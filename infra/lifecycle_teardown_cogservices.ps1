param(
    [Parameter(Mandatory=$true)][string]$ResourceGroupName,
    [ValidatePattern('^[a-z0-9]{3,8}$')][string]$ResourcePrefix = "lab673"
)

$ErrorActionPreference = "Stop"
$subscriptionId = (Get-AzContext).Subscription.Id
if (-not $subscriptionId) { throw "Sign in to the lab subscription before cleanup." }
$accounts = @(Get-AzResource -ResourceType "Microsoft.CognitiveServices/accounts" -ResourceGroupName $ResourceGroupName)

foreach ($account in $accounts) {
    if ($account.Name -notlike "${ResourcePrefix}-foundry-*") { continue }
    $accountName = $account.Name
    $accountLocation = $account.Location
    $projects = Get-AzResource -ResourceType "Microsoft.CognitiveServices/accounts/projects" -ResourceGroupName $ResourceGroupName
    foreach ($project in $projects) {
        if ($project.ResourceId.StartsWith("$($account.ResourceId)/projects/", [StringComparison]::OrdinalIgnoreCase)) {
            Remove-AzResource -ResourceId $project.ResourceId -Force
        }
    }
    $deployments = Get-AzCognitiveServicesAccountDeployment -ResourceGroupName $ResourceGroupName -AccountName $accountName
    foreach ($deployment in $deployments) {
        Remove-AzCognitiveServicesAccountDeployment -ResourceId $deployment.Id -Force
    }
    Remove-AzResource -ResourceId $account.ResourceId -Force
    $deletedAccountId = "/subscriptions/$subscriptionId/providers/Microsoft.CognitiveServices/locations/$accountLocation/resourceGroups/$ResourceGroupName/deletedAccounts/$accountName"
    $purged = $false
    for ($attempt = 0; $attempt -lt 6; $attempt++) {
        try {
            Remove-AzResource -ResourceId $deletedAccountId -ApiVersion "2024-10-01" -Force -ErrorAction Stop
            $purged = $true
            break
        } catch {
            if ($attempt -lt 5) { Start-Sleep -Seconds 10 }
        }
    }
    if (-not $purged) { throw "Could not purge the deleted Foundry account: $accountName" }
    Write-Output "Deleted and purged lab Foundry account: $accountName"
}