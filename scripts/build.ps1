param(
    [switch]$SkipZip,
    [switch]$SkipInstaller,
    [switch]$OneFile
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Crie .venv e instale PyInstaller: python -m venv .venv; .venv\Scripts\python -m pip install pyinstaller'
}

$env:PYTHONPATH = Join-Path $projectRoot 'src'
$version = (& $python -c 'import maker_elegoo; print(maker_elegoo.__version__)').Trim()
if (-not $version) { throw 'Não foi possível ler __version__ de maker_elegoo.' }

$commonArgs = @(
    '--noconfirm', '--clean', '--windowed', '--name', 'MakerElegoo',
    '--paths', (Join-Path $projectRoot 'src'),
    '--distpath', (Join-Path $projectRoot 'dist'),
    '--workpath', (Join-Path $projectRoot 'build\pyinstaller'),
    '--specpath', (Join-Path $projectRoot 'build\pyinstaller'),
    '--runtime-hook', (Join-Path $projectRoot 'scripts\pyinstaller_tk_runtime.py')
)

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
    $commonArgs += @('--add-data', "$(Join-Path $libraryRoot 'tcl_library');tcl_library")
    $commonArgs += @('--add-data', "$(Join-Path $libraryRoot 'tk_library');tk_library")
}

# Build rápido --onedir (sem descompactação em %TEMP% ao abrir)
$onDirDist = Join-Path $projectRoot 'dist\MakerElegoo'
if (Test-Path -LiteralPath $onDirDist) {
    Remove-Item -LiteralPath $onDirDist -Recurse -Force
}
& $python -m PyInstaller --onedir @commonArgs (Join-Path $projectRoot 'launcher.py')
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller (--onedir) falhou.' }

$exeDirEntry = Join-Path $onDirDist 'MakerElegoo.exe'
if (-not (Test-Path -LiteralPath $exeDirEntry)) { throw "Executável não foi criado em $exeDirEntry" }
Write-Host "Bundle rápido (--onedir) criado: $onDirDist"

$artifacts = New-Object System.Collections.Generic.List[string]

if ($OneFile) {
    & $python -m PyInstaller --onefile @commonArgs (Join-Path $projectRoot 'launcher.py')
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller (--onefile) falhou.' }
    $oneFileExe = Join-Path $projectRoot 'dist\MakerElegoo.exe'
    if (Test-Path -LiteralPath $oneFileExe) { $artifacts.Add($oneFileExe) }
}

if (-not $SkipZip) {
    $package = Join-Path $projectRoot 'build\package'
    if (Test-Path -LiteralPath $package) { Remove-Item -LiteralPath $package -Recurse -Force }
    New-Item -ItemType Directory -Path $package -Force | Out-Null
    Copy-Item -LiteralPath $onDirDist -Destination (Join-Path $package 'MakerElegoo') -Recurse -Force
    Copy-Item -LiteralPath (Join-Path $projectRoot 'scripts\install.ps1') -Destination (Join-Path $package 'install.ps1') -Force
    Copy-Item -LiteralPath (Join-Path $projectRoot 'scripts\README-DISTRIBUTION.txt') -Destination (Join-Path $package 'LEIA-ME.txt') -Force
    $zip = Join-Path $projectRoot 'dist\MakerElegoo-Windows-Portable.zip'
    if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
    Compress-Archive -Path (Join-Path $package '*') -DestinationPath $zip
    $artifacts.Add($zip)
    Write-Host "Pacote portátil criado: $zip"
}

if (-not $SkipInstaller) {
    $isccCandidates = @(
        (Get-Command iscc -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
        (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
        (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe')
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
    $iscc = $isccCandidates | Select-Object -First 1
    if (-not $iscc) {
        throw 'Inno Setup 6 (ISCC.exe) não encontrado. Instale com: winget install JRSoftware.InnoSetup'
    }
    $issPath = Join-Path $projectRoot 'scripts\installer.iss'
    & $iscc "/DAppVersion=$version" "/DSourceDir=$onDirDist" "/DOutputDir=$(Join-Path $projectRoot 'dist')" $issPath
    if ($LASTEXITCODE -ne 0) { throw 'Inno Setup (ISCC.exe) falhou ao compilar o instalador.' }
    $setupExe = Join-Path $projectRoot "dist\MakerElegoo-Setup-v$version.exe"
    if (-not (Test-Path -LiteralPath $setupExe)) { throw "Instalador esperado não encontrado: $setupExe" }
    $artifacts.Add($setupExe)
    Write-Host "Instalador criado: $setupExe"
}

if ($artifacts.Count -gt 0) {
    $checksumFile = Join-Path $projectRoot "dist\checksums-v$version.txt"
    $lines = foreach ($item in $artifacts) {
        $hash = (Get-FileHash -LiteralPath $item -Algorithm SHA256).Hash.ToLowerInvariant()
        $name = [System.IO.Path]::GetFileName($item)
        "$hash  $name"
    }
    [System.IO.File]::WriteAllLines($checksumFile, $lines, [System.Text.UTF8Encoding]::new($false))
    Write-Host "Checksums SHA-256 gerados: $checksumFile"
}
