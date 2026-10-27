# Answer questions over cloud-stored documents

Provide current, cited answers from documents already in cloud storage without
hand-building an ingestion pipeline.

## When to use / do not use

Use when a customer's contracts, manuals or policies live in cloud storage and
their app needs current answers with citations: "Answer from our contracts and
keep up with new documents." Discover the storage type and approved scope.
A KB manages ingestion/retrieval and can plan across documents; prefer it for
those needs, classic Search for keyword lookup or custom indexing/ranking.
Confirm freshness, visual content and audience before writes.
Use the [File hero](../agentic-search-file-knowledge-source/agentic-search-file-knowledge-source.md)
for a small local file set. Failure diagnosis and quality tuning are separate routes.

## Inputs and access

Reuse a compatible existing Search service unless isolation is requested.
Follow [service provisioning](../../references/service-provisioning.md) before
version resolution; approve the selected plan and reuse a compatible service.
Free cannot support this managed-identity recipe. Consider serverless only when
region, source support, capacity and network limits fit.
Resolve storage ID, container/prefix, formats, extraction/freshness needs,
Search service, embedding/chat deployments, known question/fact and ownership.
Set `isADLSGen2` from hierarchical namespace. Empty/omitted prefixes need
whole-container approval; never widen a supplied prefix.

List/get permitted [sources](../../operations/data-plane/knowledge-sources/list.md)
and [KBs](../../operations/data-plane/knowledge-bases/list.md) read-only.
Confirm suitable governed reuse; leave reused assets unchanged. Compare corpus
scope, freshness, extraction/model and audience, not just names.
Delegate Storage/model lifecycle to its owners.

Use the [shared RBAC check](../../references/authentication-rbac.md) for caller
Search Service Contributor and Search Index Data Contributor to create the
pipeline, plus Search Index Data Reader for retrieval. The Search identity needs
Storage Blob Data Reader on supported storage scope, plus Cognitive Services User
or existing Foundry User on model accounts. Ask before granting missing permissions or provide administrator instructions.
Preserve network boundaries; check reachability from ingestion.

Approve generated resources, exact data movement, extraction/model/retrieval
costs, schedule, missing grants, network changes and ownership together.
For document-level permissions, verify ingestion metadata and per-user query
enforcement; service/project identity does not prove end-user entitlement.

## API version preflight

Follow [API version policy](../../references/api-version-policy.md) to resolve
`managementApiVersion` and `dataApiVersion` before the first request.
Pass the resolved values unchanged to every operation.
Recipes target the catalog preview baseline,
including Blob ingestion, model configuration and `retrievalReasoningEffort: low`
when planning is selected. Verify payloads, limits, readiness and citation shapes
for overrides.
Do not remove required settings or upgrade silently. Disclose preview use before mutations;
stop and discuss alternatives if the selected version cannot support the workload.

## Execute

1. Inspect [service get](../../operations/search-management/services/get.md) (`Services_Get`) for readiness, identity and access. Use [service create/update](../../operations/search-management/services/create-or-update.md) (`Services_CreateOrUpdate`) only for a new service or approved changes; wait for `provisioningState: succeeded`.
2. Reuse an unchanged compatible source, or run [KS create/update](../../operations/data-plane/knowledge-sources/create-or-update.md) (`KnowledgeSources_CreateOrUpdate`) with `dataApiVersion`, `If-None-Match: *` for creation and `Prefer: return=representation`. Approved updates preserve settings and use current ETags. This keyless text-only body disables image verbalization and does not require an ingestion chat model:

```json
{"name":"<blob-source-name>","kind":"azureBlob","azureBlobParameters":{
  "connectionString":"ResourceId=<storage-resource-id>;",
  "containerName":"<container>","folderPath":"<prefix>","isADLSGen2":false,
  "ingestionParameters":{"identity":null,"contentExtractionMode":"minimal","disableImageVerbalization":true,
    "embeddingModel":{"kind":"azureOpenAI","azureOpenAIParameters":{"resourceUri":"<model-endpoint>","deploymentId":"<embedding-deployment>","modelName":"<embedding-model>"}}}}}
```

`ResourceId` is nonsecret. `connectionString` is an API field, not a key/SAS
credential.

   If visuals/layout matter, stop before this text-only PUT. Use the
   [Blob source contract](../../references/knowledge-sources/azure-blob.md) and
   selected-version documentation to approve a supported richer extraction
   recipe and its chat/AI Services dependencies.
3. Read back scope/model/extraction and `azureBlobParameters.createdResources`
   (data source, skillset, indexer, index).
4. Poll [source status](../../operations/data-plane/knowledge-sources/get-status.md)
   (`KnowledgeSources_GetStatus`) with bounded backoff and an agreed deadline.
   Require a relevant completed synchronization (`lastSynchronizationState.endTime`),
   zero `itemsUpdatesFailed` and processed items (`itemsUpdatesProcessed`) for a
   new nonempty corpus. Check the run covers the intended upload/change.
   For unchanged reuse, verify freshness and existing
   content instead of demanding new processed items. Return timeout/errors and
   counts explicitly; do not create the KB or claim readiness after partial ingestion.
5. Use [KB composition and cited retrieval](../../references/knowledge-base-retrieval.md)
   (`KnowledgeBases_CreateOrUpdate`, `KnowledgeRetrieval_Retrieve`) with
   `kind: azureBlob`, required-source errors and references. Select
   `minimal`/`intents` for explicit lookup or approved `low`/`messages` for planning.

## Verify and clean up

Require the known fact, matching original Blob reference, correct source activity
and no errors. Do not equate HTTP success with supported citations or demand no
ranked results for every unrelated semantic query. Re-running the workflow must
read/reconcile and reuse unchanged resources, not restart ingestion by replaying PUTs.
Return versions/assets/scopes, completed-run counts, citations, costs, ownership,
rollback and remaining actions; never delete a reused resource.

For failures, inspect the generated indexer's diagnostics, source/model RBAC,
network, parsing and prefix/freshness. Repair only approved affected resources;
no full reset, broader prefix, key fallback or parallel pipeline as a shortcut.
If the request includes a new or existing Foundry prompt agent, compose the
[agent hero](../knowledge-base-foundry-prompt-agent/knowledge-base-foundry-prompt-agent.md)
after direct retrieval passes, reusing this KB.

On a teardown request, follow [scenario cleanup](../../references/safety-and-idempotency.md#scenario-cleanup): delete the owned [KB](../../operations/data-plane/knowledge-bases/delete.md) before its [KS](../../operations/data-plane/knowledge-sources/delete.md). Let KS deletion remove generated assets; do not pre-delete the index. Preserve sources referenced by retained KBs.

Remove owned agent bindings before KB deletion, preserve reused Storage/models,
and never delete source blobs. Verify generated-asset absence and retained resources.

**Official source:** [Blob ingestion, extraction and synchronization](https://learn.microsoft.com/azure/search/agentic-knowledge-source-how-to-blob).
