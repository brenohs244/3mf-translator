param(
    [string]$Repo = 'brenohs244/3mf-translator',
    [switch]$SkipBuild,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

if (-not $SkipBuild) {
    & (Join-Path $PSScriptRoot 'build.ps1')
}

$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$env:PYTHONPATH = Join-Path $projectRoot 'src'
$version = (& $python -c 'import maker_elegoo; print(maker_elegoo.__version__)').Trim()
$tag = "v$version"

$setupExe = Join-Path $projectRoot "dist\MakerElegoo-Setup-v$version.exe"
$zipFile = Join-Path $projectRoot 'dist\MakerElegoo-Windows-Portable.zip'
$checksums = Join-Path $projectRoot "dist\checksums-v$version.txt"

foreach ($req in @($setupExe, $zipFile, $checksums)) {
    if (-not (Test-Path -LiteralPath $req)) {
        throw "Artefato obrigatório ausente: $req"
    }
}

$notes = "Release $tag (pacote rapido --onedir, instalador Inno Setup e verificacao SHA-256)."
if ($DryRun) {
    Write-Host "[DryRun] gh release create $tag --repo $Repo --title $tag --notes `"$notes`" `"$setupExe`" `"$zipFile`" `"$checksums`""
    exit 0
}

gh release create $tag `
    --repo $Repo `
    --title "Maker -> ELEGOO $tag" `
    --notes $notes `
    $setupExe `
    $zipFile `
    $checksums
if ($LASTEXITCODE -ne 0) {
    throw 'Falha ao publicar Release no GitHub via gh CLI.'
}
Write-Host "Release $tag publicada em https://github.com/$Repo/releases/tag/$tag"
