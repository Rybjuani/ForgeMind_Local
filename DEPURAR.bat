@echo off
REM ============================================================
REM  ForgeMind Local - DEPURAR.bat
REM  Abre la app mostrando la consola para ver errores.
REM
REM  Usar cuando:
REM    - El .exe se cierra al instante sin mostrar nada
REM    - La UI no aparece
REM    - Queres ver los logs en tiempo real
REM
REM  La ventana negra NO se cierra sola: podes leer el error
REM  completo, copiarlo con click derecho, y mandarlo.
REM ============================================================
title ForgeMind Local - Depuracion
cd /d "%~dp0"

echo.
echo ============================================================
echo   ForgeMind Local - MODO DEPURACION
echo ============================================================
echo.
echo   Esta ventana va a mostrar los errores de la app.
echo   NO la cierres hasta que termines de leer.
echo.
echo ------------------------------------------------------------

REM --- Prioridad 1: .exe (si existe) ---
if exist "dist\ForgeMind.exe" (
    echo   Abriendo dist\ForgeMind.exe ...
    echo.
    "dist\ForgeMind.exe"
    echo.
    echo ============================================================
    echo   La app se cerro. Exit code: %errorlevel%
    echo ============================================================
    echo.
    echo   Si hay un error arriba (traceback), copialo con
    echo   click derecho -^> Marcar -^> seleccionar -^> Enter.
    echo.
    pause
    exit /b %errorlevel%
)

REM --- No hay .exe: modo dev con python ---
echo   No hay dist\ForgeMind.exe. Probando modo dev (python) ...
echo.

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

echo   [ERROR] No encontre Python ni .exe.
echo   Corre INICIAR.bat primero para generar el .exe.
pause
exit /b 1

:dev_run
echo.
echo   Usando: %PY% -m app.main
echo.
"%PY%" -m app.main
echo.
echo ============================================================
echo   La app se cerro. Exit code: %errorlevel%
echo ============================================================
echo.
echo   Si hay un error arriba (traceback), copialo.
echo.
pause
exit /b %errorlevel%
