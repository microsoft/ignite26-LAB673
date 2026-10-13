# GRZ CLI Production Packaging, Signing, and Delivery

The production release contains separate self-contained binaries for:

| Platform | Runtime identifier | Package |
|---|---|---|
| Windows x64 | `win-x64` | `.zip` |
| Linux x64 | `linux-x64` | `.tar.gz` |
| Linux ARM64 | `linux-arm64` | `.tar.gz` |
| macOS Intel | `osx-x64` | `.zip` |
| macOS Apple Silicon | `osx-arm64` | `.zip` |

Customers do not need to install .NET.

## 1. Get release-pipeline onboarding

Contact the Azure Search Engineering Foundations/release owners and request:

1. An **official OneBranch build pipeline** for `GRZBuildPoc`.
2. **CloudSign** access for Windows binaries.
3. A **OneBranch Non-Azure/ESRP release pipeline** for external package publication.
4. Microsoft Apple Developer signing/notarization onboarding for macOS.
5. An approved external download destination.

If the release writes directly to an Azure Storage account, use the approved
OneBranch EV2/Managed SDP Azure release path instead of Non-Azure Release.

Repository references:

```text
.pipelines\RPManifest\Prod-AzureSearch-Rollout-ARM-Manifest.yml
Build\Local\Extensions\After.Publish.CodeSign.targets
```

Internal guidance referenced by the repository:

```text
https://aka.ms/onebranchrelease
https://aka.ms/releaseyamlfornonazure
https://aka.ms/releaseyamlforev2
```

This is the conventional Microsoft pattern for externally distributed
binaries.

## 2. Split build, signing, and packaging

The production pipeline must execute in this order:

```text
Publish unsigned runtime directories
→ Sign binaries
→ Package ZIP/TAR
→ Generate checksums
→ Sign release manifest
→ Verify
→ Publish
```

The repository implements the required split with two scripts:

```powershell
.\Publish-Runtimes.ps1 -Version "$(Build.BuildNumber)"

# The approved platform signing operation modifies the files under:
# artifacts\<runtime>\publish

.\Create-Packages.ps1 -Version "$(Build.BuildNumber)"
```

`Publish-Runtimes.ps1`:

- Publishes each self-contained runtime.
- Writes unsigned inputs to `artifacts\<runtime>\publish`.
- Does not create customer archives.
- Does not apply test or production signatures.

The signing stage runs after publication and before packaging. It must modify
the executables and libraries in those publish directories in place. Each
platform's signing verification must pass before the packaging stage starts.

`Create-Packages.ps1`:

- Fails when an expected runtime executable is missing.
- Copies the already-signed runtime files into the customer package.
- Adds the README, configuration example, datasets, and this runbook.
- Generates `checksums.sha256` after signing.
- Creates the versioned ZIP or TAR.GZ archive.

The pipeline then signs the release manifest or archive according to the
approved release system, verifies the resulting signatures and checksums, and
publishes the immutable version.

`Publish-Packages.ps1` remains a local development convenience wrapper. It
calls both scripts and can create temporary self-signed test artifacts. Do not
use that wrapper for a customer or production release because production
signing must be an independently governed pipeline operation.

## 3. Windows signing

Azure Search already uses CloudSign through:

```text
Build\Local\Extensions\After.Publish.CodeSign.targets
```

The existing pattern is:

```xml
<AdditionalFilesToSign Include="$(PublishDir)*.dll" />
<AdditionalFilesToSign Include="$(PublishDir)*.exe" />
<CustomCodeSignCertificates>
  $(CloudSignThirdPartyCertificate)
</CustomCodeSignCertificates>
```

Have the official build set:

```text
ENABLE_CODESIGN=1
```

Sign:

```text
artifacts\win-x64\publish\GRZBuildPoc.exe
artifacts\win-x64\publish\*.dll
```

Verify in the pipeline:

```powershell
$signature = Get-AuthenticodeSignature `
  .\artifacts\win-x64\publish\GRZBuildPoc.exe

if ($signature.Status -ne "Valid")
{
    throw "GRZBuildPoc.exe does not have a valid production signature."
}

if ($signature.SignerCertificate.Subject -notlike "*Microsoft Corporation*")
{
    throw "GRZBuildPoc.exe was not signed by Microsoft."
}
```

Do not use:

```text
GRZBuildPoc-TestSigning.*
New-SelfSignedCertificate
```

## 4. macOS signing and notarization

Request access to the centrally managed Microsoft Apple Developer identity.

Run on a OneBranch macOS agent:

```bash
codesign \
  --force \
  --options runtime \
  --timestamp \
  --sign "Developer ID Application: Microsoft Corporation (<TEAM-ID>)" \
  ./artifacts/osx-arm64/publish/GRZBuildPoc
```

Verify:

```bash
codesign --verify --strict --verbose=2 \
  ./artifacts/osx-arm64/publish/GRZBuildPoc

spctl --assess --type execute --verbose=4 \
  ./artifacts/osx-arm64/publish/GRZBuildPoc
```

Package:

```bash
ditto -c -k --keepParent \
  ./artifacts/osx-arm64/publish \
  GRZBuildPoc-1.0.0-osx-arm64.zip
```

Notarize:

```bash
xcrun notarytool submit \
  GRZBuildPoc-1.0.0-osx-arm64.zip \
  --keychain-profile "MICROSOFT-NOTARY" \
  --wait
```

Repeat for `osx-x64`.

This is the standard Apple requirement, not an Azure Search-specific process.

## 5. Linux and archive signing

Linux does not have an Authenticode equivalent for standalone executables.

Use:

1. SHA-256 checksums for every archive.
2. A signed `release.json`.
3. ESRP/approved Microsoft release signing for the manifest or detached
   signatures.

Generate checksums:

```powershell
Get-ChildItem .\release\*.zip, .\release\*.tar.gz |
  Get-FileHash -Algorithm SHA256 |
  ForEach-Object {
    "$($_.Hash)  $($_.Path | Split-Path -Leaf)"
  } |
  Set-Content .\release\SHA256SUMS
```

Generate `release.json`:

```json
{
  "version": "1.0.0",
  "commit": "<commit-sha>",
  "artifacts": {
    "win-x64": {
      "file": "GRZBuildPoc-1.0.0-win-x64.zip",
      "sha256": "<sha256>"
    },
    "linux-x64": {
      "file": "GRZBuildPoc-1.0.0-linux-x64.tar.gz",
      "sha256": "<sha256>"
    },
    "linux-arm64": {
      "file": "GRZBuildPoc-1.0.0-linux-arm64.tar.gz",
      "sha256": "<sha256>"
    },
    "osx-x64": {
      "file": "GRZBuildPoc-1.0.0-osx-x64.zip",
      "sha256": "<sha256>"
    },
    "osx-arm64": {
      "file": "GRZBuildPoc-1.0.0-osx-arm64.zip",
      "sha256": "<sha256>"
    }
  }
}
```

Have ESRP/release engineering sign:

```text
release.json
SHA256SUMS
```

Do not create a team-owned GPG/private signing key without release-engineering
approval.

## 6. Block an invalid release

Add a verification stage that fails unless:

```text
All five packages exist
Windows signature is valid
macOS signatures are valid
macOS notarization succeeded
Every SHA-256 matches release.json
release.json has an approved signature
No test certificates exist in the package
Malware and SDL scans passed
Version and commit are immutable
```

Example checksum gate:

```powershell
Get-Content .\release\SHA256SUMS | ForEach-Object {
    $expected, $file = $_ -split '\s+', 2
    $actual = (Get-FileHash ".\release\$file" -Algorithm SHA256).Hash

    if ($actual -ne $expected)
    {
        throw "Checksum verification failed for $file."
    }
}
```

Configure the publish stage to depend on this stage:

```yaml
dependsOn: VerifyRelease
condition: succeeded()
```

## 7. Publish through ESRP/OneBranch

Use a **OneBranch Non-Azure Release** when ESRP or another approved external
package channel owns publication. If the target is an Azure Storage account,
use an approved EV2/Managed SDP Azure release.

Publish immutable paths:

```text
/grz/1.0.0/release.json
/grz/1.0.0/SHA256SUMS
/grz/1.0.0/GRZBuildPoc-1.0.0-win-x64.zip
/grz/1.0.0/GRZBuildPoc-1.0.0-linux-x64.tar.gz
/grz/1.0.0/GRZBuildPoc-1.0.0-linux-arm64.tar.gz
/grz/1.0.0/GRZBuildPoc-1.0.0-osx-x64.zip
/grz/1.0.0/GRZBuildPoc-1.0.0-osx-arm64.zip
```

Never overwrite an existing version. Publish a new version for every change.

For a private preview, have the webtool entitlement service issue a short-lived
download URL. Do not embed SAS tokens, storage keys, or signing credentials in
`grz-skills`.

## 8. Complete required approvals

| Approval | Required material |
|---|---|
| Security | Threat model, authentication flow, update flow, signature verification, and local-file handling |
| Privacy | Customer data accessed, outputs, telemetry, retention, deletion, and data egress |
| Legal/IP | Approval to distribute the GRZ implementation and MSR Leiden dependency |
| OSS/package | Component Governance results, licenses, attribution, and third-party notices |
| External preview | Customers, preview terms, limitations, expiration, and rollback plan |
| Support | Owning team, support alias, IcM team, diagnostics, and revocation process |

Prepare:

```text
Threat model
Data-flow diagram
Privacy questionnaire
Component Governance report
ThirdPartyNotices.txt
License notices
Preview terms
Support and incident runbook
Release and rollback plan
```

## 9. Microsoft Entra ID and Azure AI Search RBAC

Customer administrators should use the public Azure AI Search documentation for
service-side authentication and role-assignment procedures. This runbook only
defines the configuration contract required by `GRZBuildPoc`.

Public setup references:

- [Enable role-based access in Azure AI Search](https://learn.microsoft.com/azure/search/search-security-enable-roles)
- [Azure AI Search built-in roles](https://learn.microsoft.com/azure/search/search-security-rbac)
- [Connect an application using identities](https://learn.microsoft.com/azure/search/search-security-rbac-client-code)
- [Manage Azure AI Search API keys](https://learn.microsoft.com/azure/search/search-security-api-keys)
- [Azure Identity credential chains for .NET](https://learn.microsoft.com/dotnet/azure/sdk/authentication/credential-chains)

### `config.json` contract

For a public customer Search service, configure:

```json
{
  "search": {
    "endpoint": "https://<service-name>.search.windows.net",
    "apiVersion": "2026-08-01-preview",
    "serviceName": "",
    "sourceIndex": "<source-index>",
    "vectorField": "<vector-field>",
    "allowInsecureHttp": false,
    "allowInvalidCertificate": false
  },
  "authentication": {
    "mode": "defaultAzureCredential",
    "tenantId": "<customer-tenant-id>",
    "managedIdentityClientId": "",
    "managedIdentityObjectId": "",
    "managedIdentityResourceId": "",
    "allowInteractiveBrowser": false
  },
  "credentials": {
    "searchApiKeyEnvironmentVariable": "AZURE_SEARCH_API_KEY"
  }
}
```

`serviceName` is only for internal shared-cluster or devstamp routing and must
remain empty for customer services. Both insecure transport options must remain
`false` for customer and production services.

| Configuration field | Purpose |
|---|---|
| `authentication.mode` | Selects the Search credential flow |
| `authentication.tenantId` | Selects the customer's Entra tenant for user and application credentials |
| `authentication.managedIdentityClientId` | Selects a user-assigned managed identity by client ID |
| `authentication.managedIdentityObjectId` | Alternative user-assigned identity selector by object ID |
| `authentication.managedIdentityResourceId` | Alternative user-assigned identity selector by Azure resource ID |
| `authentication.allowInteractiveBrowser` | Allows browser fallback inside `defaultAzureCredential` when explicitly enabled |
| `credentials.searchApiKeyEnvironmentVariable` | Names the environment variable containing the Search key when `mode` is `apiKey` |

Configure at most one managed-identity selector. Leave all three empty to use a
system-assigned managed identity. Do not put email addresses, subscription IDs,
RBAC assignments, access tokens, API-key values, client secrets, or certificate
contents in `config.json`.

Supported Search authentication modes:

| Mode | Credential source |
|---|---|
| `defaultAzureCredential` | Recommended Azure Identity credential chain |
| `entraId` | Backward-compatible alias for `defaultAzureCredential` |
| `interactiveBrowser` | Explicit browser sign-in |
| `deviceCode` | Device-code sign-in |
| `managedIdentity` | System-assigned or selected user-assigned managed identity |
| `workloadIdentity` | Federated workload identity |
| `servicePrincipal` | Azure Identity environment credential using protected secret or certificate variables |
| `azureCli` | Existing Azure CLI sign-in |
| `azurePowerShell` | Existing Azure PowerShell sign-in |
| `azureDeveloperCli` | Existing Azure Developer CLI sign-in |
| `visualStudio` | Visual Studio Azure account |
| `visualStudioCode` | Visual Studio Code Azure account supported by the packaged dependencies |
| `apiKey` | Search admin key read from the configured environment variable |

### Search permissions expected by the CLI

The role assignment is customer-managed and is not represented in
`config.json`:

| Execution mode | Search roles expected |
|---|---|
| Schema-aware read-only execution | `Search Service Contributor` and `Search Index Data Reader` |
| Write-enabled execution | `Search Service Contributor` and `Search Index Data Contributor` |

API-key mode requires an admin key because the CLI reads the index definition
in addition to querying documents. Refer to the public role and API-key
documentation above for assignment and key-management procedures.

## 10. Configure and use the tool

### Start with the released artifact

The customer or `grz-skills` starts with the versioned archive for the host
platform, not with a loose executable:

```text
GRZBuildPoc-<version>-win-x64.zip
GRZBuildPoc-<version>-linux-x64.tar.gz
GRZBuildPoc-<version>-linux-arm64.tar.gz
GRZBuildPoc-<version>-osx-x64.tar.gz
GRZBuildPoc-<version>-osx-arm64.tar.gz
```

The delivery system must first verify the archive against the signed release
manifest or detached release signature. After extraction, verify
`checksums.sha256` before launching the executable.

Keep the extracted directory intact. A Windows package has this shape:

```text
grz\
|-- GRZBuildPoc.exe
|-- config.example.json
|-- checksums.sha256
|-- README.md
\-- PACKAGING-AND-SIGNING.md
```

Linux and macOS use `GRZBuildPoc` without the `.exe` extension.

| Item | Purpose | Required at runtime |
|---|---|---|
| `GRZBuildPoc.exe` or `GRZBuildPoc` | Self-contained CLI | Yes |
| Customer-created `config.json` | Search endpoint, authentication selection, and execution settings | Yes, but it may be stored elsewhere and passed with an absolute path |
| `checksums.sha256` | Verifies extracted package contents | Required for installation verification; not read by the CLI |
| `config.example.json` | Safe starting template for customer configuration | Setup reference |
| Markdown files | Customer and operator instructions | Reference |

Because the executable is published as a self-contained single file, the
customer does not install .NET and does not keep loose runtime DLLs beside it.
Do not rename or extract individual files from an unverified archive.

For `grz-skills`, use a stable installation layout such as:

```text
grz-skills\
|-- tools\
|   \-- grz-build\<version>\<runtime>\
|       |-- GRZBuildPoc.exe
|       |-- checksums.sha256
|       \-- package reference files
\-- config\
    \-- customer-search.json
```

The skill should select the runtime archive for the host, verify it, extract it
to a versioned directory, and invoke the executable by absolute path. Keep
customer configuration and generated results outside the immutable tool
directory so a tool upgrade does not overwrite them.

### Create `config.json`

Copy `config.example.json` to a customer-owned location and rename it
`config.json`. Example:

```json
{
  "search": {
    "endpoint": "https://customer-service.search.windows.net",
    "apiVersion": "2026-08-01-preview",
    "allowInsecureHttp": false,
    "allowInvalidCertificate": false,
    "serviceName": "",
    "sourceIndex": "customer-index",
    "vectorField": "contentVector"
  },
  "authentication": {
    "mode": "defaultAzureCredential",
    "tenantId": "<customer-tenant-id>",
    "managedIdentityClientId": "",
    "managedIdentityObjectId": "",
    "managedIdentityResourceId": "",
    "allowInteractiveBrowser": false
  },
  "azureOpenAI": {
    "llmResourceUri": "https://example.openai.azure.com/openai/deployments/example/chat/completions?api-version=2024-10-21"
  },
  "credentials": {
    "searchApiKeyEnvironmentVariable": "AZURE_SEARCH_API_KEY",
    "azureOpenAIApiKeyEnvironmentVariable": "AZURE_OPENAI_API_KEY"
  },
  "execution": {
    "samplePercent": 5,
    "probeSeed": 1234,
    "threshold": 0,
    "maxLeafSize": 100,
    "concurrency": 8,
    "requestsPerSecond": 25,
    "readOnly": true,
    "stopAfterGraph": false,
    "enableVectorRetrieval": false
  },
  "outputDirectory": "./results",
  "outputIndex": ""
}
```

For a public customer Search service:

- Keep `serviceName` empty.
- Keep both insecure TLS options `false`.
- Use a sortable index key field.
- Do not place credentials directly in `config.json`.

The `azureOpenAI` block is required. The GRZ build process uses the configured
AOAI deployment internally to generate human-readable community labels after
community construction. No additional label-field or prompt configuration is
required from the customer. Naming the AOAI environment variable in JSON does
not expose the key; the key value remains outside the file.

### Required AOAI setup for both Search authentication options

AOAI configuration and authentication are required regardless of whether
Azure AI Search uses Option A (Entra ID) or Option B (Search API key). These are
separate services and separate credentials.

The customer retrieves the key for the AOAI resource referenced by
`azureOpenAI.llmResourceUri` from:

```text
Azure portal
→ Azure OpenAI resource
→ Resource Management
→ Keys and Endpoint
```

Or with Azure CLI:

```powershell
$env:AZURE_OPENAI_API_KEY = az cognitiveservices account keys list `
  --name "<aoai-resource>" `
  --resource-group "<resource-group>" `
  --query key1 `
  --output tsv
```

The environment-variable name must match
`credentials.azureOpenAIApiKeyEnvironmentVariable`. Do not include the key
value in `config.json`. The GRZ build consumes the AOAI URI and key internally
when generating community labels; the customer does not provide additional
label-generation inputs.

### Option A: Microsoft Entra ID for Search

This is the recommended customer configuration:

```json
"authentication": {
  "mode": "defaultAzureCredential",
  "tenantId": "<customer-tenant-id>"
}
```

The customer signs in before launching the CLI:

```powershell
az login --tenant "<customer-tenant-id>"
az account set --subscription "<customer-subscription-id>"
```

The CLI obtains and refreshes the Search access token. The customer does not
create or paste a token into the configuration.

### Option B: Azure AI Search API key

Use API-key mode only when the customer cannot use Entra ID:

```json
"authentication": {
  "mode": "apiKey"
}
```

Keep the common `azureOpenAI` and `credentials` blocks from the complete
configuration example unchanged. Option B adds the Search API key; it does not
replace or provide the required AOAI key.

The customer administrator retrieves a Search admin key from:

```text
Azure portal
→ Azure AI Search service
→ Settings
→ Keys
→ Primary admin key or Secondary admin key
```

Or with Azure CLI:

```powershell
$env:AZURE_SEARCH_API_KEY = az search admin-key show `
  --service-name "<search-service>" `
  --resource-group "<resource-group>" `
  --query primaryKey `
  --output tsv
```

The current tool reads the index definition as well as querying documents, so
a query key alone is insufficient. API-key mode requires an admin key. Keep the
key in a protected process environment or secret store, never in
`config.json`, command-line arguments, logs, source control, or the tool
archive.

### Run the CLI directly

From the verified extracted package directory:

```powershell
.\GRZBuildPoc.exe validate --config .\config.json
.\GRZBuildPoc.exe plan --config .\config.json
.\GRZBuildPoc.exe execute --config .\config.json --yes
```

The configuration can be outside the package:

```powershell
.\GRZBuildPoc.exe validate `
  --config "C:\grz-skills\config\customer-search.json"
```

Results are written under the configured `outputDirectory`.

Each command also creates a timestamped `grz-operation-*.log` customer
support file in `outputDirectory`. If the configuration cannot be parsed, the
log is created beside `config.json`. It contains step-level success or failure
results, durations, console diagnostics, runtime information, and the final
exit code. Ask the customer to share this log when reporting a failure.

The support log excludes credential values, bearer tokens, document contents,
and vectors. It can include service endpoints, index names, local paths,
request counts, and exception messages needed for investigation.

For the initial customer POC, keep `readOnly` set to `true`. This prevents
Search schema changes, index creation, and document uploads.

### Integrate directly with `grz-skills`

`grz-skills` invokes the executable as a normal child process and reads its
structured output.

Use the absolute executable and configuration paths:

```powershell
C:\grz-skills\tools\grz-build\0.1.5\win-x64\GRZBuildPoc.exe `
  validate `
  --config C:\grz-skills\config\customer-search.json `
  --json
```

The integration sequence is:

1. Run `validate --json`.
2. Run `plan --json` and present the plan to the customer.
3. Obtain explicit customer confirmation.
4. Run `execute --yes --json`.
5. Monitor `progress.json` and read `receipt.json` from the configured
   `outputDirectory`.
6. Retain the generated `grz-operation-*.log` so it can be shared with the
   GRZ team if the customer reports a problem.

Each command writes one `grz-cli-v1` JSON envelope to stdout. Human-readable
diagnostics and progress are written to stderr. `grz-skills` should inherit the
signed-in customer environment or the required key/service-principal
environment variables, but it should never read, log, or transmit credential
values.

## References

- [OneBranch Release](https://aka.ms/onebranchrelease)
- [Microsoft Artifact Signing integrations](https://learn.microsoft.com/azure/artifact-signing/how-to-signing-integrations)
- [Apple notarization](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)
- [.NET single-file deployment](https://learn.microsoft.com/dotnet/core/deploying/single-file/overview)
- [Enable RBAC in Azure AI Search](https://learn.microsoft.com/azure/search/search-security-enable-roles)
- [Azure AI Search built-in roles](https://learn.microsoft.com/azure/search/search-security-rbac)
- [Azure AI Search keyless connection](https://learn.microsoft.com/azure/search/search-get-started-rbac)
- [Azure AI Search .NET client authentication](https://learn.microsoft.com/dotnet/api/overview/azure/search.documents-readme)
- [Credential chains in Azure Identity for .NET](https://learn.microsoft.com/dotnet/azure/sdk/authentication/credential-chains)
