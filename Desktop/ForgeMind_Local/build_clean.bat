@echo off
REM ============================================================
REM  ForgeMind Local - build_clean.bat
REM  Lo mismo que build.bat pero borrando build/ y dist/ primero.
REM  Usar cuando el build normal da errores raros de cache.
REM ============================================================
title ForgeMind Local - Build LIMPIO .exe
cd /d "%~dp0"

echo.
echo ============================================================
echo   ForgeMind Local - Build LIMPIO (build/ + dist/ borrados)
echo ============================================================
echo.
echo   Este script:
echo     1. BORRA build\ y dist\ (cuidado: pierde cualquier .exe viejo)
echo     2. Busca Python (o crea venv si hace falta)
echo     3. Instala PyQt6 + psutil + PyInstaller
echo     4. Empaqueta todo en dist\ForgeMind.exe
echo     5. Abre dist\ al terminar
echo.
echo ------------------------------------------------------------

REM ----- 0. Borrar build/ y dist/ -----
if exist "build" (
    echo [0/5] Borrando build\ ...
    rmdir /s /q "build"
)
if exist "dist" (
    echo [0/5] Borrando dist\ ...
    rmdir /s /q "dist"
)

REM ----- 1. Localizar Python -----
if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
    echo [1/5] Usando venv existente: %PY%
    goto have_python
)

where python >nul 2>nul
if %errorlevel%==0 (
    set "PY=python"
    echo [1/5] Python encontrado en PATH: %PY%
    goto have_python
)

where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py -3"
    echo [1/5] Python encontrado via launcher: %PY%
    goto have_python
)

echo.
echo [ERROR] No encontre Python instalado.
echo   Instalalo desde: https://www.python.org/downloads/windows/
echo   Marca "Add Python to PATH" durante la instalacion.
echo.
pause
exit /b 1

:have_python

REM ----- 2. Crear venv si no existe -----
if not exist ".venv\Scripts\python.exe" (
    echo [2/5] Creando entorno virtual .venv ...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo [ERROR] No se pudo crear el venv.
        pause
        exit /b 1
    )
    set "PY=.venv\Scripts\python.exe"
)

REM ----- 3. Reinstalar dependencias -----
echo [3/5] Reinstalando dependencias ...
"%PY%" -m pip install --upgrade --quiet --disable-pip-version-check pip >nul 2>nul
"%PY%" -m pip install --quiet --disable-pip-version-check --force-reinstall -r requirements.txt pyinstaller
if errorlevel 1 (
    echo [ERROR] Fallo pip install. Revisar mensaje arriba.
    pause
    exit /b 1
)

REM ----- 4. Ejecutar PyInstaller -----
echo [4/5] Empaquetando con PyInstaller (puede tardar 2-4 minutos) ...
echo       No cerrar esta ventana.
echo.
"%PY%" -m PyInstaller forgemind.spec --noconfirm --clean
if errorlevel 1 (
    echo.
    echo [ERROR] PyInstaller fallo. Revisar mensaje arriba.
    pause
    exit /b 1
)

REM ----- 5. Verificar .exe -----
if not exist "dist\ForgeMind.exe" (
    echo [ERROR] Build OK pero no se genero dist\ForgeMind.exe
    pause
    exit /b 1
)

for %%I in ("dist\ForgeMind.exe") do set EXE_SIZE_MB=%%~zI
set /a EXE_SIZE_MB=%EXE_SIZE_MB% / 1048576

echo.
echo ============================================================
echo   LISTO  -  dist\ForgeMind.exe  (%EXE_SIZE_MB% MB)
echo ============================================================
echo.
echo   Cerrando .exe viejo si estaba abierto...
taskkill /f /im ForgeMind.exe >nul 2>nul
echo   Abriendo carpeta dist\ en Explorer...
explorer "dist"

echo.
echo   Doble click en ForgeMind.exe para abrir la app.
echo.
pause
exit /b 0
