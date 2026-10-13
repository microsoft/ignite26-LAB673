# Create Or Update Services

**Operation ID:** `Services_CreateOrUpdate`
**Plane:** management
**Safety:** write

## Quick reference

- **Method/path:** `PUT /subscriptions/{subscriptionId}/resourceGroups/{resourceGroupName}/providers/Microsoft.Search/searchServices/{searchServiceName}`
- **API version parameter:** `managementApiVersion`
- **Endpoint:** `https://management.azure.com`
- **Preferred interface:** contract-complete Azure MCP operation; fallback `az rest`; use the SDK when generating application code.
- **Minimum role:** Search Service Contributor; key operations require Contributor or Owner

## When to use / Do not use

Use only for the single `Services_CreateOrUpdate` REST action. Route multi-step customer outcomes to `hero-scenarios/` and failures to `troubleshooting/`.

## Inputs and context discovery

Reuse `managementApiVersion` already resolved for the current task. If absent, resolve it using [API version policy](../../../references/api-version-policy.md) before any request; this also applies when called directly without a hero scenario. Set `$managementApiVersion` to that exact value in the same PowerShell invocation as the request. Check the selected version's request/response contract; never silently change an inherited or explicit version.

Resolve every path placeholder from the active Azure context or the user. Preserve query parameters, request headers, body fields, and resource names exactly. Discover subscription, resource group, service endpoint, current object, ETag, region/tier support, and role assignments before mutation.

Before choosing a region, SKU, or capacity, follow [service provisioning](../../../references/service-provisioning.md). Reuse a compatible service and an already approved selection; ask only for missing requirements. This policy distinguishes dedicated, Free, and serverless, including the serverless management-version requirement.

For an existing service, GET its current definition first and preserve settings outside the approved diff. Do not apply new-service defaults to it. Prefer [partial update](update.md) for supported property changes; do not attempt an in-place dedicated/serverless conversion.

## Preconditions and authentication

Acquire an Azure Resource Manager token for `https://management.azure.com/.default`. Prefer Microsoft Entra ID and least privilege. Use the resolved `managementApiVersion`; never silently fall back to keys, another tenant, a public endpoint, or another API version.

## Safety or approval gate

Show the desired-state diff and obtain approval before billable, permission, network, production, or data-movement changes.

Recommend the setup with its estimated cost and important availability limits, then ask permission to create it. Include the proposed authentication and network defaults in that approval rather than asking separate technical questions. Preserve project/network policy and verify a usable private connection when required; never relax an existing network boundary.

## Request contract

`@request.json` tells Azure CLI to read the body from a local file; it is not a bundled template. Create that file from the approved selection and the resolved `managementApiVersion` contract before invoking the command.

Set `location`, `sku.name`, and `properties.hostingMode: "Default"`. For dedicated services, set the approved `properties.replicaCount` and `properties.partitionCount`; one of each is a development starting point, not a production SLA configuration. For serverless, use `sku.name: "serverless"` and omit replica and partition counts; follow the [serverless API contract](../../../references/service-provisioning.md#serverless-api-contract). Do not send this body to an unverified catalog or inherited version, use `developer` as the SKU, or set `computeType` to serverless.

For new services, prefer `properties.disableLocalAuth: true` without `authOptions`. Follow the [shared RBAC check](../../../references/authentication-rbac.md) to reuse a compatible managed identity and existing access; use `identity.type: "SystemAssigned"` only when a new identity is needed. Set `properties.publicNetworkAccess` and any network rules from the approved plan. For Free, omit identity, replica, and partition settings. Identity creation does not grant source/model access; include only missing grants in the approval.

```powershell
if ([string]::IsNullOrWhiteSpace($managementApiVersion)) { throw "Resolve managementApiVersion using the shared API version policy before this request." }
az rest --method put --url "https://management.azure.com/subscriptions/{subscriptionId}/resourceGroups/{resourceGroupName}/providers/Microsoft.Search/searchServices/{searchServiceName}?api-version=$managementApiVersion" --headers "Content-Type=application/json" --body "@request.json"
```

Use `If-Match` for an update/delete that must not overwrite concurrent changes and `If-None-Match: *` for create-only semantics. Keep request JSON source-controlled and secret-free. For list operations, follow continuation links. For document batches, inspect every item because HTTP 200 can contain partial failures.

## Execution and validation

Execute once, retain status code, request ID, ETag, and long-running-operation headers, and poll only the returned operation/status URL with bounded backoff. Repeat the corresponding GET/list operation and compare the effective state. Treat provisioning, indexer, knowledge-source, and private-link terminal failure states as failure.

Wait for `provisioningState: succeeded`; fail on terminal failure/cancellation or a bounded timeout. Verify the effective location, SKU, identity, authentication, and network configuration, plus dedicated capacity when applicable. Record created/reused ownership before running the scenario's workload validation. Quota or capacity failure is not permission to choose another region or tier.

## Rollback or recovery

For writes, retain the redacted previous definition and restore it with its ETag. For actions such as reset, resync, run, upgrade, or key rotation, report that rollback is not transactional and provide the documented recovery path. Never recreate a deleted object unless ownership and source-of-truth inputs are verified.

## Error and output contract

Return operation ID, plane, endpoint with secrets removed, resolved API version and selection source, target resource ID/name, status, request/correlation ID, ETag or operation URL, validation result, changed fields, warnings, rollback, and remaining customer action. Surface the service error code/message verbatim but redact credentials and private content.

## Official references

These links describe the catalog's default recipe baseline. For an override, consult documentation for the selected version before execution.

- [Services REST operations](https://learn.microsoft.com/rest/api/searchmanagement/services?view=rest-searchmanagement-2025-05-01)
- [Azure REST API specification](https://github.com/Azure/azure-rest-api-specs/tree/main/specification/search)
