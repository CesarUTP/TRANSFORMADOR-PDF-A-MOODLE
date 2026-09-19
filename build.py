"""
build.py — Construye ConvertidorMoodle.exe con PyInstaller.

Ejecutar desde la carpeta pdf-to-moodle con:
    .\\backend\\venv\\Scripts\\python build.py
"""
import subprocess
import sys
import os

VENV_PYINSTALLER = os.path.join(
    os.path.dirname(__file__),
    "backend", "venv", "Scripts", "pyinstaller.exe"
)

cmd = [
    VENV_PYINSTALLER,
    "launcher.py",
    "--onedir",
    "--noconsole",
    "--name", "ConvertidorMoodle",
    "--noconfirm",
    # ── Icono del ejecutable ─────────────────────────────────────────────
    "--icon", "assets/Icon.ico",
    # ── Datos a incluir ─────────────────────────────────────────────────
    "--add-data", "frontend;frontend",
    "--add-data", "backend;backend",
    "--add-data", "assets/Icon.ico;.",
    # ── Rutas de busqueda de modulos ────────────────────────────────────
    "--paths", "backend",
    # ── Paquetes con imports dinamicos (FastAPI / Uvicorn / Starlette) ──
    "--collect-all", "fastapi",
    "--collect-all", "uvicorn",
    "--collect-all", "starlette",
    "--collect-all", "anyio",
    "--collect-all", "pdfplumber",
    "--collect-all", "pdfminer",
    "--collect-all", "lxml",
    "--collect-all", "python_multipart",
    # ── Llamada a Gemini: API REST directa con requests (formatter.py), sin
    # el SDK de Google. Como backend/ va como datos, requests y su cadena
    # (certificados HTTPS incluidos) hay que declararlos a mano: antes
    # entraban de rebote con google.generativeai ──────────────────────────
    "--collect-all", "requests",
    "--collect-all", "urllib3",
    "--collect-all", "certifi",
    "--collect-all", "charset_normalizer",
    "--collect-all", "idna",
    # ── PyWebView y su backend para Windows (Edge Chromium) ─────────────
    "--collect-all", "webview",
    "--hidden-import", "webview.platforms.winforms",
    "--hidden-import", "clr",
    "--hidden-import", "System.Windows.Forms",
    # ── Hidden imports de FastAPI / Uvicorn ──────────────────────────────
    "--hidden-import", "uvicorn.protocols.http.auto",
    "--hidden-import", "uvicorn.protocols.http.h11_impl",
    "--hidden-import", "uvicorn.protocols.websockets.auto",
    "--hidden-import", "uvicorn.lifespan.on",
    "--hidden-import", "uvicorn.logging",
    "--hidden-import", "anyio._backends._asyncio",
    "--hidden-import", "anyio._backends._trio",
    "--hidden-import", "multipart",
    "--hidden-import", "email.mime.text",
    "--hidden-import", "email.mime.multipart",
    # ── database.py usa sqlite3; al vivir en backend/ (agregado como datos,
    # no como código analizado por PyInstaller) su import nunca se detecta
    # automáticamente y hay que declararlo a mano ──────────────────────────
    "--hidden-import", "sqlite3",
    # ── extractor.py renderiza páginas de PDF como imagen (PIL/Pillow vía
    # pypdfium2, para que Gemini pueda leer código en capturas de pantalla
    # y respuestas marcadas solo por color) — mismo problema que sqlite3:
    # al vivir en backend/ como datos, no se detecta solo ──────────────────
    "--collect-all", "PIL",
    "--hidden-import", "pypdfium2",
]

print("Construyendo ConvertidorMoodle.exe ...")
print("(Esto puede tardar 3-5 minutos)\n")

result = subprocess.run(cmd, cwd=os.path.dirname(os.path.abspath(__file__)))

if result.returncode == 0:
    print("\n[OK] Build exitoso.")
    print("  El ejecutable esta en: dist\\ConvertidorMoodle.exe")
else:
    print("\n[ERROR] Build fallido. Revisa los mensajes de arriba.")
    sys.exit(1)
