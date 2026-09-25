"""
launcher.py — Punto de entrada silencioso del ejecutable.

Estrategia:
  1. Abrir la ventana de inmediato con una splash screen HTML (sin servidor).
  2. Arrancar uvicorn en segundo plano.
  3. Cuando el servidor responde, transicionar a la app principal.
  4. Exponer API Python para el dialogo nativo "Guardar como".
"""

import sys
import os
import base64
import json
import secrets
import socket
import threading
import time
import traceback
import urllib.request
import webbrowser

# ── Log de arranque (para depurar fallos silenciosos del backend) ──────────
def _app_data_dir() -> str:
    """
    Carpeta de datos de la app para el ejecutable empaquetado — SIEMPRE
    escribible por el usuario actual. La carpeta del propio ejecutable
    (ej. "C:\\Program Files\\..." en Windows tras instalarlo) normalmente
    NO lo es para un usuario sin privilegios de administrador: escribir el
    log de errores (o la base de datos) ahí fallaba en silencio, dejando
    al usuario sin ninguna pista real de por qué la app no arrancaba.
    """
    app_name = "ConversorMoodleXML"
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    path = os.path.join(base, app_name)
    os.makedirs(path, exist_ok=True)
    return path


if getattr(sys, "frozen", False):
    LOG_PATH = os.path.join(_app_data_dir(), "launcher_error.log")
else:
    LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "launcher_error.log")


def _log(msg: str) -> None:
    try:
        # Tope de 1 MB: al pasarlo, el registro anterior queda como .1 y se
        # empieza uno nuevo.
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > 1_000_000:
            os.replace(LOG_PATH, LOG_PATH + ".1")
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass

# ── Rutas del bundle ────────────────────────────────────────────────────────
if getattr(sys, "frozen", False):
    BUNDLE_DIR = sys._MEIPASS
else:
    BUNDLE_DIR = os.path.dirname(os.path.abspath(__file__))

BACKEND_DIR = os.path.join(BUNDLE_DIR, "backend")
# ── Importar configuración centralizada ─────────────────────────────────────
# Aseguramos que el backend esté en sys.path antes de importar config
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from config import APP_VERSION, PREFIJO_DESCARGAS, SERVER_HOST
import seguridad

HOST = SERVER_HOST


def _abrir_socket() -> socket.socket:
    """
    El launcher reserva el puerto ANTES de arrancar el servidor y se lo
    entrega a uvicorn. Antes se usaba siempre el 8000: si otro programa lo
    ocupaba primero, la ventana cargaba SU página (con el puente nativo
    disponible) sin avisar. Con el puerto 0 el sistema da uno libre, y como
    el socket ya es nuestro nadie más puede escuchar en él.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if sys.platform == "win32":
        # En Windows otro proceso podría enlazar el mismo puerto con
        # SO_REUSEADDR si no se pide exclusividad.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    sock.bind((HOST, 0))
    return sock


_SOCK = _abrir_socket()
PORT = _SOCK.getsockname()[1]
URL  = f"http://{HOST}:{PORT}"
seguridad.EN_LAUNCHER = True

# Tiempo mínimo que se muestra la splash screen, sin importar qué tan rápido
# arranque el backend. Sin este mínimo, cuando el servidor respondía casi de
# inmediato (backend ya "caliente" en disco/caché del SO) la ventana saltaba
# a la app principal en una fracción de segundo — la persona ni alcanzaba a
# ver el logo o el crédito de los desarrolladores. Con esto la cinemática de
# inicio siempre se ve completa, de forma consistente en cada arranque.
MIN_SPLASH_SECONDS = 2.5


# ── API expuesta a JavaScript ───────────────────────────────────────────────
# Funciones sueltas publicadas con window.expose(), no un objeto js_api:
# pywebview resuelve el nombre que pide el JS recorriendo atributos con
# getattr, sin filtrar los que empiezan con "_". Con un objeto que guardaba
# la ventana, un JS en la página podía llegar a Api._window.gui… y de ahí
# a os.system. Ahora la ventana vive en una variable del módulo, fuera del
# alcance del puente, y lo único que el JS puede llamar son estas dos.
_VENTANA = None

# Enlaces que la app puede abrir en el navegador del sistema (la
# ventana de escritorio no abre pestañas nuevas). Lista cerrada: las
# páginas de Google para obtener la clave y ver precios, y la de descargas
# de la app (aviso de versión nueva).
_URLS_PERMITIDAS = ("https://aistudio.google.com/", "https://ai.google.dev/", PREFIJO_DESCARGAS)


def save_xml_file(filename: str, b64_content: str) -> dict:
    """
    Abre el dialogo nativo 'Guardar como', escribe el XML y devuelve
    {'saved': True, 'path': '...'} o {'saved': False}.
    """
    try:
        if _VENTANA is None:
            return {"saved": False, "error": "Ventana no disponible"}

        import webview

        # Carpeta inicial: Descargas del usuario
        downloads = os.path.join(os.path.expanduser("~"), "Downloads")
        if not os.path.isdir(downloads):
            downloads = os.path.expanduser("~")

        result = _VENTANA.create_file_dialog(
            webview.SAVE_DIALOG,
            directory=downloads,
            save_filename=os.path.basename(str(filename)),
            file_types=("Archivos XML (*.xml)", "Todos los archivos (*.*)"),
        )

        if not result:
            return {"saved": False}

        save_path = result[0] if isinstance(result, (list, tuple)) else result

        # Asegurar extension .xml
        if not save_path.lower().endswith(".xml"):
            save_path += ".xml"

        content_bytes = base64.b64decode(b64_content)
        with open(save_path, "wb") as f:
            f.write(content_bytes)

        return {"saved": True, "path": save_path}

    except Exception as exc:
        print("SAVE ERROR:", traceback.format_exc())
        return {"saved": False, "error": "Python error: " + str(exc)}


def open_url(url: str) -> bool:
    if not isinstance(url, str) or not url.startswith(_URLS_PERMITIDAS):
        return False
    return _abrir_en_navegador(url)


# pywebview abre en el navegador del sistema los enlaces que piden ventana
# nueva (window.open, target="_blank") llamando a webbrowser.open, y en
# Windows eso termina en os.startfile, que abre CUALQUIER cosa: una ruta
# file:// a un .exe incluida. Se reemplaza por una versión que solo deja
# pasar la lista de arriba.
_abrir_en_navegador = webbrowser.open


def _abrir_solo_permitidas(url, new=0, autoraise=True):
    if isinstance(url, str) and url.startswith(_URLS_PERMITIDAS):
        return _abrir_en_navegador(url, new, autoraise)
    _log(f"Enlace externo bloqueado: {str(url)[:200]}")
    return False


webbrowser.open = _abrir_solo_permitidas


# ── Splash Screen HTML ──────────────────────────────────────────────────────
# Pantalla sobria de arranque: el ícono oficial, nombre, una barra fina que avanza con
# las etapas REALES del arranque (el launcher las informa con setStage) y un
# pie con créditos y versión. Sin tarjeta de vidrio, sin halos, sin texto en
# degradado y sin mensajes inventados que rotan (ver DESIGN.md). Siempre en
# modo claro, igual que la app al abrirse.

_SPLASH_STYLE = """
    :root {
      --bg: #f1f5f9; --surface: #ffffff; --border: #d5dde8;
      --text: #0f172a; --muted: #475569; --subtle: #606f85;
      --mark: #0369a1; --accent: #0273ae; --error: #d31b44;
      --ease-out: cubic-bezier(0.23, 1, 0.32, 1);
      color-scheme: light;
    }
    * { margin: 0; padding: 0; box-sizing: border-box; }
    html, body { height: 100%; }
    body {
      background: var(--bg);
      color: var(--text);
      font-family: 'Hanken Grotesk', system-ui, -apple-system, 'Segoe UI', sans-serif;
      display: grid;
      grid-template-rows: 1fr auto;
      user-select: none;
      cursor: default;
      overflow: hidden;
      -webkit-font-smoothing: antialiased;
    }
    main {
      align-self: center;
      justify-self: center;
      width: min(440px, calc(100% - 64px));
      animation: enter 320ms var(--ease-out) both;
    }
    @keyframes enter {
      from { opacity: 0; transform: translateY(6px); }
      to   { opacity: 1; transform: none; }
    }
    .mark {
      width: 52px; height: 52px;
      border-radius: 14px;
      background: var(--mark);
      display: grid; place-items: center;
      margin-bottom: 28px;
    }
    .logo { display: block; width: 64px; height: 64px; margin: 0 0 24px -3px; }
    h1 {
      font-family: 'Outfit', 'Hanken Grotesk', system-ui, sans-serif;
      font-size: 30px;
      font-weight: 800;
      letter-spacing: -0.6px;
      line-height: 1.15;
    }
    .lead {
      margin-top: 10px;
      font-size: 15px;
      line-height: 1.55;
      color: var(--muted);
      max-width: 46ch;
    }
    .status { margin-top: 40px; }
    .track {
      height: 3px;
      background: var(--border);
      border-radius: 9999px;
      overflow: hidden;
    }
    .fill {
      height: 100%;
      background: var(--accent);
      border-radius: 9999px;
      transform: scaleX(0.04);
      transform-origin: left;
      /* Avanza con cada etapa real; entre etapas, un tramo lento hace que
         no parezca congelada mientras el servidor termina de arrancar. */
      transition: transform 1.4s var(--ease-out);
    }
    .status-row {
      display: flex; justify-content: space-between; gap: 16px;
      margin-top: 12px;
      font-size: 13px;
      color: var(--subtle);
      font-variant-numeric: tabular-nums;
    }
    #status { color: var(--muted); }
    footer {
      display: flex; justify-content: space-between; align-items: center; gap: 16px;
      padding: 18px 32px 22px;
      border-top: 1px solid var(--border);
      font-size: 12px;
      color: var(--subtle);
    }
    @media (max-width: 560px) {
      footer { flex-direction: column; gap: 4px; text-align: center; }
    }
    @media (prefers-reduced-motion: reduce) {
      main { animation-name: fade; }
      .fill { transition-duration: 0.01ms; }
    }
    @keyframes fade { from { opacity: 0; } to { opacity: 1; } }
"""

def _fuente_css(familia: str, archivo: str) -> str:
    """@font-face con la fuente incrustada: la splash se carga sin servidor
    (y sin internet no se veía la tipografía de la app)."""
    try:
        with open(os.path.join(BUNDLE_DIR, "frontend", "fonts", archivo), "rb") as f:
            datos = base64.b64encode(f.read()).decode("ascii")
    except OSError:
        return ""
    return (f"@font-face {{ font-family: '{familia}'; font-weight: 100 900; "
            f"src: url(data:font/woff2;base64,{datos}) format('woff2'); }}\n")


_SPLASH_FUENTES = (_fuente_css("Outfit", "outfit-latin-wght-normal.woff2")
                   + _fuente_css("Hanken Grotesk", "hanken-grotesk-latin-wght-normal.woff2"))

_SPLASH_HEAD = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Conversor a Moodle XML</title>
  <style>""" + _SPLASH_FUENTES + _SPLASH_STYLE + """</style>
</head>"""

_MARK_SVG = """<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#fff"
           stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
        <polyline points="14 2 14 8 20 8"/>
        <line x1="16" y1="13" x2="8" y2="13"/>
        <line x1="16" y1="17" x2="8" y2="17"/>
      </svg>"""

def _icono_data_uri() -> str:
    """El ícono oficial (assets/Icon.ico, exportado a frontend/img/icono.png)
    incrustado en el HTML: la splash se carga sin servidor, así que no puede
    pedirlo por URL. Si falta, se usa el ícono de documento de siempre."""
    try:
        with open(os.path.join(BUNDLE_DIR, "frontend", "img", "icono.png"), "rb") as f:
            return "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")
    except OSError:
        return ""


_ICONO = _icono_data_uri()
_MARCA = (f'<img class="logo" src="{_ICONO}" alt="" width="64" height="64">' if _ICONO
          else f'<div class="mark">{_MARK_SVG}</div>')

_FOOTER = f"""<footer>
    <span>Desarrollado por los ingenieros C&eacute;sar Gonz&aacute;lez y Vicente Urriola</span>
    <span>Versi&oacute;n {APP_VERSION}</span>
  </footer>"""

SPLASH_HTML = _SPLASH_HEAD + f"""
<body>
  <main>
    {_MARCA}
    <h1>Conversor a Moodle XML</h1>
    <p class="lead">Convierte tus pruebas y ex&aacute;menes en PDF o TXT al formato de Moodle, con revisi&oacute;n antes de exportar.</p>
    <div class="status" role="status" aria-live="polite">
      <div class="track" aria-hidden="true"><div class="fill" id="fill"></div></div>
      <div class="status-row">
        <span id="status">Iniciando&hellip;</span>
        <span id="pct" aria-hidden="true"></span>
      </div>
    </div>
  </main>
  {_FOOTER}
  <script>
    // El launcher llama setStage(fracción, texto) en cada etapa real.
    window.setStage = function (f, texto) {{
      document.getElementById('fill').style.transform = 'scaleX(' + Math.max(0.04, Math.min(f, 1)) + ')';
      if (texto) document.getElementById('status').textContent = texto;
    }};
  </script>
</body>
</html>"""


def _error_html(log_path: str) -> str:
    """Pantalla cuando el servidor local no arranca: mismo lenguaje visual
    que la splash, con qué pasó, qué hacer y dónde está el registro."""
    import html as _html
    return _SPLASH_HEAD + f"""
<body style="user-select:text;">
  <main>
    <div class="mark" style="background:var(--error);">
      <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2"
           stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
        <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
      </svg>
    </div>
    <h1>No se pudo iniciar el conversor</h1>
    <p class="lead">El servidor interno de la aplicaci&oacute;n no respondi&oacute; a tiempo. Cierra esta ventana y vuelve a abrir la aplicaci&oacute;n; si sigue igual, reinicia el equipo.</p>
    <p class="lead" style="margin-top:24px;font-size:13px;">Si el problema contin&uacute;a, env&iacute;a este registro al desarrollador:<br>
      <span style="color:var(--text);font-family:ui-monospace,Menlo,Consolas,monospace;word-break:break-all;">{_html.escape(log_path)}</span></p>
  </main>
  {_FOOTER}
</body>
</html>"""


# ── Server helpers ──────────────────────────────────────────────────────────
def _run_server():
    try:
        _log(f"Iniciando uvicorn en {HOST}:{PORT} (BACKEND_DIR={BACKEND_DIR})")
        import uvicorn
        servidor = uvicorn.Server(uvicorn.Config("main:app", log_level="critical"))
        servidor.run(sockets=[_SOCK])
    except BaseException:
        _log("EXCEPCION en _run_server:\n" + traceback.format_exc())


def _es_nuestro_servidor() -> bool:
    """Quien responde tiene que firmar un número al azar con el token de
    este arranque: otro programa no lo conoce (y el token nunca se envía)."""
    nonce = secrets.token_urlsafe(16)
    with urllib.request.urlopen(f"{URL}{seguridad.RUTA_SALUD}?n={nonce}", timeout=1) as r:
        firma = json.loads(r.read().decode("utf-8")).get("firma", "")
    return secrets.compare_digest(str(firma), seguridad.firma_salud(nonce))


def _wait_for_server(timeout: int = 30) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if _es_nuestro_servidor():
                return True
            _log("Quien responde en el puerto no es el servidor de la app.")
            return False
        except Exception:
            time.sleep(0.4)
    return False


# ── Entry point ─────────────────────────────────────────────────────────────
def main():
    import webview

    global _VENTANA

    window = webview.create_window(
        title="Conversor a Moodle XML",
        html=SPLASH_HTML,
        width=800,
        height=750,
        resizable=True,
        min_size=(500, 600),
        # Abre ocupando toda la pantalla (maximizada) desde la splash; la app
        # principal se carga en esta misma ventana, así que también. Se usa
        # maximizada y no el modo "pantalla completa" del sistema para que
        # la barra de título (cerrar, minimizar) siga visible: en Windows,
        # fullscreen no deja botón para cerrar.
        maximized=True,
    )

    # Lo único que el JS de la ventana puede llamar en Python (ver arriba).
    _VENTANA = window
    window.expose(save_xml_file, open_url)

    def _stage(fraccion: float, texto: str) -> None:
        # Informa una etapa REAL del arranque a la splash (barra + texto).
        try:
            window.evaluate_js(f"window.setStage && window.setStage({fraccion}, {json.dumps(texto)})")
        except Exception:
            pass

    def _start_backend():
        try:
            start_time = time.time()
            _stage(0.35, "Iniciando el servidor local…")
            threading.Thread(target=_run_server, daemon=True).start()
            time.sleep(0.4)
            _stage(0.7, "Cargando el conversor…")
            server_ready = _wait_for_server()

            if server_ready:
                _stage(1.0, "Listo")
            # Completa el tiempo restante hasta el mínimo antes de navegar, para
            # que la splash dure siempre lo mismo (nunca menos) sin importar si
            # el servidor respondió en 200ms o en 4 segundos.
            elapsed = time.time() - start_time
            remaining = MIN_SPLASH_SECONDS - elapsed
            if remaining > 0:
                time.sleep(remaining)

            if server_ready:
                # El token va en el fragmento (#): el navegador no lo envía al
                # servidor ni queda en registros; la página lo lee y lo manda
                # en cada petición a /api/ (ver frontend/js/api.js).
                window.load_url(f"{URL}/#t={seguridad.TOKEN}")
            else:
                _log("El backend no respondio dentro del timeout.")
                window.load_html(_error_html(LOG_PATH))
        except Exception:
            _log("EXCEPCION en _start_backend:\n" + traceback.format_exc())

    webview.start(func=_start_backend)
    sys.exit(0)


if __name__ == "__main__":
    main()
