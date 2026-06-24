import sys
from pathlib import Path

BUILD_BAT = r"""@echo off
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
echo     3. Empaqueta todo en dist\ForgeMind.exe
echo     4. Abre la carpeta dist\ al terminar
echo.
echo   Si falla, mandale foto del error.
echo.
echo ------------------------------------------------------------

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
    echo [2/5] Creando entorno virtual .venv ...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo [ERROR] No se pudo crear el venv.
        pause
        exit /b 1
    )
    set "PY=.venv\Scripts\python.exe"
)

REM ----- 3. Instalar dependencias -----
echo [3/5] Instalando dependencias PyQt6 + psutil + PyInstaller ...
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

REM ----- 5. Ejecutar PyInstaller -----
echo [4/5] Empaquetando con PyInstaller (puede tardar 1-3 minutos) ...
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

REM ----- 6. Verificar .exe -----
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
echo.
pause
exit /b 0
"""

BUILD_CLEAN_BAT = r"""@echo off
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
"""


def write_crlf(path: Path, content: str) -> None:
    """Write a .bat file with CRLF line endings, no BOM, ASCII-only."""
    # Normalize line endings to \r\n (CRLF) — required by cmd.exe
    # Replace any \r\n with \n first to avoid double-encoding, then to \r\n
    normalized = content.replace("\r\n", "\n").replace("\n", "\r\n")
    # Write as ASCII (errors='replace' just in case, but content is pure ASCII)
    path.write_bytes(normalized.encode("ascii", errors="replace"))


def main() -> int:
    # Script lives in <project_root>/scripts/write_bats.py
    # .bat files go to <project_root>/ so the user can double-click them
    # from the project root in Explorer.
    root = Path(__file__).resolve().parent.parent
    print(f"Project root: {root}")
    write_crlf(root / "build.bat", BUILD_BAT)
    write_crlf(root / "build_clean.bat", BUILD_CLEAN_BAT)
    # Quick sanity check: print first bytes
    for name in ("build.bat", "build_clean.bat"):
        p = root / name
        head = p.read_bytes()[:20]
        print(f"{name}: {head!r}  size={p.stat().st_size}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
