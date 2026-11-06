param(
    [Parameter(Mandatory=$true)][string]$SearchAdminKey,
    [Parameter(Mandatory=$true)][string]$OpenAIKey,
    [switch]$RestoreSnapshots
)

$ErrorActionPreference = "Stop"
if (-not $env:RESTORE_INDEX_SNAPSHOTS) { $env:RESTORE_INDEX_SNAPSHOTS = "true" }
if ($RestoreSnapshots) { $env:RESTORE_INDEX_SNAPSHOTS = "true" }
$repoRoot = Split-Path $PSScriptRoot -Parent
$envContent = @"
AZURE_SEARCH_SERVICE_ENDPOINT=$env:AZURE_SEARCH_SERVICE_ENDPOINT
AZURE_SEARCH_SERVICE_NAME=$env:AZURE_SEARCH_SERVICE_NAME
AZURE_SEARCH_ADMIN_KEY=$SearchAdminKey
AZURE_OPENAI_ENDPOINT=$env:AZURE_OPENAI_ENDPOINT
AZURE_OPENAI_SERVICE_NAME=$env:AZURE_OPENAI_SERVICE_NAME
AZURE_OPENAI_KEY=$OpenAIKey
AZURE_OPENAI_CHATGPT_DEPLOYMENT=$env:AZURE_OPENAI_CHATGPT_DEPLOYMENT
AZURE_OPENAI_CHATGPT_MODEL_NAME=$env:AZURE_OPENAI_CHATGPT_MODEL_NAME
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=$env:AZURE_OPENAI_EMBEDDING_DEPLOYMENT
AZURE_TENANT_ID=$env:AZURE_TENANT_ID
MICROSOFT_FOUNDRY_PROJECT_ENDPOINT=$env:MICROSOFT_FOUNDRY_PROJECT_ENDPOINT
MICROSOFT_FOUNDRY_PROJECT_ID=$env:MICROSOFT_FOUNDRY_PROJECT_ID
INDEXING_STORAGE_ACCOUNT_ID=$env:INDEXING_STORAGE_ACCOUNT_ID
INDEXING_STORAGE_ACCOUNT_NAME=$env:INDEXING_STORAGE_ACCOUNT_NAME
CONTENTUNDERSTANDING_ENDPOINT=$env:CONTENTUNDERSTANDING_ENDPOINT
CONTENTUNDERSTANDING_KEY=$OpenAIKey
CONTENTUNDERSTANDING_API_VERSION=2025-11-01
RESTORE_INDEX_SNAPSHOTS=$env:RESTORE_INDEX_SNAPSHOTS
"@
$envPathRoot = Join-Path $repoRoot ".env"
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText($envPathRoot, $envContent, $utf8NoBom)
Write-Output "Created .env in repo root"

Push-Location $repoRoot
try {
    python (Join-Path $PSScriptRoot "setup-venv.py")
    if ($LASTEXITCODE -ne 0) { throw "Virtual environment setup failed." }
    $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
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