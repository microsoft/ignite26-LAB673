# Agentic Search with Blob Knowledge Source

Create a Blob-backed knowledge source and knowledge base, then retrieve a cited known answer. Start with a new Search service or reuse a compatible service.

## Inputs and access

Reuse a compatible existing Search service unless isolation is requested. Follow [service provisioning](../../references/service-provisioning.md) before API version resolution; ask only for missing requirements and approve the selected plan. Free cannot support this managed-identity ingestion recipe. Consider serverless only when its region, size, and outbound-network limits fit. Resolve an approved container/prefix, Search service, embedding/chat deployments, and cleanup ownership. Delegate Storage/model lifecycle to their owning skills. Use the [shared RBAC check](../../references/authentication-rbac.md) for caller access and the Search managed identity's `Storage Blob Data Reader` access on the approved storage scope and `Cognitive Services User` access on the model resource. Ask before granting missing permissions or provide administrator instructions.

## API version preflight

Before the first request, follow the [API version policy](../../references/api-version-policy.md) to reuse or resolve `managementApiVersion` and `dataApiVersion` for the current task. Pass the resolved values unchanged to every operation; do not let an operation independently choose another default. The payloads below describe the catalog's default preview recipe, including Blob ingestion, model configuration, and `retrievalReasoningEffort: low`. Verify all of these capabilities and the retrieval response/citation contract for an override before execution. Do not assume GA or a newer preview supports the same payloads, silently remove reasoning/model settings, or upgrade mid-workflow. Disclose preview use before mutations; stop and discuss an alternative if the requested version cannot support this scenario.

## Execute

1. Inspect an existing service with [service get](../../operations/search-management/services/get.md) (`Services_Get`) and verify region/tier support, identity, and access for this scenario. Reuse it if compatible. Run [service create/update](../../operations/search-management/services/create-or-update.md) (`Services_CreateOrUpdate`) only for a new service or approved changes, and wait for `provisioningState: succeeded`.
2. Run [knowledge-source create/update](../../operations/data-plane/knowledge-sources/create-or-update.md) (`KnowledgeSources_CreateOrUpdate`) using `dataApiVersion`:

```json
{"name":"blob-source","kind":"azureBlob","azureBlobParameters":{
  "connectionString":"ResourceId=<storage-resource-id>;",
  "containerName":"<container>","folderPath":"<prefix>","isADLSGen2":false,
  "ingestionParameters":{"identity":null,"contentExtractionMode":"minimal",
    "embeddingModel":{"kind":"azureOpenAI","azureOpenAIParameters":{"resourceUri":"<model-endpoint>","deploymentId":"<embedding-deployment>","modelName":"<embedding-model>"}},
    "chatCompletionModel":{"kind":"azureOpenAI","azureOpenAIParameters":{"resourceUri":"<model-endpoint>","deploymentId":"<chat-deployment>","modelName":"<chat-model>"}}}}}
```

3. Poll [source status](../../operations/data-plane/knowledge-sources/get-status.md) (`KnowledgeSources_GetStatus`) to `active` with zero failed items.
4. Run [knowledge-base create/update](../../operations/data-plane/knowledge-bases/create-or-update.md) (`KnowledgeBases_CreateOrUpdate`):

```json
{"name":"blob-kb","knowledgeSources":[{"name":"blob-source"}],
 "models":[{"kind":"azureOpenAI","azureOpenAIParameters":{"resourceUri":"<model-endpoint>","deploymentId":"<chat-deployment>","modelName":"<chat-model>"}}],
 "retrievalReasoningEffort":{"kind":"low"},"outputMode":"extractiveData"}
```

5. Run [retrieve](../../operations/data-plane/knowledge-retrieval/retrieve.md) (`KnowledgeRetrieval_Retrieve`) with a known-answer question, references enabled, and source errors configured to fail.

## Verify and clean up

Require the known document, original Blob citation, and no result for an unrelated query. Rerun PUTs for idempotency. Return resolved API versions and selection sources, generated assets, role scopes, status history, citation, cost drivers, rollback, and ownership-scoped cleanup; never delete a reused resource.

On a teardown request, follow [scenario cleanup](../../references/safety-and-idempotency.md#scenario-cleanup): delete the owned [KB](../../operations/data-plane/knowledge-bases/delete.md) before its [KS](../../operations/data-plane/knowledge-sources/delete.md). Let KS deletion remove generated assets; do not pre-delete the index. Preserve sources referenced by retained KBs.
