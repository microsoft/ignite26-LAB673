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
    $searchAdminKey = az rest --method POST `
        --url "https://management.azure.com/subscriptions/$env:AZURE_SUBSCRIPTION_ID/resourceGroups/$env:AZURE_RESOURCE_GROUP/providers/Microsoft.Search/searchServices/$env:AZURE_SEARCH_SERVICE_NAME/listAdminKeys?api-version=2026-09-01-preview" `
        --query primaryKey -o tsv
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($searchAdminKey)) {
        throw "Could not retrieve the Search admin key."
    }
    $openaiKey = az cognitiveservices account keys list `
        -g $env:AZURE_RESOURCE_GROUP -n $env:AZURE_OPENAI_SERVICE_NAME --query key1 -o tsv
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($openaiKey)) {
        throw "Could not retrieve the Foundry API key."
    }
    Write-LabLog "Resources deployed. Preparing the lab environment."
    & (Join-Path $PSScriptRoot "setup-knowledge.ps1") `
        -SearchAdminKey $searchAdminKey `
        -OpenAIKey $openaiKey *>> $logFile
    Write-LabLog "Lab setup completed successfully."
} catch {
    Write-LabLog "Lab setup FAILED: $($_.Exception.Message)"
    exit 1
}