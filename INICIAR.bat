@echo off
REM ============================================================
REM  ForgeMind Local - INICIAR.bat
REM  Doble click para abrir la app de forma amigable.
REM
REM  Que hace:
REM    1. Si existe dist\ForgeMind.exe  ->  lo abre directo
REM    2. Si NO existe                  ->  buildea (build.bat) y abre
REM    3. Si falla Python o PyInstaller ->  abre en modo python (dev)
REM
REM  No requiere saber Python ni linea de comandos.
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
echo   (requiere Python instalado), respondé N abajo.
echo.
set /p CONFIRM=Generar el .exe ahora? [S/N]: 
if /i not "%CONFIRM%"=="S" (
    echo.
    echo   Abriendo en modo desarrollo (python -m app.main) ...
    echo.
    goto run_dev
)

echo.
echo   Lanzando build.bat ...
echo.
call "%~dp0build.bat"
if errorlevel 1 (
    echo.
    echo   [ERROR] El build fallo. Probando modo dev ...
    echo.
    goto run_dev
)

REM --- Despues del build, abrir el .exe ---
if exist "%EXE%" (
    echo.
    echo   Abriendo ForgeMind Local ...
    echo.
    start "" "%EXE%"
    exit /b 0
)

echo.
echo   [ERROR] El build termino pero no se genero el .exe.
echo   Probando modo dev ...
echo.

:run_dev
REM --- Modo dev: python directo ---
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
echo.
"%PY%" -m app.main
if errorlevel 1 (
    echo.
    echo   [ERROR] La app fallo al arrancar. Mensaje arriba.
    echo.
    pause
)
exit /b %errorlevel%
