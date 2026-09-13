@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo   Conversor a Moodle XML - Generador de instalador Windows
echo ============================================================
echo.

REM ── 1. Entorno virtual de compilacion (temporal, no se distribuye) ────
if not exist "build_venv\Scripts\python.exe" (
    echo [1/4] Creando entorno virtual de compilacion...
    python --version >nul 2>&1
    if errorlevel 1 (
        echo.
        echo [ERROR] Python no esta instalado o no esta en el PATH.
        echo Descargalo desde https://www.python.org/downloads/
        echo Al instalarlo, marca la casilla "Add Python to PATH".
        echo.
        pause
        exit /b 1
    )
    python -m venv build_venv
) else (
    echo [1/4] Entorno virtual de compilacion ya existe, se reutiliza.
)

echo [2/4] Instalando dependencias...
"build_venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
"build_venv\Scripts\pip.exe" install --quiet -r backend\requirements.txt
"build_venv\Scripts\pip.exe" install --quiet pywebview pyinstaller
if errorlevel 1 (
    echo.
    echo [ERROR] Fallo instalando dependencias. Revisa tu conexion a internet.
    pause
    exit /b 1
)

echo [3/4] Compilando el ejecutable (PyInstaller)...
"build_venv\Scripts\python.exe" build.py
if errorlevel 1 (
    echo.
    echo [ERROR] La compilacion con PyInstaller fallo. Revisa los mensajes de arriba.
    pause
    exit /b 1
)

echo [4/4] Generando el instalador con Inno Setup...
set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    echo.
    echo [ERROR] No se encontro Inno Setup 6.
    echo Descargalo gratis desde https://jrsoftware.org/isdl.php e instalalo
    echo con las opciones por defecto, luego vuelve a correr este script.
    echo.
    pause
    exit /b 1
)

"%ISCC%" installer.iss
if errorlevel 1 (
    echo.
    echo [ERROR] Inno Setup fallo al compilar el instalador.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   Listo. Instalador generado en:
echo   %~dp0Output\ConversorMoodleXML_Setup.exe
echo ============================================================
pause
