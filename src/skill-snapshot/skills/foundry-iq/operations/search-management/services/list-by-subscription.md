# List By Subscription Services

**Operation ID:** `Services_ListBySubscription`
**Plane:** management
**Safety:** read

## Quick reference

- **Method/path:** `GET /subscriptions/{subscriptionId}/providers/Microsoft.Search/searchServices`
- **API version parameter:** `managementApiVersion`
- **Endpoint:** `https://management.azure.com`
- **Preferred interface:** contract-complete Azure MCP operation; fallback `az rest`; use the SDK when generating application code.
- **Minimum role:** Reader

## When to use / Do not use

Use only for the single `Services_ListBySubscription` REST action. Route multi-step customer outcomes to `hero-scenarios/` and failures to `troubleshooting/`.

## Inputs and context discovery

Reuse `managementApiVersion` already resolved for the current task. If absent, resolve it using [API version policy](../../../references/api-version-policy.md) before any request; this also applies when called directly without a hero scenario. Set `$managementApiVersion` to that exact value in the same PowerShell invocation as the request. Check the selected version's request/response contract; never silently change an inherited or explicit version.

Resolve every path placeholder from the active Azure context or the user. Preserve query parameters, request headers, body fields, and resource names exactly. Discover subscription, resource group, service endpoint, current object, ETag, region/tier support, and role assignments before mutation.

## Preconditions and authentication

Acquire an Azure Resource Manager token for `https://management.azure.com/.default`. Prefer Microsoft Entra ID and least privilege. Use the resolved `managementApiVersion`; never silently fall back to keys, another tenant, a public endpoint, or another API version.

## Safety or approval gate

No mutation approval is needed. Do not broaden access to make the read succeed.

## Request contract

```powershell
if ([string]::IsNullOrWhiteSpace($managementApiVersion)) { throw "Resolve managementApiVersion using the shared API version policy before this request." }
az rest --method get --url "https://management.azure.com/subscriptions/{subscriptionId}/providers/Microsoft.Search/searchServices?api-version=$managementApiVersion"
```

Use `If-Match` for an update/delete that must not overwrite concurrent changes and `If-None-Match: *` for create-only semantics. Keep request JSON source-controlled and secret-free. For list operations, follow continuation links. For document batches, inspect every item because HTTP 200 can contain partial failures.

## Execution and validation

Execute once, retain status code, request ID, ETag, and long-running-operation headers, and poll only the returned operation/status URL with bounded backoff. Validate status, shape, paging, and the requested identifier without printing secrets. Treat provisioning, indexer, knowledge-source, and private-link terminal failure states as failure.

## Rollback or recovery

For writes, retain the redacted previous definition and restore it with its ETag. For actions such as reset, resync, run, upgrade, or key rotation, report that rollback is not transactional and provide the documented recovery path. Never recreate a deleted object unless ownership and source-of-truth inputs are verified.

## Error and output contract

Return operation ID, plane, endpoint with secrets removed, resolved API version and selection source, target resource ID/name, status, request/correlation ID, ETag or operation URL, validation result, changed fields, warnings, rollback, and remaining customer action. Surface the service error code/message verbatim but redact credentials and private content.

## Official references

These links describe the catalog's default recipe baseline. For an override, consult documentation for the selected version before execution.

- [Services REST operations](https://learn.microsoft.com/rest/api/searchmanagement/services?view=rest-searchmanagement-2025-05-01)
- [Azure REST API specification](https://github.com/Azure/azure-rest-api-specs/tree/main/specification/search)
