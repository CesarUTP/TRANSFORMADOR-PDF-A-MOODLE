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
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@600;700;800&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }

    body {
      background: #090d16;
      background-image: 
        radial-gradient(at 0% 0%, rgba(2, 132, 199, 0.25) 0px, transparent 50%),
        radial-gradient(at 100% 100%, rgba(56, 189, 248, 0.2) 0px, transparent 50%);
      color: #f8fafc;
      font-family: 'Plus Jakarta Sans', system-ui, -apple-system, sans-serif;
      height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      user-select: none;
      overflow: hidden;
      -webkit-font-smoothing: antialiased;
    }

    .splash-card {
      background: rgba(19, 28, 49, 0.75);
      border: 1px solid rgba(255, 255, 255, 0.12);
      border-radius: 28px;
      padding: 48px 40px;
      text-align: center;
      box-shadow: 0 20px 50px rgba(0, 0, 0, 0.45), 0 0 30px rgba(56, 189, 248, 0.2);
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
      display: flex;
      flex-direction: column;
      align-items: center;
      max-width: 420px;
      width: 90%;
      animation: popIn 0.5s cubic-bezier(0.16, 1, 0.3, 1) forwards;
    }

    @keyframes popIn {
      from { transform: scale(0.92) translateY(12px); opacity: 0; }
      to   { transform: scale(1) translateY(0); opacity: 1; }
    }

    .logo-wrap {
      width: 76px;
      height: 76px;
      background: linear-gradient(135deg, #0284c7 0%, #38bdf8 50%, #818cf8 100%);
      border-radius: 20px;
      display: flex;
      align-items: center;
      justify-content: center;
      margin-bottom: 24px;
      box-shadow: 0 0 30px rgba(56, 189, 248, 0.4);
      animation: pulseGlow 3s infinite alternate cubic-bezier(0.16, 1, 0.3, 1);
    }

    @keyframes pulseGlow {
      from { transform: scale(1); box-shadow: 0 0 25px rgba(56, 189, 248, 0.3); }
      to   { transform: scale(1.04); box-shadow: 0 0 40px rgba(56, 189, 248, 0.6); }
    }

    .app-name {
      font-family: 'Outfit', sans-serif;
      font-size: 28px;
      font-weight: 800;
      letter-spacing: -0.6px;
      margin-bottom: 6px;
      background: linear-gradient(135deg, #0284c7 0%, #38bdf8 50%, #818cf8 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }

    .app-sub {
      font-size: 13.5px;
      color: #94a3b8;
      font-weight: 500;
      margin-bottom: 36px;
    }

    .progress-wrap {
      width: 100%;
    }

    .bar-bg {
      height: 6px;
      background: rgba(9, 13, 22, 0.8);
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 9999px;
      overflow: hidden;
      margin-bottom: 14px;
    }

    .bar-fill {
      height: 100%;
      background: linear-gradient(90deg, #0284c7 0%, #38bdf8 50%, #818cf8 100%);
      border-radius: 9999px;
      animation: slide 1.6s ease-in-out infinite;
      transform-origin: left center;
    }

    @keyframes slide {
      0%   { transform: translateX(-100%) scaleX(.35); }
      50%  { transform: translateX(55%)   scaleX(.65); }
      100% { transform: translateX(210%)  scaleX(.35); }
    }

    .status-text {
      font-size: 13px;
      color: #94a3b8;
      font-weight: 600;
      text-align: center;
      min-height: 20px;
      transition: opacity 0.25s;
    }

    .dev-credit {
      position: fixed;
      bottom: 28px;
      font-size: 12px;
      color: #64748b;
      font-weight: 500;
      letter-spacing: 0.2px;
    }
  </style>
</head>
<body>
  <div class="splash-card">
    <div class="logo-wrap">
      <svg width="36" height="36" viewBox="0 0 24 24" fill="none"
           stroke="#fff" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
        <polyline points="14 2 14 8 20 8"/>
        <line x1="16" y1="13" x2="8" y2="13"/>
        <line x1="16" y1="17" x2="8" y2="17"/>
      </svg>
    </div>
    <div class="app-name">PDF &rarr; Moodle XML</div>
    <div class="app-sub">Conversor de Ex&aacute;menes Universitarios</div>
    <div class="progress-wrap">
      <div class="bar-bg"><div class="bar-fill"></div></div>
      <div class="status-text" id="status">Iniciando aplicaci&oacute;n&hellip;</div>
    </div>
  </div>
  <div class="dev-credit">Desarrollado por los ingenieros C&eacute;sar Gonz&aacute;lez y Vicente Urriola</div>
  <script>
    const msgs = [
      "Iniciando aplicaci\u00f3n\u2026",
      "Cargando dependencias\u2026",
      "Configurando servidor backend\u2026",
      "Preparando interfaz de alta precisi\u00f3n\u2026",
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
        width=800,
        height=750,
        resizable=True,
        min_size=(500, 600),
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
