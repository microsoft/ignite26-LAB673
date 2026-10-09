$ErrorActionPreference = "Stop"
$repository = "microsoft/ignite26-LAB673"
$revision = "main"
$targetPath = "C:\Users\LabUser\Desktop\ignite26-LAB673"
$tempRoot = Join-Path $env:TEMP ([Guid]::NewGuid().ToString("N"))
$tempZip = Join-Path $tempRoot "repo.zip"
$tempExtract = Join-Path $tempRoot "extracted"

if (Test-Path $targetPath) {
    throw "The repository folder already exists: $targetPath. Preserve it or remove it explicitly before downloading again."
}

New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
try {
    $headers = @{ Accept = "application/vnd.github+json" }
    if ($env:GITHUB_TOKEN) {
        $headers.Authorization = "Bearer $env:GITHUB_TOKEN"
    }
    $zipUrl = "https://api.github.com/repos/$repository/zipball/$revision"
    Invoke-WebRequest -Uri $zipUrl -Headers $headers -OutFile $tempZip -UseBasicParsing
    Expand-Archive -Path $tempZip -DestinationPath $tempExtract -Force
    $extractedFolder = Get-ChildItem $tempExtract -Directory | Select-Object -First 1
    if (-not $extractedFolder) { throw "The repository archive contains no folder." }
    Move-Item $extractedFolder.FullName $targetPath
    Write-Output "Downloaded lab resources to $targetPath."
} finally {
    Remove-Item $tempRoot -Recurse -Force
}