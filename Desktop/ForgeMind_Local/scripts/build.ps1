<#
.SYNOPSIS
    Empaqueta ForgeMind Local en un .exe standalone con PyInstaller.

.DESCRIPTION
    - Activa el venv local si existe.
    - Limpia build/ y dist/ previos si se pasa -Clean.
    - Ejecuta: pyinstaller forgemind.spec --noconfirm
    - Imprime tamano del .exe resultante.
    - Exit code != 0 si PyInstaller fallo o no se genero el .exe.

.EXAMPLE
    .\scripts\build.ps1
    .\scripts\build.ps1 -Clean
    .\scripts\build.ps1 -NoUpx
#>

[CmdletBinding()]
param(
    [switch]$Clean,
    [switch]$NoUpx
)

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir '..')
Set-Location $ProjectRoot

function Write-Step($msg) {
    Write-Host "[build] $msg" -ForegroundColor Cyan
}

function Write-Err($msg) {
    Write-Host "[build][ERROR] $msg" -ForegroundColor Red
}

# --- venv ---
$VenvDir = Join-Path $ProjectRoot '.venv'
$PythonExe = 'python'
if (Test-Path $VenvDir) {
    $VenvPy = Join-Path $VenvDir 'Scripts\python.exe'
    if (Test-Path $VenvPy) {
        $PythonExe = $VenvPy
        Write-Step "Usando venv: $VenvPy"
    }
}

# --- verificar PyInstaller ---
$HasPI = & $PythonExe -c "import PyInstaller; print(PyInstaller.__version__)" 2>$null
if (-not $HasPI) {
    Write-Err "PyInstaller no esta instalado."
    Write-Host "        Instalalo con: $PythonExe -m pip install pyinstaller" -ForegroundColor Yellow
    exit 1
}
Write-Step "PyInstaller $HasPI OK"

# --- limpiar si se pidio ---
if ($Clean) {
    foreach ($d in 'build', 'dist') {
        $full = Join-Path $ProjectRoot $d
        if (Test-Path $full) {
            Write-Step "Limpiando $d/"
            Remove-Item -Recurse -Force $full
        }
    }
}

# --- verificar spec existe ---
$Spec = Join-Path $ProjectRoot 'forgemind.spec'
if (-not (Test-Path $Spec)) {
    Write-Err "No se encuentra forgemind.spec en el project root."
    exit 1
}

# --- ejecutar PyInstaller ---
# OJO: --noupx NO se puede combinar con un .spec file (PyInstaller lo rechaza).
# Si -NoUpx esta activo, parchamos el spec en runtime.
$Spec = Join-Path $ProjectRoot 'forgemind.spec'
if ($NoUpx) {
    Write-Step "Aplicando upx=False al spec (modo -NoUpx)"
    (Get-Content $Spec -Raw) -replace 'upx=True', 'upx=False' | Set-Content $Spec -Encoding UTF8
}

$Args = @('-m', 'PyInstaller', $Spec, '--noconfirm', '--clean')
# NOTA: NO pasamos --noupx aca porque PyInstaller rechaza combinarlo con un spec.

Write-Step "Ejecutando: $PythonExe $($Args -join ' ')"
& $PythonExe @Args
$ExitCode = $LASTEXITCODE
if ($ExitCode -ne 0) {
    Write-Err "PyInstaller fallo (exit $ExitCode). Revisa el log arriba."
    exit $ExitCode
}

# --- verificar output ---
$Exe = Join-Path $ProjectRoot 'dist\ForgeMind.exe'
if (-not (Test-Path $Exe)) {
    Write-Err "Build OK pero no se genero dist\ForgeMind.exe"
    exit 1
}

$Size = (Get-Item $Exe).Length / 1MB
Write-Host ""
Write-Host "OK  $Exe  ($([math]::Round($Size, 1)) MB)" -ForegroundColor Green
exit 0