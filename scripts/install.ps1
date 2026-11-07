$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot 'MakerElegoo.exe'
if (-not (Test-Path -LiteralPath $source)) { throw 'MakerElegoo.exe não está ao lado deste instalador.' }
$targetDir = Join-Path $env:LOCALAPPDATA 'Programs\MakerElegoo'
New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
$target = Join-Path $targetDir 'MakerElegoo.exe'
Copy-Item -LiteralPath $source -Destination $target -Force
$menuDir = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
$shortcut = Join-Path $menuDir 'Maker ELEGOO.lnk'
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($shortcut)
$link.TargetPath = $target
$link.WorkingDirectory = $targetDir
$link.Description = 'Conversor MakerWorld para ELEGOO Slicer'
$link.Save()
Write-Host "Instalado em $target"
