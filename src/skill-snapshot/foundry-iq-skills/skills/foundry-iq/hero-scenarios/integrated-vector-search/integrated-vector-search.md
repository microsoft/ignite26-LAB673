# Integrated Vector Search

Build integrated vectorization and prove hybrid semantic search against known content.

## Inputs and preflight

Resolve Search, Blob, and Azure OpenAI resources. Verify embedding dimensions, region/tier support, and Search/vector/model quota. Use the [shared RBAC check](../../references/authentication-rbac.md) for caller access and the Search managed identity's `Storage Blob Data Reader` access on the approved storage scope and `Cognitive Services OpenAI User` access on the Azure OpenAI resource. Ask before granting missing permissions or provide administrator instructions.

Follow [service provisioning](../../references/service-provisioning.md) before API version resolution. Reuse a compatible Search service; otherwise approve a new-service plan and run [service create/update](../../operations/search-management/services/create-or-update.md) (`Services_CreateOrUpdate`) after resolving the versions below. Wait for `provisioningState: succeeded` before ingestion. This managed-identity recipe excludes Free; private outbound skillset execution requires a suitable dedicated tier, not serverless.

## API version preflight

Before the first request, follow the [API version policy](../../references/api-version-policy.md) to reuse or resolve `dataApiVersion` for the current task. Resolve `managementApiVersion` only if Search management operations are needed. Verify integrated vectorization, skillset projections, vectorizer configuration, and hybrid semantic queries against the selected contract. Pass the resolved values unchanged to every operation; do not let an operation independently choose another default. The payloads below describe the catalog's default data-plane recipe; validate any override before execution. Search API versions do not select Blob or Azure OpenAI API versions.

## Execute

1. Run [data-source create/update](../../operations/data-plane/data-sources/create-or-update.md) (`DataSources_CreateOrUpdate`) with `ResourceId=<storage-resource-id>;` and the approved container/prefix.
2. Run [index create/update](../../operations/data-plane/indexes/create-or-update.md) (`Indexes_CreateOrUpdate`). Include a key, searchable text, a `Collection(Edm.Single)` vector field whose `dimensions` match the model, HNSW algorithm/profile, Azure OpenAI vectorizer, and semantic configuration.
3. Run [skillset create/update](../../operations/data-plane/skillsets/create-or-update.md) (`Skillsets_CreateOrUpdate`). Add Text Split and `AzureOpenAIEmbeddingSkill`, then project chunks into the target index while preserving a filterable parent key.
4. Run [indexer create/update](../../operations/data-plane/indexers/create-or-update.md) (`Indexers_CreateOrUpdate`), [run](../../operations/data-plane/indexers/run.md), and poll [status](../../operations/data-plane/indexers/get-status.md) (`Indexers_GetStatus`) to terminal success.
5. Run [hybrid search](../../operations/data-plane/documents/search-post.md) (`Documents_SearchPost`):

```json
{"search":"fourteen day airfare rule","queryType":"semantic",
 "semanticConfiguration":"semantic-default",
 "vectorQueries":[{"kind":"text","text":"fourteen day airfare rule","fields":"contentVector","k":5}],
 "select":"id,title,content","top":5}
```

## Verify and clean up

Require zero indexer failures, the expected key/content, and nonempty search and reranker scores. Rerun the indexer after no source change. Return resolved API versions and selection sources, model/dimensions, assets, indexing counts, query evidence, request IDs, cost drivers, rollback, and cleanup.

On a teardown request, follow [scenario cleanup](../../references/safety-and-idempotency.md#scenario-cleanup): delete the owned indexer before its skillset, data source, and index; never delete a reused resource.
