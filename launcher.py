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
import threading
import time
import urllib.request

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



# ── Splash Screen HTML ──────────────────────────────────────────────────────
SPLASH_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8"/>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }

    body {
      background: #171614;
      color: #cdccca;
      font-family: -apple-system, 'Segoe UI', system-ui, sans-serif;
      height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      user-select: none;
    }

    .logo-wrap {
      width: 72px; height: 72px;
      background: #01696f;
      border-radius: 20px;
      display: flex; align-items: center; justify-content: center;
      margin-bottom: 28px;
      box-shadow: 0 8px 32px rgba(1,105,111,0.35);
      animation: pop .5s cubic-bezier(.34,1.56,.64,1) forwards;
    }
    @keyframes pop {
      from { transform: scale(0.7); opacity: 0; }
      to   { transform: scale(1);   opacity: 1; }
    }

    .app-name {
      font-size: 30px;
      font-weight: 700;
      color: #f0efed;
      letter-spacing: -0.6px;
      margin-bottom: 8px;
      animation: fadein .6s ease .15s both;
    }
    .app-sub {
      font-size: 14px;
      color: #5a5957;
      margin-bottom: 56px;
      animation: fadein .6s ease .25s both;
    }
    @keyframes fadein {
      from { opacity: 0; transform: translateY(6px); }
      to   { opacity: 1; transform: translateY(0); }
    }

    .progress-wrap {
      width: 300px;
      animation: fadein .6s ease .35s both;
    }
    .bar-bg {
      height: 3px;
      background: #252422;
      border-radius: 3px;
      overflow: hidden;
      margin-bottom: 16px;
    }
    .bar-fill {
      height: 100%;
      background: linear-gradient(90deg, #01696f 0%, #4f98a3 100%);
      border-radius: 3px;
      animation: slide 1.5s ease-in-out infinite;
      transform-origin: left center;
    }
    @keyframes slide {
      0%   { transform: translateX(-100%) scaleX(.35); }
      50%  { transform: translateX(55%)   scaleX(.65); }
      100% { transform: translateX(210%)  scaleX(.35); }
    }
    .status-text {
      font-size: 12.5px;
      color: #5a5957;
      text-align: center;
      letter-spacing: .2px;
      min-height: 18px;
      transition: opacity .3s;
    }

    .dev-credit {
      position: fixed;
      bottom: 30px;
      font-size: 11.5px;
      color: #383634;
      letter-spacing: .3px;
    }
  </style>
</head>
<body>
  <div class="logo-wrap">
    <svg width="34" height="34" viewBox="0 0 24 24" fill="none"
         stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
      <polyline points="14 2 14 8 20 8"/>
      <line x1="16" y1="13" x2="8" y2="13"/>
      <line x1="16" y1="17" x2="8" y2="17"/>
      <polyline points="10 9 9 9 8 9"/>
    </svg>
  </div>
  <div class="app-name">PDF &rarr; Moodle XML</div>
  <div class="app-sub">Conversor de Ex&aacute;menes Universitarios</div>
  <div class="progress-wrap">
    <div class="bar-bg"><div class="bar-fill"></div></div>
    <div class="status-text" id="status">Iniciando aplicaci&oacute;n&hellip;</div>
  </div>
  <div class="dev-credit">Desarrollado por C&eacute;sar O. Gonz&aacute;lez-Camargo</div>
  <script>
    const msgs = [
      "Iniciando aplicaci\u00f3n\u2026",
      "Cargando dependencias\u2026",
      "Configurando servidor\u2026",
      "Preparando la interfaz\u2026",
      "Casi listo\u2026"
    ];
    let i = 0;
    const el = document.getElementById('status');
    setInterval(() => {
      el.style.opacity = '0';
      setTimeout(() => {
        i = (i + 1) % msgs.length;
        el.textContent = msgs[i];
        el.style.opacity = '1';
      }, 200);
    }, 1400);
  </script>
</body>
</html>"""


# ── Server helpers ──────────────────────────────────────────────────────────
def _run_server():
    import uvicorn
    uvicorn.run("main:app", host=HOST, port=PORT, log_level="critical")


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
        title="PDF → Moodle XML",
        html=SPLASH_HTML,
        js_api=api,          # <-- expone api.save_xml_file() a JS
        width=1000,
        height=850,
        resizable=True,
        min_size=(800, 650),
    )

    # Guardar referencia de la ventana en el api para los dialogos
    api._set_window(window)

    def _start_backend():
        threading.Thread(target=_run_server, daemon=True).start()
        if _wait_for_server():
            window.load_url(URL)

    webview.start(func=_start_backend)
    sys.exit(0)


if __name__ == "__main__":
    main()
