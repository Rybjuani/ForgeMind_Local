@echo off
REM ============================================================
REM  ForgeMind Local - INICIAR.bat
REM  Doble click para abrir la app de forma amigable.
REM
REM  ASCII PURO (sin acentos) para que cmd.exe no se clave.
REM ============================================================
title ForgeMind Local
cd /d "%~dp0"

set "EXE=dist\ForgeMind.exe"

REM --- Modo rapido: el .exe ya existe ---
if exist "%EXE%" (
    echo.
    echo   Abriendo ForgeMind Local ...
    echo.
    start "" "%EXE%"
    exit /b 0
)

REM --- No hay .exe: explicar y buildear ---
echo.
echo ============================================================
echo   ForgeMind Local
echo ============================================================
echo.
echo   No encontre el ejecutable (dist\ForgeMind.exe).
echo.
echo   Voy a generar la primera vez. Tarda 1-3 minutos la
echo   primera vez (descarga PyQt6 + empaqueta). Las siguientes
echo   veces abre directo en 1 segundo.
echo.
echo   Si preferis no esperar y abrir en modo desarrollo
echo   (requiere Python instalado), responde N abajo.
echo.
set /p CONFIRM=Generar el .exe ahora? [S/N]: 
if /i not "%CONFIRM%"=="S" (
    echo.
    echo   Abriendo en modo desarrollo (python -m app.main) ...
    echo.
    goto run_dev
)

REM ============================================================
REM BUILD INLINE (no llama a build.bat para evitar el pause)
REM ============================================================

REM --- Localizar Python ---
if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
    goto build_have_python
)
where python >nul 2>nul
if %errorlevel%==0 (
    set "PY=python"
    goto build_have_python
)
where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py -3"
    goto build_have_python
)
echo.
echo   [ERROR] No encontre Python instalado.
echo   Instalalo desde https://www.python.org/downloads/windows/
echo   (marca "Add Python to PATH" durante la instalacion)
echo.
echo   Abriendo en modo dev igual (probablemente falle) ...
echo.
goto run_dev

:build_have_python
REM --- Crear venv si no existe ---
if not exist ".venv\Scripts\python.exe" (
    echo   Creando entorno virtual .venv ...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo   [ERROR] No se pudo crear el venv. Modo dev ...
        goto run_dev
    )
    set "PY=.venv\Scripts\python.exe"
)

REM --- Instalar dependencias ---
echo   Instalando dependencias (PyQt6 + psutil + PyInstaller) ...
"%PY%" -m pip install --quiet --disable-pip-version-check -r requirements.txt pyinstaller
if errorlevel 1 (
    echo   [ERROR] Fallo pip install. Modo dev ...
    goto run_dev
)

REM --- Limpiar cache vieja ---
echo   Limpiando cache vieja ...
if exist "app\__pycache__" rmdir /s /q "app\__pycache__" 2>nul
if exist "build" rmdir /s /q "build" 2>nul
if exist "dist\ForgeMind.exe" del /f /q "dist\ForgeMind.exe" 2>nul

REM --- PyInstaller ---
echo   Empaquetando con PyInstaller (1-3 minutos) ...
"%PY%" -m PyInstaller forgemind.spec --noconfirm --clean
if errorlevel 1 (
    echo.
    echo   [ERROR] PyInstaller fallo. Modo dev ...
    echo.
    goto run_dev
)

REM --- Verificar y abrir ---
if exist "%EXE%" (
    echo.
    echo   LISTO. Abriendo ForgeMind Local ...
    echo.
    start "" "%EXE%"
    exit /b 0
)

echo.
echo   [ERROR] El build termino pero no se genero el .exe.
echo   Modo dev ...
echo.

:run_dev
REM ============================================================
REM MODO DEV: python directo (sin .exe)
REM ============================================================
if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
    goto dev_run
)
where python >nul 2>nul
if %errorlevel%==0 (
    set "PY=python"
    goto dev_run
)
where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py -3"
    goto dev_run
)

echo.
echo   [ERROR] No encontre Python instalado.
echo.
echo   Instalalo desde: https://www.python.org/downloads/windows/
echo   (marca "Add Python to PATH" durante la instalacion)
echo.
echo   Despues hace doble click de nuevo en INICIAR.bat
echo.
pause
exit /b 1

:dev_run
echo.
echo   Usando: %PY% -m app.main
echo   (Si ves errores aca, mandanos una captura.)
echo.
"%PY%" -m app.main
if errorlevel 1 (
    echo.
    echo   [ERROR] La app fallo al arrancar. Mensaje arriba.
    echo.
    pause
)
exit /b %errorlevel%
