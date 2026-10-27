# Create Knowledge Sources

**Operation ID:** `KnowledgeSources_Create`
**Plane:** data
**Safety:** write

## Quick reference

- **Method/path:** `POST /knowledgesources`
- **API version parameter:** `dataApiVersion`
- **Endpoint:** `https://<search-service>.search.windows.net`
- **Preferred interface:** contract-complete Azure MCP operation; fallback `az rest`; use the SDK when generating application code.
- **Minimum role:** Search Service Contributor

## When to use / Do not use

Use only for the single `KnowledgeSources_Create` REST action. Route multi-step customer outcomes to `hero-scenarios/` and failures to `troubleshooting/`.

### Select the source type

Use one of these seven recipes. Ask when the source type is ambiguous, not every time a version differs. Verify the selected version against every kind and the whole KS/KB/retrieve lifecycle under [API version policy](../../../references/api-version-policy.md). Adapt documented contracts without a separate version-approval question; respect explicit pins/GA-only constraints. Do not default ambiguous sources to Blob.

| Source | `kind` | API version | Request-body guide |
|---|---|---|---|
| Existing Azure AI Search index (AZS) | `searchIndex` | `dataApiVersion` | [Search index](../../../references/knowledge-sources/search-index.md) |
| Direct file uploads | `file` | `dataApiVersion` | [File](../../../references/knowledge-sources/file.md) |
| Azure Blob Storage or ADLS Gen2 | `azureBlob` | `dataApiVersion` | [Blob](../../../references/knowledge-sources/azure-blob.md) |
| OneLake lakehouse files | `indexedOneLake` | `dataApiVersion` | [Indexed OneLake](../../../references/knowledge-sources/indexed-onelake.md) |
| SharePoint content copied into a Search index | `indexedSharePoint` | `dataApiVersion` | [Indexed SharePoint](../../../references/knowledge-sources/indexed-sharepoint.md) |
| SharePoint, queried live (no ingestion) | `remoteSharePoint` | `2026-08-01-preview` | [Remote SharePoint](../../../references/knowledge-sources/remote-sharepoint.md) |
| Public web search (Bing Custom Search) | `web` | `2026-04-01` GA or `2026-08-01-preview` | [Web](../../../references/knowledge-sources/web.md) |

Load only the selected guide and this operation's shared contracts. Do not substitute `remoteSharePoint`'s query-time permission model for `indexedSharePoint`'s ingestion-time ACLs, or vice versa. `fabricDataAgent`, `fabricOntology`, `indexedSql`, `mcpServer`, and `workIQ` knowledge-source kinds are outside this release's recipes; explain that boundary instead of silently substituting a different source or claiming unsupported coverage.

## Inputs and context discovery

Reuse `dataApiVersion` already resolved for the current task. If absent, resolve it using [API version policy](../../../references/api-version-policy.md) before any request; this also applies when called directly without a hero scenario. Use that exact value in the request template. Check every dependent kind/KB/retrieve contract and record any documented compatible override; no separate version approval is needed. Check the selected version's request/response contract; never silently change an inherited or explicit version.

Resolve every path placeholder from the active Azure context or the user. Preserve query parameters, request headers, body fields, and resource names exactly. Discover subscription, resource group, service endpoint, current object, ETag, region/tier support, and role assignments before mutation.

## Preconditions and authentication

Acquire a Search token for `https://search.azure.com/.default`. Prefer Microsoft Entra ID and least privilege. Use the resolved `dataApiVersion`; never silently fall back to keys, another tenant, a public endpoint, or another API version.

## Safety or approval gate

Show the desired-state diff and obtain approval before billable, permission, network, production, or data-movement changes.

## Request contract

Build `request.json` from the selected guide, resolving every placeholder. Use exactly one `kind` and its matching parameter object. Omit response-only `createdResources`. Verify the source name is unused; if it exists, compare it and use [create or update](create-or-update.md) only for approved changes.

Replace `<data-api-version>` with the non-empty resolved `dataApiVersion` before executing:
also resolve `<skill-user-agent>` and generate a GUID for `<client-request-id>`.
Apply the shared [CLI quoting](../../../references/http-contract.md#windows-quoting)
for the executing shell, including URLs and quoted `@file` arguments on Windows.

```text
az rest --method post --url "https://<search-service>.search.windows.net/knowledgesources?api-version=<data-api-version>" --resource "https://search.azure.com" --headers "Content-Type=application/json" "User-Agent=<skill-user-agent>" "x-ms-client-request-id=<client-request-id>" --body "@request.json"
```

Use `If-Match` for an update/delete that must not overwrite concurrent changes and `If-None-Match: *` for create-only semantics. Keep request JSON source-controlled and secret-free. For list operations, follow continuation links. For document batches, inspect every item because HTTP 200 can contain partial failures.

## Execution and validation

Execute once, retain status code, request ID, ETag, and long-running-operation headers, and poll only the returned operation/status URL with bounded backoff. Repeat the corresponding GET/list operation and compare the effective state. Treat provisioning, indexer, knowledge-source, and private-link terminal failure states as failure.

Apply the selected guide's readiness checks: wrapping an existing index, uploading files, and synchronizing an external source have different lifecycles. Definition creation alone is not proof that content is retrievable. Report source creation and ingestion verification separately.

## Rollback or recovery

For writes, retain the redacted previous definition and restore it with its ETag. For actions such as reset, resync, run, upgrade, or key rotation, report that rollback is not transactional and provide the documented recovery path. Never recreate a deleted object unless ownership and source-of-truth inputs are verified.

## Error and output contract

Return operation ID, plane, endpoint with secrets removed, resolved API version and selection source, target resource ID/name, status, request/correlation ID, ETag or operation URL, validation result, changed fields, warnings, rollback, and remaining customer action. Surface the service error code/message verbatim but redact credentials and private content.

## Official references

These links describe the catalog's default recipe baseline. For an override, consult documentation for the selected version before execution.

- [Knowledge Sources REST operations](https://learn.microsoft.com/rest/api/searchservice/knowledge-sources?view=rest-searchservice-2026-08-01-preview)
- [Azure REST API specification](https://github.com/Azure/azure-rest-api-specs/tree/main/specification/search)
