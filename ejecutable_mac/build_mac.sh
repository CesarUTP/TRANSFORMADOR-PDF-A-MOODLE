#!/bin/bash
# build_mac.sh — Genera Catedra.app y el instalador .dmg (macOS).
set -e
cd "$(dirname "$0")"

echo "============================================================"
echo "  Cátedra - Generador de instalador macOS"
echo "============================================================"
echo ""

# ── 1. Entorno virtual de compilacion (temporal, no se distribuye) ────
if [ ! -f "build_venv/bin/python3" ]; then
    echo "[1/4] Creando entorno virtual de compilacion..."
    if ! command -v python3 >/dev/null 2>&1; then
        echo ""
        echo "[ERROR] Python 3 no esta instalado o no esta en el PATH."
        echo "Descargalo desde https://www.python.org/downloads/"
        echo ""
        read -p "Presiona Enter para salir..."
        exit 1
    fi
    python3 -m venv build_venv
else
    echo "[1/4] Entorno virtual de compilacion ya existe, se reutiliza."
fi

echo "[2/4] Instalando dependencias..."
"build_venv/bin/pip" install --quiet --upgrade pip
# Todas las dependencias (también las indirectas) con versión exacta y su
# huella SHA-256: pip rechaza cualquier paquete que no coincida.
"build_venv/bin/pip" install --quiet --require-hashes -r requirements-build.lock

echo "[3/4] Compilando la app (PyInstaller)..."
"build_venv/bin/python3" build.py

echo "[4/4] Generando el instalador .dmg..."
rm -f dist/Catedra.app/Contents/MacOS/launcher_error.log
rm -rf dist/dmg_staging
mkdir -p dist/dmg_staging
cp -R dist/Catedra.app dist/dmg_staging/
ln -s /Applications dist/dmg_staging/Aplicaciones

hdiutil create -volname "Cátedra" \
    -srcfolder dist/dmg_staging \
    -ov -format UDZO \
    dist/Catedra.dmg

rm -rf dist/dmg_staging

echo ""
echo "============================================================"
echo "  Listo. Instalador generado en:"
echo "  $(pwd)/dist/Catedra.dmg"
echo "============================================================"
read -p "Presiona Enter para salir..."
