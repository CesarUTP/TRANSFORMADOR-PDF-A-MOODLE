#!/bin/bash
# iniciar.command — Doble clic para abrir "PDF → Moodle XML" en macOS.

cd "$(dirname "$0")" || exit 1

VENV_DIR="backend/venv"
PYTHON_BIN="$VENV_DIR/bin/python3"

echo ""
echo "PDF → Moodle XML"
echo ""

# ── Auto-instalación si el venv no existe ─────────────────────────────
if [ ! -f "$PYTHON_BIN" ]; then
    echo "Primera ejecución detectada. Configurando el entorno..."
    echo ""

    if ! command -v python3 >/dev/null 2>&1; then
        echo "[ERROR] Python 3 no está instalado o no está en el PATH."
        echo "Descárgalo desde https://www.python.org/downloads/"
        echo ""
        read -p "Presiona Enter para salir..."
        exit 1
    fi

    echo "[1/3] Creando entorno virtual..."
    python3 -m venv "$VENV_DIR"

    echo "[2/3] Instalando dependencias (puede tardar unos minutos)..."
    "$VENV_DIR/bin/pip" install -r backend/requirements.txt --quiet

    echo "[3/3] Instalando interfaz de ventana nativa..."
    "$VENV_DIR/bin/pip" install pywebview --quiet

    echo ""
    echo "Instalación completada."
    echo ""
fi

# ── Lanzar la app en ventana nativa ───────────────────────────────────
"$PYTHON_BIN" launcher.py
