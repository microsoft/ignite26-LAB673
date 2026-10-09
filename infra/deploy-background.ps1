$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$repoRoot = Split-Path $PSScriptRoot -Parent
$logFile = $env:LAB_DEPLOYMENT_LOG
if (-not $logFile) { $logFile = Join-Path $repoRoot "lifecycle-log.txt" }

function Write-LabLog {
    param([string]$Message)
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Message"
    Write-Output $line
    Add-Content -Path $logFile -Value $line
}

try {
    foreach ($name in @("AZURE_SUBSCRIPTION_ID", "AZURE_RESOURCE_GROUP", "AZURE_PRINCIPAL_ID", "AZURE_LOCATION")) {
        if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name))) {
            throw "Missing deployment setting: $name"
        }
    }
    Write-LabLog "Starting lab resource deployment."
    $deploymentOutput = az deployment group create `
        --subscription $env:AZURE_SUBSCRIPTION_ID `
        --resource-group $env:AZURE_RESOURCE_GROUP `
        --name lab673 `
        --template-file (Join-Path $PSScriptRoot "main.bicep") `
        --parameters principalId="$env:AZURE_PRINCIPAL_ID" location="$env:AZURE_LOCATION" `
        --query properties.outputs -o json --only-show-errors
    if ($LASTEXITCODE -ne 0) { throw "Resource deployment failed." }
    $outputs = $deploymentOutput | ConvertFrom-Json
    foreach ($property in $outputs.PSObject.Properties) {
        [Environment]::SetEnvironmentVariable($property.Name, [string]$property.Value.value, "Process")
    }
    Write-LabLog "Resources deployed. Preparing the lab environment."
    & (Join-Path $PSScriptRoot "setup-knowledge.ps1") *>> $logFile
    Write-LabLog "Lab setup completed successfully."
} catch {
    Write-LabLog "Lab setup FAILED: $($_.Exception.Message)"
    exit 1
}