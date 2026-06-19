# Launch TokenStep into the Windows system tray (no console window).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { Write-Error "Python not found on PATH."; exit 1 }

$pythonw = Join-Path (Split-Path $python) "pythonw.exe"
if (-not (Test-Path $pythonw)) { $pythonw = $python }

$app = Join-Path $root "tokenstep_app.py"
Start-Process -FilePath $pythonw -ArgumentList "`"$app`""
Write-Host "TokenStep launched to the system tray."
