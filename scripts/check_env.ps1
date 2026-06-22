<#
.SYNOPSIS
    Chequea el entorno para ForgeMind Local (sin arrancar la UI).

.DESCRIPTION
    Reporta:
      - Version de Python
      - Presencia de PyQt6, psutil, llama_cpp (binding opcional)
      - llama-cli / llama-server en PATH
      - RAM total / disponible
      - GPUs detectadas y soporte Vulkan (heuristica)

.EXAMPLE
    .\scripts\check_env.ps1
#>

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir '..')
Set-Location $ProjectRoot

$PythonExe = 'python'
$VenvDir = Join-Path $ProjectRoot '.venv'
if (Test-Path $VenvDir) {
    $VenvPy = Join-Path $VenvDir 'Scripts\python.exe'
    if (Test-Path $VenvPy) { $PythonExe = $VenvPy }
}

function Write-Section($title) {
    Write-Host ""
    Write-Host ("== " + $title + " ==") -ForegroundColor Cyan
}

Write-Section "Python"
& $PythonExe --version
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] No se pudo ejecutar python" -ForegroundColor Red
    exit 1
}

Write-Section "Modulos Python"
foreach ($m in 'PyQt6', 'psutil', 'llama_cpp') {
    $ok = & $PythonExe -c "import $m; print('OK')" 2>$null
    if ($ok -and $ok.Trim() -eq 'OK') {
        $ver = & $PythonExe -c "import $m; print(getattr($m, '__version__', '?'))" 2>$null
        Write-Host ("  {0,-10} OK ({1})" -f $m, $ver.Trim())
    } else {
        Write-Host ("  {0,-10} NO instalado" -f $m) -ForegroundColor Yellow
    }
}

Write-Section "llama.cpp en PATH"
foreach ($exe in 'llama-cli', 'llama-server', 'llama-cli.exe', 'llama-server.exe') {
    $found = Get-Command $exe -ErrorAction SilentlyContinue
    if ($found) {
        Write-Host ("  {0,-18} -> {1}" -f $exe, $found.Source)
    }
}

Write-Section "Resumen de hardware / GPU / Vulkan"
& $PythonExe -m app.main --check
$Exit = $LASTEXITCODE
exit $Exit