"""
build.py — Construye ConvertidorMoodle.app con PyInstaller (macOS).

Ejecutar desde esta carpeta con:
    ./venv/bin/python build.py
(o con el Python que tenga pyinstaller instalado)
"""
import subprocess
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))

cmd = [
    sys.executable, "-m", "PyInstaller",
    "launcher.py",
    "--onedir",
    "--windowed",
    "--name", "ConvertidorMoodle",
    "--noconfirm",
    # ── Icono de la app ──────────────────────────────────────────────────
    "--icon", "assets/Icon.icns",
    # ── Datos a incluir (separador ":" en macOS/Linux, ";" en Windows) ──
    "--add-data", "frontend:frontend",
    "--add-data", "backend:backend",
    "--add-data", "assets/Icon.icns:.",
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
    # ── PyWebView y su backend para macOS (Cocoa/WebKit vía pyobjc) ─────
    "--collect-all", "webview",
    "--hidden-import", "webview.platforms.cocoa",
    "--collect-all", "objc",
    "--collect-all", "WebKit",
    "--collect-all", "Quartz",
    "--collect-all", "AppKit",
    "--collect-all", "Foundation",
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

print("Construyendo ConvertidorMoodle.app ...")
print("(Esto puede tardar 3-5 minutos)\n")

result = subprocess.run(cmd, cwd=HERE)

if result.returncode == 0:
    print("\n[OK] Build exitoso.")
    print("  La app esta en: dist/ConvertidorMoodle.app")
else:
    print("\n[ERROR] Build fallido. Revisa los mensajes de arriba.")
    sys.exit(1)
