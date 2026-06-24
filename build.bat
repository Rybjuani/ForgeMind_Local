@echo off
REM ============================================================
REM  ForgeMind Local - build.bat
REM  Doble click para generar dist\ForgeMind.exe actualizado.
REM ============================================================
title ForgeMind Local - Build .exe
cd /d "%~dp0"

echo.
echo ============================================================
echo   ForgeMind Local - Generador de .exe
echo ============================================================
echo.
echo   Este script:
echo     1. Busca Python (o crea un venv si hace falta)
echo     2. Instala PyQt6 + psutil + PyInstaller
echo     3. LIMPIA cache vieja (__pycache__, build/, dist/ForgeMind.exe)
echo     4. Empaqueta todo en dist\ForgeMind.exe
echo     5. Abre la carpeta dist\ al terminar
echo.
echo   Si falla, mandale foto del error.
echo.
echo ------------------------------------------------------------

REM ----- 1. Localizar Python -----
if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
    echo [1/6] Usando venv existente: %PY%
    goto have_python
)

where python >nul 2>nul
if %errorlevel%==0 (
    set "PY=python"
    echo [1/6] Python encontrado en PATH: %PY%
    goto have_python
)

where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py -3"
    echo [1/6] Python encontrado via launcher: %PY%
    goto have_python
)

echo.
echo [ERROR] No encontre Python instalado.
echo.
echo   Instalalo desde: https://www.python.org/downloads/windows/
echo   Durante la instalacion marca la casilla
echo   "Add Python to PATH" (es importante).
echo.
echo   Despues volve a hacer doble click en este .bat.
echo.
pause
exit /b 1

:have_python

REM ----- 2. Crear venv si no existe -----
if not exist ".venv\Scripts\python.exe" (
    echo [2/6] Creando entorno virtual .venv ...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo [ERROR] No se pudo crear el venv.
        pause
        exit /b 1
    )
    set "PY=.venv\Scripts\python.exe"
)

REM ----- 3. Instalar dependencias -----
echo [3/6] Instalando dependencias PyQt6 + psutil + PyInstaller ...
"%PY%" -m pip install --upgrade --quiet --disable-pip-version-check pip >nul 2>nul
"%PY%" -m pip install --quiet --disable-pip-version-check -r requirements.txt pyinstaller
if errorlevel 1 (
    echo [ERROR] Fallo pip install. Revisar mensaje arriba.
    pause
    exit /b 1
)

REM ----- 4. Verificar spec -----
if not exist "forgemind.spec" (
    echo [ERROR] No se encuentra forgemind.spec en la carpeta del proyecto.
    pause
    exit /b 1
)

REM ----- 5. LIMPIAR cache vieja (CRITICO para que no bundlee codigo viejo) -----
echo [4/6] Limpiando cache vieja (__pycache__, build/, dist/ForgeMind.exe) ...
REM Borrar __pycache__ recursivo (Python 3 cache)
if exist "app\__pycache__" rmdir /s /q "app\__pycache__" 2>nul
if exist "tests\__pycache__" rmdir /s /q "tests\__pycache__" 2>nul
REM Borrar build/ (cache de PyInstaller)
if exist "build" rmdir /s /q "build" 2>nul
REM Borrar .exe viejo para que no quede corriendo si el build falla
if exist "dist\ForgeMind.exe" del /f /q "dist\ForgeMind.exe" 2>nul

REM ----- 6. Ejecutar PyInstaller -----
echo [5/6] Empaquetando con PyInstaller (puede tardar 1-3 minutos) ...
echo       No cerrar esta ventana.
echo.
"%PY%" -m PyInstaller forgemind.spec --noconfirm --clean
if errorlevel 1 (
    echo.
    echo [ERROR] PyInstaller fallo. Revisar mensaje arriba.
    echo         Si el error habla de "UPX", proba build_clean.bat
    echo         o instala UPX: https://upx.github.io/
    echo.
    pause
    exit /b 1
)

REM ----- 7. Verificar .exe -----
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
echo   Cerrando el .exe viejo si lo tenias abierto...
taskkill /f /im ForgeMind.exe >nul 2>nul
echo   Abriendo carpeta dist\ en Explorer...
explorer "dist"

echo.
echo   Doble click en ForgeMind.exe para abrir la app.
echo   O usa INICIAR.bat para abrir directo.
echo.
pause
exit /b 0
