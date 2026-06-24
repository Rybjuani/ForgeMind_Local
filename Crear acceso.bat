@echo off
REM ============================================================
REM  ForgeMind Local - Crear acceso en el escritorio
REM  Doble click para tener ForgeMind como un icono mas en
REM  el escritorio de Windows.
REM ============================================================
title Crear acceso - ForgeMind Local
cd /d "%~dp0"

echo.
echo ============================================================
echo   ForgeMind Local - Crear acceso en el escritorio
echo ============================================================
echo.

REM --- Detectar ruta del escritorio ---
set "DESKTOP=%USERPROFILE%\Desktop"
if not exist "%DESKTOP%" set "DESKTOP=%USERPROFILE%\Escritorio"
if not exist "%DESKTOP%" (
    echo   [ERROR] No se encontro la carpeta del escritorio.
    pause
    exit /b 1
)

set "TARGET=%~dp0INICIAR.bat"
set "SHORTCUT=%DESKTOP%\ForgeMind Local.lnk"
set "ICON=%~dp0app\assets\fonts\Newsreader-Variable.ttf"

if not exist "%TARGET%" (
    echo   [ERROR] No se encontro INICIAR.bat en:
    echo   %TARGET%
    pause
    exit /b 1
)

REM --- Crear el .lnk via PowerShell ---
echo   Creando acceso: %SHORTCUT%
echo.
powershell -NoProfile -Command ^
    "$ws = New-Object -ComObject WScript.Shell; " ^
    "$sc = $ws.CreateShortcut('%SHORTCUT%'); " ^
    "$sc.TargetPath = '%TARGET%'; " ^
    "$sc.WorkingDirectory = '%~dp0'; " ^
    "$sc.IconLocation = '%SystemRoot%\System32\shell32.dll,13'; " ^
    "$sc.Description = 'ForgeMind Local - LLM lab'; " ^
    "$sc.WindowStyle = 7; " ^
    "$sc.Save()"

if errorlevel 1 (
    echo.
    echo   [ERROR] No se pudo crear el acceso.
    echo   Probablemente falte PowerShell o permisos.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   LISTO
echo ============================================================
echo.
echo   Se creo el acceso "ForgeMind Local" en tu escritorio.
echo.
echo   Doble click en el icono para abrir la app.
echo.
echo   Si todavia no tenes el .exe generado, el acceso lo
echo   va a buildear automaticamente la primera vez.
echo.
pause
exit /b 0
