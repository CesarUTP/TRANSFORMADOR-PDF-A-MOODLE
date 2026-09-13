"""
build.py — Construye ConvertidorMoodle.exe con PyInstaller (Windows).

No se corre a mano: lo invoca build_windows.bat después de crear el
entorno virtual de compilación (build_venv) e instalar las dependencias.
"""
import subprocess
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
VENV_PYINSTALLER = os.path.join(HERE, "build_venv", "Scripts", "pyinstaller.exe")

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
    "--collect-all", "google.generativeai",
    "--collect-all", "google.api_core",
    "--collect-all", "grpc",
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
]

print("Construyendo ConvertidorMoodle.exe ...")
print("(Esto puede tardar 3-5 minutos)\n")

result = subprocess.run(cmd, cwd=HERE)

if result.returncode == 0:
    print("\n[OK] Build exitoso.")
    print("  El ejecutable esta en: dist\\ConvertidorMoodle\\")
else:
    print("\n[ERROR] Build fallido. Revisa los mensajes de arriba.")
    sys.exit(1)
