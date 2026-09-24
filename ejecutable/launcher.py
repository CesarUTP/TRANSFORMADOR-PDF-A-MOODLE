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
import threading
import time
import traceback
import urllib.request

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

from config import SERVER_HOST, SERVER_PORT

HOST = SERVER_HOST
PORT = SERVER_PORT
URL  = f"http://{HOST}:{PORT}"

# Tiempo mínimo que se muestra la splash screen, sin importar qué tan rápido
# arranque el backend. Sin este mínimo, cuando el servidor respondía casi de
# inmediato (backend ya "caliente" en disco/caché del SO) la ventana saltaba
# a la app principal en una fracción de segundo — la persona ni alcanzaba a
# ver el logo o el crédito de los desarrolladores. Con esto la cinemática de
# inicio siempre se ve completa, de forma consistente en cada arranque.
MIN_SPLASH_SECONDS = 2.5


# ── API expuesta a JavaScript ───────────────────────────────────────────────
class Api:
    """Funciones Python accesibles desde el JS de la app via window.pywebview.api"""

    def __init__(self):
        self._window = None

    def _set_window(self, window):
        self._window = window

    def save_xml_file(self, filename: str, b64_content: str) -> dict:
        """
        Abre el dialogo nativo 'Guardar como', escribe el XML y devuelve
        {'saved': True, 'path': '...'} o {'saved': False}.
        """
        try:
            if self._window is None:
                return {"saved": False, "error": "Ventana no disponible"}

            import webview

            # Carpeta inicial: Descargas del usuario
            downloads = os.path.join(os.path.expanduser("~"), "Downloads")
            if not os.path.isdir(downloads):
                downloads = os.path.expanduser("~")

            result = self._window.create_file_dialog(
                webview.SAVE_DIALOG,
                directory=downloads,
                save_filename=filename,
                file_types=("Archivos XML (*.xml)", "Todos los archivos (*.*)"),
            )

            if not result:
                return {"saved": False}

            save_path = result[0] if isinstance(result, (list, tuple)) else result

            # Asegurar extension .xml
            if not save_path.lower().endswith(".xml"):
                save_path += ".xml"

            import base64
            content_bytes = base64.b64decode(b64_content)
            with open(save_path, "wb") as f:
                f.write(content_bytes)
            
            return {"saved": True, "path": save_path}
        
        except Exception as exc:
            import traceback
            print("SAVE ERROR:", traceback.format_exc())
            return {"saved": False, "error": "Python error: " + str(exc)}

    # Enlaces que la app puede abrir en el navegador del sistema (la
    # ventana de escritorio no abre pestañas nuevas). Lista cerrada: solo
    # las páginas de Google para obtener la clave y ver precios.
    _URLS_PERMITIDAS = ("https://aistudio.google.com/", "https://ai.google.dev/")

    def open_url(self, url: str) -> bool:
        if not isinstance(url, str) or not url.startswith(self._URLS_PERMITIDAS):
            return False
        import webbrowser
        return webbrowser.open(url)



# ── Splash Screen HTML ──────────────────────────────────────────────────────
# Pantalla sobria de arranque: el ícono oficial, nombre, una barra fina que avanza con
# las etapas REALES del arranque (el launcher las informa con setStage) y un
# pie con créditos y versión. Sin tarjeta de vidrio, sin halos, sin texto en
# degradado y sin mensajes inventados que rotan (ver DESIGN.md). Siempre en
# modo claro, igual que la app al abrirse.
APP_VERSION = "1.1"

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

_SPLASH_HEAD = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Conversor a Moodle XML</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@700;800&family=Hanken+Grotesk:wght@400;500;600&display=swap" rel="stylesheet">
  <style>""" + _SPLASH_STYLE + """</style>
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
        uvicorn.run("main:app", host=HOST, port=PORT, log_level="critical")
    except Exception:
        _log("EXCEPCION en _run_server:\n" + traceback.format_exc())


def _wait_for_server(timeout: int = 30) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(URL, timeout=1)
            return True
        except Exception:
            time.sleep(0.4)
    return False


# ── Entry point ─────────────────────────────────────────────────────────────
def main():
    import webview

    api = Api()

    window = webview.create_window(
        title="Conversor a Moodle XML",
        html=SPLASH_HTML,
        js_api=api,          # <-- expone api.save_xml_file() a JS
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

    # Guardar referencia de la ventana en el api para los dialogos
    api._set_window(window)

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
                window.load_url(URL)
            else:
                _log("El backend no respondio dentro del timeout.")
                window.load_html(_error_html(LOG_PATH))
        except Exception:
            _log("EXCEPCION en _start_backend:\n" + traceback.format_exc())

    webview.start(func=_start_backend)
    sys.exit(0)


if __name__ == "__main__":
    main()
