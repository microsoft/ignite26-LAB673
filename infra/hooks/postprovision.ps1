$ErrorActionPreference = "Stop"
if (-not $env:RESTORE_INDEX_SNAPSHOTS) { $env:RESTORE_INDEX_SNAPSHOTS = "true" }
$repoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Push-Location $repoRoot
try {
    python (Join-Path $repoRoot "infra\setup-venv.py")
    if ($LASTEXITCODE -ne 0) { throw "Virtual environment setup failed." }
    $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
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