$ErrorActionPreference = "Stop"
$repoRoot = "C:\Users\LabUser\Desktop\ignite26-LAB673"
$backgroundScript = Join-Path $repoRoot "infra\deploy-background.ps1"
$logFile = "C:\Users\LabUser\Desktop\lifecycle-log.txt"
$clientId = "@lab.CloudSubscription.AppId"
$clientSecret = "@lab.CloudSubscription.AppSecret"
$tenantId = "@lab.CloudSubscription.TenantId"
$subscriptionId = "@lab.CloudSubscription.Id"
$resourceGroupName = "@lab.CloudResourceGroup(REPLACE_WITH_SKILLABLE_RESOURCE_GROUP_NAME).Name"
$labUserUpn = "@lab.CloudPortalCredential(User1).Username"

if (-not (Test-Path $backgroundScript)) {
    throw "Download the repository before running the deployment lifecycle action."
}

az login --service-principal -u $clientId -p $clientSecret --tenant $tenantId --subscription $subscriptionId --skip-subscription-discovery --output none
if ($LASTEXITCODE -ne 0) { throw "Azure sign-in failed." }
$labUserObjectId = az ad user show --id $labUserUpn --query id -o tsv
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($labUserObjectId)) {
    throw "Could not resolve the attendee object ID."
}

$env:AZURE_SUBSCRIPTION_ID = $subscriptionId
$env:AZURE_RESOURCE_GROUP = $resourceGroupName
$env:AZURE_PRINCIPAL_ID = $labUserObjectId
$env:AZURE_TENANT_ID = $tenantId
$env:AZURE_LOCATION = "westus3"
$env:RESTORE_INDEX_SNAPSHOTS = "true"
$env:LAB_DEPLOYMENT_LOG = $logFile
$clientSecret = $null

Start-Process -FilePath "powershell.exe" `
    -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$backgroundScript`"" `
    -WindowStyle Hidden
Write-Output "Deployment is running in the background. Progress is recorded in $logFile."