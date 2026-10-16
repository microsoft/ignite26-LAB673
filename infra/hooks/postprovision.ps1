$ErrorActionPreference = "Stop"
if (-not $env:RESTORE_INDEX_SNAPSHOTS) { $env:RESTORE_INDEX_SNAPSHOTS = "true" }
$repoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Push-Location $repoRoot
try {
    if (-not (Test-Path ".venv")) {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw "Could not create the virtual environment." }
    }
    $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    & $venvPython -m pip install --disable-pip-version-check -r src/notebooks/requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
    & $venvPython infra/setup-env.py
    if ($LASTEXITCODE -ne 0) { throw "Environment setup failed." }
    & $venvPython infra/setup-content-understanding.py
    if ($LASTEXITCODE -ne 0) { throw "Content Understanding setup failed." }
    if ($env:RESTORE_INDEX_SNAPSHOTS -eq "true") {
        & $venvPython infra/create-knowledge.py
        if ($LASTEXITCODE -ne 0) { throw "Snapshot restoration failed." }
    }
    Write-Host "Lab resources and local environment are ready."
} finally {
    Pop-Location
}