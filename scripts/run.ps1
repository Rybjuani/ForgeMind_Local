<#
.SYNOPSIS
    Lanza ForgeMind Local (UI PyQt6).

.DESCRIPTION
    - Activa el venv local si existe (.venv).
    - Verifica Python 3.10+ y PyQt6.
    - Lanza: python -m app.main
    - Flags soportados: -Check, -Mock

.EXAMPLE
    .\scripts\run.ps1
    .\scripts\run.ps1 -Check
    .\scripts\run.ps1 -Mock
#>

[CmdletBinding()]
param(
    [switch]$Check,
    [switch]$Mock,
    [switch]$NoVenv
)

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir '..')
Set-Location $ProjectRoot

function Write-Step($msg) {
    Write-Host "[run] $msg" -ForegroundColor Cyan
}

function Write-Err($msg) {
    Write-Host "[run][ERROR] $msg" -ForegroundColor Red
}

# --- venv ---
$VenvDir = Join-Path $ProjectRoot '.venv'
$UseVenv = -not $NoVenv
$PythonExe = 'python'

if ($UseVenv -and (Test-Path $VenvDir)) {
    $VenvPy = Join-Path $VenvDir 'Scripts\python.exe'
    if (Test-Path $VenvPy) {
        $PythonExe = $VenvPy
        Write-Step "Usando venv: $VenvPy"
    } else {
        Write-Step "Venv existe pero falta Scripts\python.exe; usando python del sistema."
    }
} elseif ($UseVenv) {
    Write-Step "No hay .venv local. Usando python del sistema (recomendado crear uno)."
}

# --- version check ---
$PyVerOutput = & $PythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Err "No se pudo ejecutar '$PythonExe'. Verifica que Python este instalado y en PATH."
    exit 1
}
$Major = ($PyVerOutput -split '\.')[0]
$Minor = ($PyVerOutput -split '\.')[1]
if ([int]$Major -lt 3 -or ([int]$Major -eq 3 -and [int]$Minor -lt 10)) {
    Write-Err "Se necesita Python 3.10+. Detectado: $PyVerOutput"
    exit 1
}
Write-Step "Python $PyVerOutput OK"

# --- dependencias (chequeo liviano) ---
$Missing = & $PythonExe -c "import sys; mods=['PyQt6','psutil']; miss=[m for m in mods if not __import__(m)]; print(' '.join(miss))" 2>$null
if ($Missing -and $Missing.Trim()) {
    Write-Err "Faltan modulos: $Missing"
    Write-Host "        Instalalos con: $PythonExe -m pip install -r requirements.txt" -ForegroundColor Yellow
    exit 1
}
Write-Step "Dependencias base OK (PyQt6, psutil)"

# --- armado de comando ---
$Args = @('-m', 'app.main')
if ($Check) { $Args += '--check' }
if ($Mock)  { $Args += '--mock' }

Write-Step "Ejecutando: $PythonExe $($Args -join ' ')"
& $PythonExe @Args
$ExitCode = $LASTEXITCODE
if ($ExitCode -ne 0 -and $ExitCode -ne 130) {
    Write-Err "La app termino con codigo $ExitCode"
}
exit $ExitCode