param(
    [switch]$RestoreSnapshots
)

$ErrorActionPreference = "Stop"
if (-not $env:RESTORE_INDEX_SNAPSHOTS) { $env:RESTORE_INDEX_SNAPSHOTS = "true" }
$repoRoot = Split-Path $PSScriptRoot -Parent
Push-Location $repoRoot
try {
    if (-not (Test-Path ".venv")) {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw "Could not create the virtual environment." }
    }
    $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    & $venvPython -m pip install -r (Join-Path $repoRoot "src\notebooks\requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
    if ($RestoreSnapshots) { $env:RESTORE_INDEX_SNAPSHOTS = "true" }
    & $venvPython (Join-Path $PSScriptRoot "setup-env.py") --credential cli
    if ($LASTEXITCODE -ne 0) { throw "Environment setup failed." }
    & $venvPython (Join-Path $PSScriptRoot "setup-content-understanding.py")
    if ($LASTEXITCODE -ne 0) { throw "Content Understanding setup failed." }
    if ($env:RESTORE_INDEX_SNAPSHOTS -eq "true") {
        & $venvPython (Join-Path $PSScriptRoot "create-knowledge.py")
        if ($LASTEXITCODE -ne 0) { throw "Snapshot restoration failed." }
    }
    Write-Output "Lab resources and local environment are ready."
} finally {
    Pop-Location
}