@echo off
title PDF → Moodle XML

:: ── Auto-instalación si el venv no existe ─────────────────────────────
if not exist "%~dp0backend\venv\Scripts\python.exe" (
    echo.
    echo  Primera ejecucion detectada. Configurando el entorno...
    echo.

    python --version >nul 2>&1
    if errorlevel 1 (
        echo  [ERROR] Python no esta instalado o no esta en el PATH.
        echo  Descargalo desde https://www.python.org/downloads/
        echo.
        pause
        exit /b 1
    )

    echo  [1/3] Creando entorno virtual...
    python -m venv "%~dp0backend\venv"

    echo  [2/3] Instalando dependencias ^(puede tardar unos minutos^)...
    "%~dp0backend\venv\Scripts\pip.exe" install -r "%~dp0backend\requirements.txt" --quiet

    echo  [3/3] Instalando interfaz de ventana nativa...
    "%~dp0backend\venv\Scripts\pip.exe" install pywebview --quiet

    echo.
    echo  Instalacion completada.
    echo.
)

:: ── Lanzar la app en ventana nativa ───────────────────────────────────
"%~dp0backend\venv\Scripts\pythonw.exe" "%~dp0launcher.py"
