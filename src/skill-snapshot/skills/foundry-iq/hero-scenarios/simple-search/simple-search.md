# Simple Search

Deliver a working keyword search from a clean subscription or reuse a compatible service.

## Inputs

Resolve subscription, resource group, service/index names, and cleanup ownership. Follow [service provisioning](../../references/service-provisioning.md) before API version resolution: reuse a compatible service or recommend Free for an eligible tiny tutorial, serverless for qualifying intermittent development, or a suitable dedicated tier. Ask only for missing requirements and obtain approval for the selected plan.

## API version preflight

Before the first request, follow the [API version policy](../../references/api-version-policy.md) to reuse or resolve `managementApiVersion` and `dataApiVersion` for the current task. Verify service provisioning, index definitions, document indexing, and keyword search against the selected contracts. Pass the resolved values unchanged to every operation; do not let an operation independently choose another default. The payloads below describe the catalog's default data-plane recipe; validate any override before execution.

## Execute

1. Inspect a reused service with [service get](../../operations/search-management/services/get.md) (`Services_Get`). Run [service create/update](../../operations/search-management/services/create-or-update.md) (`Services_CreateOrUpdate`) only for a new service or approved changes, and wait for `provisioningState: succeeded`.
2. Check the operator's catalog-required data-plane permissions using the [shared RBAC check](../../references/authentication-rbac.md). Reuse existing access; ask before granting missing permissions or provide administrator instructions.
3. Run [index create/update](../../operations/data-plane/indexes/create-or-update.md) (`Indexes_CreateOrUpdate`) with:

```json
{"name":"demo-index","fields":[
  {"name":"id","type":"Edm.String","key":true,"filterable":true},
  {"name":"title","type":"Edm.String","searchable":true},
  {"name":"content","type":"Edm.String","searchable":true}
]}
```

4. Run [document indexing](../../operations/data-plane/documents/index.md) (`Documents_Index`) with three known-answer records and `@search.action: "mergeOrUpload"`.
5. Run [search](../../operations/data-plane/documents/search-post.md) (`Documents_SearchPost`) using `dataApiVersion`:

```json
{"search":"fourteen days","select":"id,title,content","top":3}
```

## Verify and clean up

Require every batch item to succeed and the expected fixture key/text in results. Rerun PUT and merge-or-upload to prove convergence. Return resolved API versions and selection sources, elapsed stages, resources, request IDs, cost drivers, rollback, and cleanup; never delete a reused resource.

On a teardown request, follow [scenario cleanup](../../references/safety-and-idempotency.md#scenario-cleanup): delete the owned index before the service, preserving any reused resources.
