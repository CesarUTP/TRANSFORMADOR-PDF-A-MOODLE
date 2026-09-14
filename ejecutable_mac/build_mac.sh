#!/bin/bash
# build_mac.sh — Genera ConvertidorMoodle.app y el instalador .dmg (macOS).
set -e
cd "$(dirname "$0")"

echo "============================================================"
echo "  Conversor a Moodle XML - Generador de instalador macOS"
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
"build_venv/bin/pip" install --quiet -r backend/requirements.txt
"build_venv/bin/pip" install --quiet pywebview pyinstaller pyobjc

echo "[3/4] Compilando la app (PyInstaller)..."
"build_venv/bin/python3" build.py

echo "[4/4] Generando el instalador .dmg..."
rm -f dist/ConvertidorMoodle.app/Contents/MacOS/launcher_error.log
rm -rf dist/dmg_staging
mkdir -p dist/dmg_staging
cp -R dist/ConvertidorMoodle.app dist/dmg_staging/
ln -s /Applications dist/dmg_staging/Aplicaciones

hdiutil create -volname "Conversor a Moodle XML" \
    -srcfolder dist/dmg_staging \
    -ov -format UDZO \
    dist/ConversorMoodleXML.dmg

rm -rf dist/dmg_staging

echo ""
echo "============================================================"
echo "  Listo. Instalador generado en:"
echo "  $(pwd)/dist/ConversorMoodleXML.dmg"
echo "============================================================"
read -p "Presiona Enter para salir..."
