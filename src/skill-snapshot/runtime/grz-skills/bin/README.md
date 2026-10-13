# GRZBuildPoc

Standalone topic-diversity proof of concept extracted from
`robertlee/grz-poc`. It reads vectors from Azure AI Search, builds a weighted
CSR graph, runs hierarchical MSR Leiden, computes representative centroids, and
stores results locally or in an explicitly selected output index.

## Authentication

Use Microsoft Entra ID for customer Search services:

```powershell
az login --tenant "<customer-tenant-id>"
az account set --subscription "<customer-subscription-id>"
```

Configure:

```json
"authentication": {
  "mode": "defaultAzureCredential",
  "tenantId": "<customer-tenant-id>",
  "managedIdentityClientId": "",
  "managedIdentityObjectId": "",
  "managedIdentityResourceId": "",
  "allowInteractiveBrowser": false
}
```

The CLI requests an access token for
`https://search.azure.com/.default`. Azure AI Search SDK clients accept either
an `AzureKeyCredential` or any Azure Core `TokenCredential`; the CLI implements
the same two authentication contracts for its REST requests.

`defaultAzureCredential` is the recommended mode and covers environment,
workload identity, managed identity, Visual Studio, Visual Studio Code, Azure
CLI, Azure PowerShell, Azure Developer CLI, and optionally interactive browser
credentials. The `entraId` name remains an alias for backward compatibility.
The CLI also supports selecting `interactiveBrowser`, `deviceCode`,
`managedIdentity`, `workloadIdentity`, `servicePrincipal`, `azureCli`,
`azurePowerShell`, `azureDeveloperCli`, `visualStudio`, or `visualStudioCode`
directly. API-key authentication remains available as `apiKey`; its key is read
from the configured environment variable.

`servicePrincipal` uses `EnvironmentCredential`. Configure either
`AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, and `AZURE_CLIENT_SECRET`, or the
certificate variables supported by Azure Identity. `workloadIdentity` uses
`AZURE_CLIENT_ID` and `AZURE_FEDERATED_TOKEN_FILE`, plus either
`authentication.tenantId` or `AZURE_TENANT_ID`.

For `managedIdentity`, leave all selectors empty for the system-assigned
identity. For a user-assigned identity, configure exactly one of
`managedIdentityClientId`, `managedIdentityObjectId`, or
`managedIdentityResourceId`.

## Azure OpenAI community labeling

The GRZ build requires an Azure OpenAI deployment to generate human-readable
community labels. Configure the complete request URI:

```json
"azureOpenAI": {
  "llmResourceUri": "https://example.openai.azure.com/openai/deployments/example/chat/completions?api-version=2024-10-21"
},
"credentials": {
  "azureOpenAIApiKeyEnvironmentVariable": "AZURE_OPENAI_API_KEY"
}
```

Set the key outside the configuration file:

```powershell
$env:AZURE_OPENAI_API_KEY = "<customer-aoai-key>"
```

The build consumes the AOAI URI and key internally for community labeling. The
customer does not provide additional label fields or prompt configuration.
Never place the key value in JSON, command-line arguments, or source control.

Never place API keys, client secrets, certificates, or bearer tokens in
command-line arguments, configuration files, container images, or source
control.

## Configuration

Copy `config.example.json` and supply the service, index, vector field,
execution limits, and output settings. Keep
`execution.readOnly` set to `true` for initial runs. Credentials are resolved
by the configured Entra credential flow and are not stored in JSON.

Paths in the configuration are resolved relative to the configuration file.
For an HTTP-only development stamp, set `search.allowInsecureHttp` to `true`.
Never enable this for customer or production services because credentials and
payloads would be sent without TLS.

For a development cluster endpoint, set `search.serviceName` to the routed
service name. The tool adds `service=<name>` to every data-plane request. If
the development certificate does not match the cluster hostname, set
`search.allowInvalidCertificate` to `true`. This disables server identity
validation and must never be enabled for customer or production services.

## Run the tool

```powershell
.\GRZBuildPoc.exe validate --config .\config.json
.\GRZBuildPoc.exe plan --config .\config.json
.\GRZBuildPoc.exe execute --config .\config.json --yes
```

Linux and macOS use the same commands with `./GRZBuildPoc`. By default, the
tool enumerates only the key field in sorted pages and uses reservoir sampling
to select probe documents. This is read-only and does not download document
content or vectors during key discovery. The Search key field must be sortable.

`execution.samplePercent` controls the number of probe documents. It must be
between 3 and 5 and defaults to 5. The live source count is read first, then the
tool rounds the percentage up to a whole probe count. `probeSeed` keeps the
random sample reproducible across runs against the same source snapshot.

## Structured JSON output

Add `--json` to `validate`, `plan`, or `execute` for UI and automation
integration:

```powershell
.\GRZBuildPoc.exe plan --config .\config.json --json
.\GRZBuildPoc.exe validate --config .\config.json --json
.\GRZBuildPoc.exe execute --config .\config.json --yes --json
```

The command writes exactly one `grz-cli-v1` JSON envelope to stdout.
Human-readable diagnostics and progress remain on stderr. Successful execution
returns the output directory, receipt path, and parsed `receipt.json`.

Every `plan`, `validate`, and `execute` invocation also creates a timestamped
`grz-operation-*.log` text file in `outputDirectory`. If `config.json` cannot
be parsed, the log is created beside the configuration file instead. The log
contains runtime information, console diagnostics, step-level
`SUCCEEDED`/`FAILED` results, durations, the final exit code, and the overall
result. Customers should share this file when reporting a problem.

The support log intentionally excludes credential values, bearer tokens,
document contents, and vectors. It may contain the configured endpoint, index
names, file paths, request counts, and exception messages needed to diagnose
the run.

Example:

```json
{
  "schemaVersion": "grz-cli-v1",
  "status": "succeeded",
  "command": "execute",
  "exitCode": 0,
  "data": {
    "outputDirectory": "C:\\work\\results",
    "receiptPath": "C:\\work\\results\\receipt.json",
    "receipt": {}
  },
  "errorCode": null,
  "error": null
}
```

## `grz-skills` integration

`grz-skills` should invoke the CLI as a child process using the versioned JSON
output:

```powershell
.\GRZBuildPoc.exe validate --config C:\grz\config.json --json
.\GRZBuildPoc.exe plan --config C:\grz\config.json --json
.\GRZBuildPoc.exe execute --config C:\grz\config.json --yes --json
```

The skill reads the single JSON envelope from stdout, displays diagnostics from
stderr, and monitors `progress.json` and `receipt.json` in the configured output
directory. The executable runs as a normal child process and exits when the
command completes.

## Build and test

The project requires .NET SDK 10.0.100 or a compatible .NET 10 feature band.
It pins `Microsoft.Network.Leiden.Csr` 3.0.0. Clean restore requires access to a
feed containing that package.

```powershell
$env:GRZ_LEIDEN_NUGET_SOURCE = "<approved-MSR-GraphRAG-NuGet-v3-source>"
dotnet restore .\Tests\GRZBuildPoc.Tests.csproj `
    --source "https://msdata.pkgs.visualstudio.com/bbd6e814-7e33-452b-9cc7-690473457fb8/_packaging/AzureSearch-Aggregated-2022/nuget/v3/index.json" `
    --source $env:GRZ_LEIDEN_NUGET_SOURCE
dotnet build .\GRZBuildPoc.csproj --no-restore
dotnet test .\Tests\GRZBuildPoc.Tests.csproj --no-restore
```

## Cross-platform packages

Production and customer releases use separate publication and packaging
operations so approved signing can run between them:

```powershell
.\Publish-Runtimes.ps1 -Version "<version>"

# Sign and verify artifacts\<runtime>\publish with the approved
# Windows, macOS, and release signing systems.

.\Create-Packages.ps1 -Version "<version>"
```

The scripts create self-contained packages for:

- Windows x64
- Linux x64 and ARM64
- macOS x64 and ARM64

The same C# source is used for every target, but each operating system and CPU
architecture requires its own executable. `Publish-Runtimes.ps1` writes the
unsigned runtime files to `artifacts\<runtime>\publish`.
`Create-Packages.ps1` packages those files only after the signing stage and
generates checksums over the signed package contents.

`Publish-Packages.ps1` is a local development wrapper that can create temporary
self-signed Windows and archive signatures. Do not use those test signatures
for customer releases.

When using the local test wrapper, verify an archive with:

```bash
openssl dgst -sha256 \
    -verify GRZBuildPoc-TestSigning.pub.pem \
    -signature GRZBuildPoc-0.1.5-linux-x64.tar.gz.sig \
    GRZBuildPoc-0.1.5-linux-x64.tar.gz
```

Linux and macOS archives are produced from Windows without Unix execute bits.
After extraction, run:

```bash
chmod +x GRZBuildPoc
```

## Docker

Start Docker Desktop or another Linux container engine, then run:

```powershell
.\Build-Container.ps1 -Image "grz-build-poc:0.1.0"
```

Pass the key only when starting the container:

```powershell
docker run --rm `
    -e AZURE_SEARCH_API_KEY `
    -e AZURE_OPENAI_API_KEY `
    -v "${PWD}\config.docker.json:/app/config.json:ro" `
    -v "${PWD}\results:/results" `
    grz-build-poc:0.1.0 `
    execute --config /app/config.json --yes
```

For the container configuration, set `outputDirectory` to `/results`.

The image contains the self-contained Linux x64 executable and does not require
the .NET runtime in the final container.
