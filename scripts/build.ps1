param(
    [switch]$SkipZip
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Crie .venv e instale PyInstaller: python -m venv .venv; .venv\Scripts\python -m pip install pyinstaller'
}

$pyInstallerArgs = @('--noconfirm', '--clean', '--onefile', '--windowed', '--name', 'MakerElegoo',
    '--paths', (Join-Path $projectRoot 'src'), '--distpath', (Join-Path $projectRoot 'dist'),
    '--workpath', (Join-Path $projectRoot 'build\pyinstaller'),
    '--specpath', (Join-Path $projectRoot 'build\pyinstaller'),
    '--runtime-hook', (Join-Path $projectRoot 'scripts\pyinstaller_tk_runtime.py'))

# Python 3.15 ships Tcl/Tk 9 as ZIP archives. PyInstaller does not collect their
# contents automatically, so extract the libraries into the bundle explicitly.
$pythonRoot = (& $python -c 'import sys; print(sys.base_prefix)').Trim()
$tclRoot = Join-Path $pythonRoot 'tcl'
$tclArchive = Get-ChildItem -LiteralPath $tclRoot -Filter 'libtcl*.zip' -File -ErrorAction SilentlyContinue | Select-Object -First 1
$tkArchive = Get-ChildItem -LiteralPath $tclRoot -Filter 'libtk*.zip' -File -ErrorAction SilentlyContinue | Select-Object -First 1
if ($tclArchive -and $tkArchive) {
    $libraryRoot = Join-Path $projectRoot 'build\tk_libraries'
    New-Item -ItemType Directory -Path $libraryRoot -Force | Out-Null
    Expand-Archive -LiteralPath $tclArchive.FullName -DestinationPath $libraryRoot -Force
    Expand-Archive -LiteralPath $tkArchive.FullName -DestinationPath $libraryRoot -Force
    $pyInstallerArgs += @('--add-data', "$(Join-Path $libraryRoot 'tcl_library');tcl_library")
    $pyInstallerArgs += @('--add-data', "$(Join-Path $libraryRoot 'tk_library');tk_library")
}

& $python -m PyInstaller @pyInstallerArgs (Join-Path $projectRoot 'launcher.py')
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller falhou.' }

$exe = Join-Path $projectRoot 'dist\MakerElegoo.exe'
if (-not (Test-Path -LiteralPath $exe)) { throw 'Executável não foi criado.' }
if (-not $SkipZip) {
    $package = Join-Path $projectRoot 'build\package'
    New-Item -ItemType Directory -Path $package -Force | Out-Null
    Copy-Item -LiteralPath $exe -Destination (Join-Path $package 'MakerElegoo.exe') -Force
    Copy-Item -LiteralPath (Join-Path $projectRoot 'scripts\install.ps1') -Destination (Join-Path $package 'install.ps1') -Force
    Copy-Item -LiteralPath (Join-Path $projectRoot 'scripts\README-DISTRIBUTION.txt') -Destination (Join-Path $package 'LEIA-ME.txt') -Force
    $zip = Join-Path $projectRoot 'dist\MakerElegoo-Windows.zip'
    if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
    Compress-Archive -Path (Join-Path $package '*') -DestinationPath $zip
    Write-Host "Pacote criado: $zip"
}
Write-Host "Executável criado: $exe"
