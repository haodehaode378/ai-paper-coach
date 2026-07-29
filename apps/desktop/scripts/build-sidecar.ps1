param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$desktopRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$repositoryRoot = (Resolve-Path (Join-Path $desktopRoot "..\..")).Path
$apiRoot = Join-Path $repositoryRoot "services\api"
$tauriRoot = Join-Path $desktopRoot "src-tauri"
$buildRoot = Join-Path $tauriRoot "target\pyinstaller"
$venvRoot = Join-Path $tauriRoot "target\sidecar-build-venv"
$buildPython = Join-Path $venvRoot "Scripts\python.exe"
$targetTriple = (& rustc --print host-tuple).Trim()

if (-not $targetTriple) {
    throw "Unable to determine the Rust target triple."
}

if (-not (Test-Path -LiteralPath $buildPython)) {
    & $Python -m venv $venvRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to create the isolated sidecar build environment."
    }
}

& $buildPython -m pip install --disable-pip-version-check -r (Join-Path $apiRoot "requirements-build.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Unable to install sidecar build dependencies."
}

$binaryRoot = Join-Path $tauriRoot "binaries"
$outputName = "ai-paper-coach-api-$targetTriple"
$outputPath = Join-Path $binaryRoot "$outputName.exe"

New-Item -ItemType Directory -Force -Path $buildRoot, $binaryRoot | Out-Null

& $buildPython -m PyInstaller `
    --clean `
    --noconfirm `
    --onefile `
    --name $outputName `
    --distpath $binaryRoot `
    --workpath (Join-Path $buildRoot "work") `
    --specpath (Join-Path $buildRoot "spec") `
    --paths $apiRoot `
    --add-data "$apiRoot\app\prompts;app\prompts" `
    (Join-Path $apiRoot "desktop_entry.py")

if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $outputPath)) {
    throw "Sidecar build failed: $outputPath"
}

Write-Output $outputPath
