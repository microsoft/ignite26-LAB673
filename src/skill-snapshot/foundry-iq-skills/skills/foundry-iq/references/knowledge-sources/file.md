# Create Or Update File Knowledge Sources

## Quick reference

- **Kind:** `file` (direct file upload).
- **Operations:** [create](../../operations/data-plane/knowledge-sources/create.md) or [create/update](../../operations/data-plane/knowledge-sources/create-or-update.md).
- **API version:** `dataApiVersion`; inherit the operation's shared contracts.

## When to use / Do not use

Use for small approved uploads; use [Blob](azure-blob.md) for containers or scheduled ingestion. A File source creates an index, not an indexer or ingestion schedule.

## Inputs and context discovery

Reuse or resolve `dataApiVersion` with the [API version policy](../api-version-policy.md). This is a catalog-baseline payload; verify the selected version and never silently change it.

Resolve source name, approved files/formats/sizes, and embedding endpoint/deployment/model. The baseline permits 100 files of at most 50 MB each, with `minimal` extraction and no images. Verify selected-version limits before upload.

## Preconditions and authentication

Use a Search-audience Entra token and Search Service Contributor. The Search identity needs Cognitive Services User or existing Foundry User on the model account. Retrieval needs Search Index Data Reader or Contributor.

## Safety or approval gate

Approve upload, processing cost, and identity/permission changes. Confirm the data boundary before reading private files; do not upload whole directories by default.

## Request contract

```json
{
  "name": "<source-name>",
  "kind": "file",
  "fileParameters": {
    "ingestionParameters": {
      "contentExtractionMode": "minimal",
      "embeddingModel": {
        "kind": "azureOpenAI",
        "azureOpenAIParameters": {
          "resourceUri": "<model-endpoint>",
          "deploymentId": "<embedding-deployment>",
          "modelName": "<embedding-model>"
        }
      }
    }
  }
}
```

Include `fileParameters.ingestionParameters`, not `networkAccessMode`, a schedule, storage credentials, or file bytes. The baseline does not support File `standard` extraction; stop rather than changing versions or extraction silently.

## Execution and validation

Read the definition with [get](../../operations/data-plane/knowledge-sources/get.md); record `createdResources` and created/reused ownership. Creation leaves the source empty. [Upload](../../operations/data-plane/knowledge-sources/upload-file.md) approved raw binary with `Content-Disposition`, not JSON. Retain each `fileId`/ownership and fail on `errorMessage`; [list files](../../operations/data-plane/knowledge-sources/list-files.md) to reconcile names/counts. Do not poll an indexer. Verify requested retrieval through an approved KB with a known answer and file reference; metadata alone is insufficient.

## Rollback or recovery

List files before retrying uncertain uploads. For single-file removal/replacement, [delete the file](../../operations/data-plane/knowledge-sources/delete-file.md) by approved `fileId`, then re-upload only for replacement. Verify its absence from the file list; keep the KS, KBs, and other uploads.

For whole-source teardown, follow [scenario cleanup](../safety-and-idempotency.md#scenario-cleanup) and reuse scoped authorization. Delete owned KBs before [KS deletion](../../operations/data-plane/knowledge-sources/delete.md); preserve sources referenced by retained KBs. KS deletion removes uploaded content and the generated index; do not pre-delete the index or enumerate files for deletion. Verify GET/404 for the KS and recorded index. Never delete a reused KS or local originals.

## Error and output contract

Return the selected operation's output plus kind, generated index, per-file IDs/errors, validation result, and remaining action. Do not print private file contents or tokens.

## Official references

- [File knowledge sources and version-specific limits](https://learn.microsoft.com/azure/search/agentic-knowledge-source-how-to-file)
