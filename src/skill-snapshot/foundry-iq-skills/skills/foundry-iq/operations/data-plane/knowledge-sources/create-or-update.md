# Create Or Update Knowledge Sources

**Operation ID:** `KnowledgeSources_CreateOrUpdate`
**Plane:** data
**Safety:** write

## Quick reference

- **Method/path:** `PUT /knowledgesources('{sourceName}')`
- **API version parameter:** `dataApiVersion`
- **Endpoint:** `https://<search-service>.search.windows.net`
- **Preferred interface:** contract-complete Azure MCP operation; fallback `az rest`; use the SDK when generating application code.
- **Minimum role:** Search Service Contributor

## When to use / Do not use

Use only for the single `KnowledgeSources_CreateOrUpdate` REST action. Route multi-step customer outcomes to `hero-scenarios/` and failures to `troubleshooting/`.

Before building the body, [select the source type](create.md#select-the-source-type) and load its guide: Search index (AZS), File, Blob, indexed OneLake, indexed SharePoint, remote SharePoint, or Web. Verify compatibility across all sources/KB/retrieve, not just the URL date. Do not default an ambiguous source to Blob.

## Inputs and context discovery

Reuse `dataApiVersion` already resolved for the current task. If absent, resolve it using [API version policy](../../../references/api-version-policy.md) before any request; this also applies when called directly without a hero scenario. Use that exact value in the request template. Check every dependent kind/KB/retrieve contract and record any documented compatible override; no separate version approval is needed. Check the selected version's request/response contract; never silently change an inherited or explicit version.

Resolve every path placeholder from the active Azure context or the user. Preserve query parameters, request headers, body fields, and resource names exactly. Discover subscription, resource group, service endpoint, current object, ETag, region/tier support, and role assignments before mutation.

## Preconditions and authentication

Acquire a Search token for `https://search.azure.com/.default`. Prefer Microsoft Entra ID and least privilege. Use the resolved `dataApiVersion`; never silently fall back to keys, another tenant, a public endpoint, or another API version.

## Safety or approval gate

Show the desired-state diff and obtain approval before billable, permission, network, production, or data-movement changes.

## Request contract

Build `request.json` from the selected type guide. Match the body `name` to `sourceName` and use only that kind's parameter object; omit response-only `createdResources`. Read an existing definition and ETag before updating. Preserve fields outside the approved change, including ingestion settings, identity, and permission options. Do not change an existing source's `kind` in place; stop and plan a separately named source and dependent knowledge-base migration.

Replace `<data-api-version>` with the non-empty resolved `dataApiVersion` before executing:
also resolve `<skill-user-agent>` and generate a GUID for `<client-request-id>`.
Apply the shared [CLI quoting](../../../references/http-contract.md#windows-quoting)
for the executing shell, including URLs and quoted `@file` arguments on Windows.

```text
az rest --method put --url "https://<search-service>.search.windows.net/knowledgesources('{sourceName}')?api-version=<data-api-version>" --resource "https://search.azure.com" --headers "Content-Type=application/json" "User-Agent=<skill-user-agent>" "x-ms-client-request-id=<client-request-id>" --body "@request.json"
```

Use `If-Match` for an update/delete that must not overwrite concurrent changes and `If-None-Match: *` for create-only semantics. Keep request JSON source-controlled and secret-free. For list operations, follow continuation links. For document batches, inspect every item because HTTP 200 can contain partial failures.

## Execution and validation

Execute once, retain status code, request ID, ETag, and long-running-operation headers, and poll only the returned operation/status URL with bounded backoff. Repeat the corresponding GET/list operation and compare the effective state. Treat provisioning, indexer, knowledge-source, and private-link terminal failure states as failure.

Apply the selected guide's readiness checks. Report source creation/update and ingestion verification separately; an HTTP success is not proof that the intended content is retrievable.

## Rollback or recovery

For writes, retain the redacted previous definition and restore it with its ETag. For actions such as reset, resync, run, upgrade, or key rotation, report that rollback is not transactional and provide the documented recovery path. Never recreate a deleted object unless ownership and source-of-truth inputs are verified.

## Error and output contract

Return operation ID, plane, endpoint with secrets removed, resolved API version and selection source, target resource ID/name, status, request/correlation ID, ETag or operation URL, validation result, changed fields, warnings, rollback, and remaining customer action. Surface the service error code/message verbatim but redact credentials and private content.

## Official references

These links describe the catalog's default recipe baseline. For an override, consult documentation for the selected version before execution.

- [Knowledge Sources REST operations](https://learn.microsoft.com/rest/api/searchservice/knowledge-sources?view=rest-searchservice-2026-08-01-preview)
- [Azure REST API specification](https://github.com/Azure/azure-rest-api-specs/tree/main/specification/search)
