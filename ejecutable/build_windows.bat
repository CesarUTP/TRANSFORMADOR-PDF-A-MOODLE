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
"build_venv\Scripts\pip.exe" install --quiet "pywebview==6.2.1" "pyinstaller==6.22.3"
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
set "ISCC="

REM Se busca primero en el registro de Windows (funciona sin importar la
REM version de Inno Setup instalada: 6, 7, la que sea) y solo si eso falla
REM se prueban rutas fijas conocidas como respaldo.
for /f "tokens=2,*" %%A in ('reg query "HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\ISCC.exe" /ve 2^>nul ^| findstr /i "REG_SZ"') do set "ISCC=%%B"
if not defined ISCC (
    for /f "tokens=2,*" %%A in ('reg query "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\ISCC.exe" /ve 2^>nul ^| findstr /i "REG_SZ"') do set "ISCC=%%B"
)
if not defined ISCC (
    for %%V in (7 6 8 9) do (
        if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup %%V\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup %%V\ISCC.exe"
        if not defined ISCC if exist "%ProgramFiles%\Inno Setup %%V\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup %%V\ISCC.exe"
    )
)

if not defined ISCC (
    echo.
    echo [ERROR] No se encontro Inno Setup instalado.
    echo Descargalo gratis desde https://jrsoftware.org/isdl.php e instalalo
    echo con las opciones por defecto, luego vuelve a correr este script.
    echo.
    pause
    exit /b 1
)

echo Usando Inno Setup: %ISCC%
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
