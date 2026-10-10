$bgScriptPath = "C:\Users\LabUser\Desktop\deploy-background.ps1"
$logFile = "C:\Users\LabUser\Desktop\lifecycle-log.txt"

$bgScript = @'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$logFile = "C:\Users\LabUser\Desktop\lifecycle-log.txt"
function Log {
    param([string]$msg)
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg"
    Write-Host $line
    Add-Content -Path $logFile -Value $line
}

Log "=== Background deploy script started ==="

$subscriptionId = $env:BG_SUBSCRIPTION_ID
$resourceGroupName = $env:BG_RESOURCE_GROUP
$labUserObjectId = $env:BG_LAB_USER_OID
$bicepFilePath = $env:BG_BICEP_PATH
$tenantId = $env:BG_TENANT_ID

az config set core.only_show_errors=yes --only-show-errors
az config set bicep.use_binary_from_path=false --only-show-errors

$deploymentName = "deployment"
$foundryDeploymentSuffix = [Guid]::NewGuid().ToString("N").Substring(0, 8)

Log "Starting Bicep deployment..."
$deploymentOutput = az deployment group create `
  --name $deploymentName `
  --resource-group $resourceGroupName `
  --template-file $bicepFilePath `
  --parameters principalId="$labUserObjectId" `
    --parameters resourcePrefix="lab673" `
  --parameters foundryDeploymentSuffix="$foundryDeploymentSuffix" `
  --parameters location="westus3" `
  --query properties.outputs -o json 2>&1
$deployExitCode = $LASTEXITCODE

if ($deployExitCode -ne 0) {
    Log "Deployment failed (exit code $deployExitCode):"
    Add-Content -Path $logFile -Value $deploymentOutput
    $opErrors = az deployment operation group list `
      --resource-group $resourceGroupName `
      --name $deploymentName `
      --query "[?properties.provisioningState=='Failed'].{Resource:properties.targetResource.resourceName, Type:properties.targetResource.resourceType, Error:properties.statusMessage.error}" `
      -o json 2>&1
    Log "Operation errors:"
    Add-Content -Path $logFile -Value $opErrors
    Log "=== Background deploy script FAILED ==="
    exit 1
}

Log "Deployment succeeded."

Add-Content -Path $logFile -Value $deploymentOutput
$outs = $deploymentOutput | ConvertFrom-Json
foreach ($property in $outs.PSObject.Properties) {
    [Environment]::SetEnvironmentVariable($property.Name, [string]$property.Value.value, "Process")
}
$env:AZURE_SUBSCRIPTION_ID = $subscriptionId
$env:AZURE_RESOURCE_GROUP = $resourceGroupName
$env:AZURE_PRINCIPAL_ID = $labUserObjectId
$env:AZURE_TENANT_ID = $tenantId
$env:RESTORE_INDEX_SNAPSHOTS = "true"

$searchName = $outs.AZURE_SEARCH_SERVICE_NAME.value
$openaiName = $outs.AZURE_OPENAI_SERVICE_NAME.value
Log "Fetching Search and Foundry API keys..."
$searchAdminKey = az rest --method POST `
    --url "https://management.azure.com/subscriptions/$subscriptionId/resourceGroups/$resourceGroupName/providers/Microsoft.Search/searchServices/$searchName/listAdminKeys?api-version=2026-09-01-preview" `
    --query primaryKey -o tsv
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($searchAdminKey)) {
        Log "ERROR: Could not retrieve the Search admin key."
        exit 1
}
$openaiKey = az cognitiveservices account keys list `
    -g $resourceGroupName -n $openaiName --query key1 -o tsv
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($openaiKey)) {
        Log "ERROR: Could not retrieve the Foundry API key."
        exit 1
}

$localInfraPath = "C:\Users\LabUser\Desktop\ignite26-LAB673\infra"
$setupLocal = Join-Path $localInfraPath "setup-knowledge.ps1"

if (-not (Test-Path $setupLocal)) {
    Log "ERROR: Setup file not found at: $setupLocal"
    exit 1
}

Log "Running setup-knowledge.ps1..."
powershell -ExecutionPolicy Bypass -File $setupLocal `
    -SearchAdminKey $searchAdminKey `
    -OpenAIKey $openaiKey *>> $logFile
if ($LASTEXITCODE -ne 0) {
    Log "ERROR: setup-knowledge.ps1 failed (exit $LASTEXITCODE)."
    exit 1
}

Log "=== Background deploy script completed ==="
'@

Set-Content -Path $bgScriptPath -Value $bgScript -Encoding UTF8

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
function Log {
    param([string]$msg)
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg"
    Write-Host $line
    Add-Content -Path $logFile -Value $line
}
Log "=== Lifecycle script started ==="

$clientId = "@lab.CloudSubscription.AppId"
$clientSecret = "@lab.CloudSubscription.AppSecret"
$tenantId = "@lab.CloudSubscription.TenantId"
$subscriptionId = "@lab.CloudSubscription.Id"

Log "Logging in to Azure..."
az login --service-principal -u $clientId -p $clientSecret --tenant $tenantId --subscription $subscriptionId --skip-subscription-discovery
if ($LASTEXITCODE -ne 0) { throw "Azure sign-in failed." }
az config set core.only_show_errors=yes --only-show-errors
az config set bicep.use_binary_from_path=false --only-show-errors

$resourceGroupName = "@lab.CloudResourceGroup(REPLACE_WITH_SKILLABLE_RESOURCE_GROUP_NAME).Name"
$bicepFilePath = "C:\Users\LabUser\Desktop\ignite26-LAB673\infra\main.bicep"

if (-not (Test-Path $bicepFilePath)) {
    Log "ERROR: Bicep file not found at: $bicepFilePath"
    throw "Bicep file not found at: $bicepFilePath"
}

$labUserUpn = "@lab.CloudPortalCredential(User1).Username"
$labUserObjectId = az ad user show --id $labUserUpn --query id -o tsv
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($labUserObjectId)) {
    throw "Could not resolve the attendee object ID."
}

$env:BG_SUBSCRIPTION_ID = $subscriptionId
$env:BG_RESOURCE_GROUP = $resourceGroupName
$env:BG_LAB_USER_OID = $labUserObjectId
$env:BG_BICEP_PATH = $bicepFilePath
$env:BG_TENANT_ID = $tenantId

Log "Launching background deploy process..."
Start-Process -FilePath "powershell.exe" `
  -ArgumentList "-ExecutionPolicy Bypass -File `"$bgScriptPath`"" `
  -WindowStyle Hidden

Log "=== Lifecycle script exiting (background process handles deployment) ==="