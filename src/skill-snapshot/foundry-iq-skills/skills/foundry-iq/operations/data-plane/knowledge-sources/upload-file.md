# Upload File Knowledge Sources

**Operation ID:** `KnowledgeSources_UploadFile`
**Plane:** data
**Safety:** write

## Quick reference

- **Method/path:** `POST /knowledgesources('{sourceName}')/files`
- **API version parameter:** `dataApiVersion`
- **Endpoint:** `https://<search-service>.search.windows.net`
- **Preferred interface:** contract-complete Azure MCP operation; fallback a binary-capable HTTP client such as PowerShell `Invoke-WebRequest`; use the SDK when generating application code.
- **Minimum role:** Search Service Contributor

## When to use / Do not use

Use only for the single `KnowledgeSources_UploadFile` REST action. Route multi-step customer outcomes to `hero-scenarios/` and failures to `troubleshooting/`.

The source must already have `kind: file`; use the [File creation guide](../../../references/knowledge-sources/file.md) if it does not exist. Do not use this operation for Blob, OneLake, SharePoint, or Search index sources.

## Inputs and context discovery

Reuse `dataApiVersion` already resolved for the current task. If absent, resolve it using [API version policy](../../../references/api-version-policy.md) before any request; this also applies when called directly without a hero scenario. Set `$dataApiVersion` to that exact value in the same PowerShell invocation as the request. Check the selected version's request/response contract; never silently change an inherited or explicit version.

Resolve every path placeholder from the active Azure context or the user. Preserve query parameters, request headers, body fields, and resource names exactly. Discover subscription, resource group, service endpoint, current object, ETag, region/tier support, and role assignments before mutation.

Confirm the approved file path/name, detected content type, size, and the selected version's limits. Acquire a Search-audience token and set `$searchToken` privately in the same invocation; never print it.

## Preconditions and authentication

Acquire a Search token for `https://search.azure.com/.default`. Prefer Microsoft Entra ID and least privilege. Use the resolved `dataApiVersion`; never silently fall back to keys, another tenant, a public endpoint, or another API version.

## Safety or approval gate

Show the desired-state diff and obtain approval before billable, permission, network, production, or data-movement changes.

## Request contract

```powershell
if ([string]::IsNullOrWhiteSpace($dataApiVersion)) { throw "Resolve dataApiVersion using the shared API version policy before this request." }
if ([string]::IsNullOrWhiteSpace($searchToken)) { throw "Acquire a Search-audience token before uploading a file." }
Invoke-WebRequest -Method Post -Uri "https://<search-service>.search.windows.net/knowledgesources('{sourceName}')/files?api-version=$dataApiVersion" -Headers @{ Authorization = "Bearer $searchToken"; "Content-Disposition" = 'attachment; filename="<file-name>"' } -ContentType "application/octet-stream" -InFile "<file-path>" -ErrorAction Stop
```

Send raw file bytes, not JSON, base64 text, or an `az rest --body` text-file expansion. The baseline requires `Content-Disposition: attachment; filename="<file-name>"`. Use a safe filename with no quote or newline characters. Do not assume POST is idempotent.

## Execution and validation

Execute once and retain status code, request ID, and the returned `fileId`, `fileName`, `fileSizeBytes`, and `errorMessage`. Treat a nonempty `errorMessage` as failure even on HTTP success. Use [list files](list-files.md) to reconcile the upload; follow continuation links. File sources do not have an indexer to poll. Verify a known-answer retrieval when requested; file metadata alone is not proof of searchable content.

## Rollback or recovery

If the response is lost or times out, list files before retrying to avoid duplicate uploads. Delete only an approved, owned upload by its returned file ID. Replacement in the baseline requires delete and re-upload; do not delete the original local file.

## Error and output contract

Return operation ID, plane, endpoint with secrets removed, resolved API version and selection source, target resource ID/name, status, request/correlation ID, ETag or operation URL, validation result, changed fields, warnings, rollback, and remaining customer action. Surface the service error code/message verbatim but redact credentials and private content.

## Official references

These links describe the catalog's default recipe baseline. For an override, consult documentation for the selected version before execution.

- [Knowledge Sources REST operations](https://learn.microsoft.com/rest/api/searchservice/knowledge-sources?view=rest-searchservice-2026-08-01-preview)
- [Azure REST API specification](https://github.com/Azure/azure-rest-api-specs/tree/main/specification/search)
