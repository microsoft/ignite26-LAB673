# Answer questions over a small set of files

Make a limited set of local manuals, policies or reports available for repeatable
answers with document citations through a File knowledge source and knowledge base.

## When to use / do not use

Use when a customer has a small local file set and needs ongoing, source-backed
answers: "Let our support app answer from these manuals and show where each
answer came from."
A KB provides managed retrieval and can plan questions spanning documents;
prefer it when those capabilities fit instead of building a custom pipeline.
Keep one-off context local; use classic Search for keyword lookup or custom
indexing/ranking. Confirm scale, freshness, visual content and audience before
uploads. Local ACLs are not inherited; differing entitlements require a supported
permission design.

Use the [Blob hero](../agentic-search-blob-knowledge-source/agentic-search-blob-knowledge-source.md)
for cloud-stored documents, recurring synchronization or content exceeding File limits.
Compose the [agent hero](../knowledge-base-foundry-prompt-agent/knowledge-base-foundry-prompt-agent.md)
when creating or extending an assistant, after retrieval works.

## Inputs and discovery

Resolve an approved file allowlist, audience, extraction needs, source/KB names,
Search service, embedding deployment and a question with a known source/fact.
Discover tenant/subscription, region/tier, identity, network posture and existing
KSs/KBs read-only. Ask only for undiscoverable facts and business/data boundaries.

Follow [service selection](../../references/service-provisioning.md) before creation.
Confirm governed reuse; separately approve changes, including new uploads. Inspect
[sources](../../operations/data-plane/knowledge-sources/list.md), their
[definitions](../../operations/data-plane/knowledge-sources/get.md) and
[KBs](../../references/knowledge-base-retrieval.md). Use deterministic new names
only when reuse cannot meet the approved outcome. Never upload a whole directory
or read private contents just to choose defaults.

## API version preflight

Resolve `dataApiVersion` and, for service discovery/setup, `managementApiVersion`
with the [API version policy](../../references/api-version-policy.md).
Pass the resolved values unchanged to every operation; disclose preview use before mutations.
Verify selected-version File upload/list, KB reasoning and reference shapes for
an override; never silently change the version.

The [File contract](../../references/knowledge-sources/file.md) baseline supports
100 files, at most 50 MB each, `minimal` extraction, no images, no indexer and
no ingestion schedule. Check formats, sizes and existing count before upload.
If visual content is essential, stop for an explicitly approved, documented
standard-extraction version or Blob alternative. Never silently discard diagrams
or claim minimal extraction is Content Understanding. Newer limits are not
baseline defaults.

## Plan and approve

Use the [shared RBAC check](../../references/authentication-rbac.md) for caller
Search Service Contributor for KS/KB management and uploads, plus Search Index
Data Reader for retrieval. Verify the Search identity's Cognitive Services User
or existing Foundry User access on the model account for embedding and any KB
planning model. Reuse sufficient inherited access.
Ask before granting missing permissions or provide administrator instructions.
Do not fall back to keys.
Free cannot supply the managed identity this keyless recipe needs; preserve
existing network/authentication settings.

Approve the reuse/new-resource plan, exact files and data movement boundary,
extraction/reasoning, model/retrieval costs, missing grants, ownership and cleanup
before consequential changes. Delegate Storage/model lifecycle to its owners.

## Execute

1. Verify a reused service with [service get](../../operations/search-management/services/get.md).
   For approved setup, use [service create/update](../../operations/search-management/services/create-or-update.md)
   (`Services_CreateOrUpdate`) and wait for successful provisioning.
2. Create only a missing source with [KS create/update](../../operations/data-plane/knowledge-sources/create-or-update.md)
   (`KnowledgeSources_CreateOrUpdate`), `If-None-Match: *`,
   `Prefer: return=representation`, and this body:

```json
{
  "name": "<file-source-name>",
  "kind": "file",
  "fileParameters": {
    "ingestionParameters": {
      "contentExtractionMode": "minimal",
      "embeddingModel": {
        "kind": "azureOpenAI",
        "azureOpenAIParameters": {
          "resourceUri": "<embedding-endpoint>",
          "deploymentId": "<embedding-deployment>",
          "modelName": "<embedding-model>"
        }
      }
    }
  }
}
```

3. Read back `kind`, model/extraction and `fileParameters.createdResources`;
   record created/reused ownership. Creation leaves an empty source. Do not
   edit the generated index.
4. [List files](../../operations/data-plane/knowledge-sources/list-files.md)
   (`KnowledgeSources_ListFiles`) before [upload](../../operations/data-plane/knowledge-sources/upload-file.md)
   (`KnowledgeSources_UploadFile`). Send approved raw bytes with a safe
   `Content-Disposition` filename, Search token and shared HTTP attribution.
   Allow synchronous processing up to 180 seconds in the baseline. Inspect
   returned `fileId`, `fileName`, `fileSizeBytes`, and `errorMessage`;
   nonempty errors fail the step even on HTTP success.
5. Reconcile the allowlist with paginated file-list results and retain IDs,
   sizes/errors and private local fingerprints for resuming. Every POST creates
   another file, even with the same filename. No indexer/status polling is needed
   for File readiness.
6. Use [KB composition and retrieval](../../references/knowledge-base-retrieval.md)
   (`KnowledgeBases_CreateOrUpdate`, `KnowledgeRetrieval_Retrieve`) with
   `kind: file`, required-source errors and references. Use `minimal`/`intents`
   for explicit lookup, or approved `low`/`messages` for decomposition.

## Verify, recover and clean up

Require the known fact, an expected `file` reference/`docName`, matching chunk
reference IDs and no activity errors. Check a multi-hop question only when
selected; do not start tuning.
Return versions, file IDs/errors, generated index, KB/retrieval endpoint, citations,
ownership, cost drivers and blocked/remaining actions.

After timeout/lost response, list and reconcile before retrying. Report ambiguity
and ask about retry/removal of an identified owned duplicate. Baseline replacement
requires approved [file delete](../../operations/data-plane/knowledge-sources/delete-file.md)
by `fileId` then upload. Never delete originals or unrelated uploads. Diagnose
format/size, capacity, model access and retrieval without inventing a new pipeline.

On requested teardown, follow [scenario cleanup](../../references/safety-and-idempotency.md#scenario-cleanup):
remove owned agent bindings first, delete owned KBs, preserve sources referenced
by retained KBs, then [delete the owned KS](../../operations/data-plane/knowledge-sources/delete.md).
KS deletion removes uploads/generated index; do not pre-delete the index.
For uploads into a reused KS, retain that KS/KB and delete only owned file IDs
after approving impacts on retained consumers. Verify absence and retained
resources. Reused assets and local originals are not deletion targets.

**Official source:** [File sources, synchronous uploads and version-specific limits](https://learn.microsoft.com/azure/search/agentic-knowledge-source-how-to-file).
