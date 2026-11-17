$ErrorActionPreference = 'Stop'
$bundleDir = Join-Path $PSScriptRoot 'MakerElegoo'
$singleExe = Join-Path $PSScriptRoot 'MakerElegoo.exe'
$targetDir = Join-Path $env:LOCALAPPDATA 'Programs\MakerElegoo'
New-Item -ItemType Directory -Path $targetDir -Force | Out-Null

if (Test-Path -LiteralPath $bundleDir) {
    Copy-Item -Path (Join-Path $bundleDir '*') -Destination $targetDir -Recurse -Force
} elseif (Test-Path -LiteralPath $singleExe) {
    Copy-Item -LiteralPath $singleExe -Destination (Join-Path $targetDir 'MakerElegoo.exe') -Force
} else {
    throw 'Pasta MakerElegoo ou MakerElegoo.exe não encontrado ao lado deste instalador.'
}

$target = Join-Path $targetDir 'MakerElegoo.exe'
$menuDir = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
$shortcut = Join-Path $menuDir 'Maker ELEGOO.lnk'
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($shortcut)
$link.TargetPath = $target
$link.WorkingDirectory = $targetDir
$link.Description = 'Conversor MakerWorld para ELEGOO Slicer'
$link.Save()
Write-Host "Instalado em $target"
