@echo off
title PDF → Moodle XML

:: ── Verificar que el venv existe ──────────────────────────────────────
if not exist "%~dp0backend\venv\Scripts\python.exe" (
    echo [ERROR] No se encontro el entorno virtual.
    echo Ejecuta primero desde la carpeta backend:
    echo     python -m venv venv
    echo     .\venv\Scripts\pip install -r requirements.txt
    echo     .\venv\Scripts\pip install pywebview
    echo.
    pause
    exit /b 1
)

:: ── Lanzar la app en ventana nativa (sin navegador) ────────────────────
"%~dp0backend\venv\Scripts\pythonw.exe" "%~dp0launcher.py"
