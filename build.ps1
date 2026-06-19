# Build a portable, windowed TokenStep.exe with PyInstaller and package it for sharing.
# Output:
#   dist\TokenStep.exe           single-file, no console, system-tray app
#   dist\TokenStep-<ver>-win64.zip  shareable portable package (exe + README)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# Read version from the package.
$version = (python -c "import tokenstep,sys; sys.stdout.write(tokenstep.__version__)")
if (-not $version) { Write-Error "Could not read version"; exit 1 }
Write-Host "Building TokenStep $version ..."

Write-Host "Installing build dependencies..."
python -m pip install --quiet --upgrade pyinstaller pystray Pillow tzdata
if (-not $?) { Write-Error "pip install failed"; exit 1 }

Write-Host "Generating application icon (app.ico) from the v0.1.5 design..."
python -c "from tokenstep import appicon; appicon.save_ico('app.ico')"
if (-not $?) { Write-Error "icon generation failed"; exit 1 }

Write-Host "Running PyInstaller..."
python -m PyInstaller --noconfirm --clean --onefile --windowed `
  --name TokenStep `
  --icon app.ico `
  --collect-submodules tokenstep `
  --collect-submodules pystray `
  --hidden-import pystray._win32 `
  tokenstep_app.py
if (-not $?) { Write-Error "PyInstaller failed"; exit 1 }

$exe = Join-Path $root "dist\TokenStep.exe"
if (-not (Test-Path $exe)) { Write-Error "Build finished but $exe is missing"; exit 1 }
$sizeMb = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Write-Host "Built $exe ($sizeMb MB)"

# Package a shareable portable zip (exe + README).
Write-Host "Packaging portable zip..."
$stage = Join-Path $root "dist\TokenStep-$version-win64"
if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
New-Item -ItemType Directory -Path $stage | Out-Null
Copy-Item $exe (Join-Path $stage "TokenStep.exe")
Copy-Item (Join-Path $root "README.md") (Join-Path $stage "README.md")

$zip = Join-Path $root "dist\TokenStep-$version-win64.zip"
if (Test-Path $zip) { Remove-Item -Force $zip }
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip
$zipMb = [math]::Round((Get-Item $zip).Length / 1MB, 1)
Write-Host "Packaged $zip ($zipMb MB)"
Write-Host "Done. Share dist\TokenStep-$version-win64.zip with the community."
