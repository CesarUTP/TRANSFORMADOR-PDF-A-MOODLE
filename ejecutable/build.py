"""
build.py — Construye ConvertidorMoodle.exe con PyInstaller (Windows).

No se corre a mano: lo invoca build_windows.bat después de crear el
entorno virtual de compilación (build_venv) e instalar las dependencias.
"""
import subprocess
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))


# backend/ y frontend/ se empaquetan enteros (--add-data): cualquier archivo
# que haya ahí viaja dentro de la app. Si hay una clave, una base de datos o
# un registro, se detiene la compilación en vez de repartirlos.
_PROHIBIDOS = (".env", "clave.dat")
_EXTENSIONES_PROHIBIDAS = (".db", ".sqlite", ".log")
_encontrados = []
for _carpeta in ("backend", "frontend"):
    for _raiz, _dirs, _archivos in os.walk(os.path.join(HERE, _carpeta)):
        _dirs[:] = [d for d in _dirs if d not in ("venv", "__pycache__")]
        for _a in _archivos:
            if _a.startswith(_PROHIBIDOS) or _a.endswith(_EXTENSIONES_PROHIBIDAS):
                _encontrados.append(os.path.relpath(os.path.join(_raiz, _a), HERE))
if _encontrados:
    print("[ERROR] Estos archivos no deben ir dentro de la app. Bórralos o muévelos y vuelve a compilar:")
    for _r in _encontrados:
        print("   -", _r)
    sys.exit(1)
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
    # ── Llamada a Gemini: API REST directa con requests (formatter.py), sin
    # el SDK de Google. Como backend/ va como datos, requests y su cadena
    # (certificados HTTPS incluidos) hay que declararlos a mano: antes
    # entraban de rebote con google.generativeai ──────────────────────────
    "--collect-all", "requests",
    "--collect-all", "urllib3",
    "--collect-all", "certifi",
    "--collect-all", "charset_normalizer",
    "--collect-all", "idna",
    # API de Gemini: clave.dat cifrado (backend/credenciales.py).
    "--collect-all", "cryptography",
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
    # seguridad.py y extractor.py (backend/ va como datos: sus imports no se detectan)
    "--hidden-import", "hmac",
    "--hidden-import", "secrets",
    "--hidden-import", "bisect",
    # ── extractor.py renderiza páginas de PDF como imagen (PIL/Pillow vía
    # pypdfium2, para que Gemini pueda leer código en capturas de pantalla
    # y respuestas marcadas solo por color) — mismo problema que sqlite3:
    # al vivir en backend/ como datos, no se detecta solo ──────────────────
    "--collect-all", "PIL",
    "--hidden-import", "pypdfium2",
]

print("Construyendo ConvertidorMoodle.exe ...")
print("(Esto puede tardar 3-5 minutos)\n")

# Avisos de terceros («Acerca de»): con ESTE Python, que es el que se
# empaqueta, para que la lista coincida con lo que va dentro de la app.
subprocess.run([sys.executable, "generar_avisos_terceros.py",
                os.path.join("frontend", "legal", "avisos-terceros.txt")], cwd=HERE, check=True)

result = subprocess.run(cmd, cwd=HERE)

if result.returncode == 0:
    print("\n[OK] Build exitoso.")
    print("  El ejecutable esta en: dist\\ConvertidorMoodle\\")
else:
    print("\n[ERROR] Build fallido. Revisa los mensajes de arriba.")
    sys.exit(1)
