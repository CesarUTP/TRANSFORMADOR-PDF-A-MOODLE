"""
build.py — Construye Catedra.app con PyInstaller (macOS).

Ejecutar desde esta carpeta con:
    ./venv/bin/python build.py
(o con el Python que tenga pyinstaller instalado)
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

cmd = [
    sys.executable, "-m", "PyInstaller",
    "launcher.py",
    "--onedir",
    "--windowed",
    "--name", "Catedra",
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
    # API de Gemini: clave.dat cifrado (backend/credenciales.py).
    "--collect-all", "cryptography",
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
    # seguridad.py y extractor.py (backend/ va como datos: sus imports no se detectan)
    "--hidden-import", "hmac",
    "--hidden-import", "secrets",
    "--hidden-import", "bisect",
    # extractor_docx.py e imagenes.py (Word, imágenes de las preguntas)
    "--hidden-import", "zipfile",
    "--hidden-import", "dataclasses",
    # ── extractor.py renderiza páginas de PDF como imagen (PIL/Pillow vía
    # pypdfium2, para que Gemini pueda leer código en capturas de pantalla
    # y respuestas marcadas solo por color) — mismo problema que sqlite3:
    # al vivir en backend/ como datos, no se detecta solo ──────────────────
    "--collect-all", "PIL",
    "--hidden-import", "pypdfium2",
    # ── exportar_pdf.py (PDF imprimible del examen): reportlab y su detector
    # de codificaciones; backend/ va como datos, así que tampoco se detectan
    # solos los módulos estándar que solo usa el código de backend/ ─────────
    "--collect-all", "reportlab",
    "--collect-all", "chardet",
    "--hidden-import", "random",
    "--hidden-import", "unicodedata",
    "--hidden-import", "base64",
]

print("Construyendo Catedra.app ...")
print("(Esto puede tardar 3-5 minutos)\n")

# Avisos de terceros («Acerca de»): con ESTE Python, que es el que se
# empaqueta, para que la lista coincida con lo que va dentro de la app.
subprocess.run([sys.executable, "generar_avisos_terceros.py",
                os.path.join("frontend", "legal", "avisos-terceros.txt")], cwd=HERE, check=True)

result = subprocess.run(cmd, cwd=HERE)

if result.returncode == 0:
    print("\n[OK] Build exitoso.")
    # El archivo se llama Catedra.app (sin tilde, por seguridad con las rutas), pero la app debe llamarse «Cátedra»
    # en la barra de menús y en el Finder: se pone en su Info.plist y se vuelve a firmar (cambiar el plist rompe la
    # firma, y en un Mac con Apple Silicon una app con la firma rota no abre). Si algo falla se deja como estaba.
    import plistlib
    _app = os.path.join(HERE, "dist", "Catedra.app")
    _plist = os.path.join(_app, "Contents", "Info.plist")
    try:
        with open(_plist, "rb") as _f:
            _original = _f.read()
        _datos = plistlib.loads(_original)
        _datos["CFBundleName"] = "Cátedra"
        _datos["CFBundleDisplayName"] = "Cátedra"
        with open(_plist, "wb") as _f:
            plistlib.dump(_datos, _f)
        _firma = subprocess.run(["codesign", "--force", "--deep", "--sign", "-", _app], capture_output=True, text=True)
        if _firma.returncode != 0:
            raise RuntimeError(_firma.stderr.strip() or "codesign falló")
        print("  Nombre mostrado: Cátedra (firmada de nuevo)")
    except Exception as _e:  # noqa: BLE001
        try:
            with open(_plist, "wb") as _f:
                _f.write(_original)
        except Exception:  # noqa: BLE001
            pass
        print(f"  [AVISO] No se pudo poner el nombre «Cátedra» en el Info.plist ({_e}); la app se llamará «Catedra».")
    print("  La app esta en: dist/Catedra.app")
else:
    print("\n[ERROR] Build fallido. Revisa los mensajes de arriba.")
    sys.exit(1)
