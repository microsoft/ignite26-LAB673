# Create Or Update Indexed OneLake Knowledge Sources

## Quick reference

- **Kind:** `indexedOneLake` (lakehouse files).
- **Operations:** [create](../../operations/data-plane/knowledge-sources/create.md) or [create/update](../../operations/data-plane/knowledge-sources/create-or-update.md).
- **API version:** `dataApiVersion`; inherit the operation's shared contracts.

## When to use / Do not use

Ingest a Fabric lakehouse's Files area, not its Tables area, SQL queries, or a Fabric Data Agent.

## Inputs and context discovery

Reuse or resolve `dataApiVersion` with the [API version policy](../api-version-policy.md). This is a catalog-baseline payload; verify the selected version and never silently change it.

Resolve workspace/lakehouse IDs, approved folder/shortcut, identity, and embedding deployment. Parquet and My Workspace are unsupported. Verify formats/shortcuts; omitting `targetPath` needs whole-lakehouse approval.

## Preconditions and authentication

Use a Search-audience Entra token with caller Search Service Contributor and Search Index Data Contributor roles. Require the same Search/Fabric tenant, Search identity's Fabric workspace Contributor role (not Azure subscription Contributor), external OneLake access, and Cognitive Services User on the model. Private synchronization is unsupported; stop on private-only requirements.

## Safety or approval gate

Obtain approval for data movement, generated resources, model costs, and permission changes. If source permissions must be preserved, verify supported permission ingestion and query-time enforcement before proceeding.

## Request contract

```json
{
  "name": "<source-name>",
  "kind": "indexedOneLake",
  "indexedOneLakeParameters": {
    "fabricWorkspaceId": "<workspace-id>",
    "lakehouseId": "<lakehouse-id>",
    "targetPath": "<approved-folder-or-shortcut>",
    "ingestionParameters": {
      "identity": null,
      "contentExtractionMode": "minimal",
      "disableImageVerbalization": true,
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

Use bare workspace/lakehouse IDs. This text-only recipe uses system-assigned identity; verify user-assigned identity, schedules, or richer extraction before changing it.

## Execution and validation

Read the source with [get](../../operations/data-plane/knowledge-sources/get.md); compare IDs/path and record `createdResources` and created/reused ownership. Poll [source status](../../operations/data-plane/knowledge-sources/get-status.md) with bounded backoff. Require completed synchronization, zero failed items, and expected folder content; `active` alone is insufficient. Verify requested retrieval through an approved KB with a known answer and lakehouse reference.

## Rollback or recovery

Use ETags for restoration. For teardown, follow [scenario cleanup](../safety-and-idempotency.md#scenario-cleanup) and reuse scoped authorization. Delete owned KBs before [KS deletion](../../operations/data-plane/knowledge-sources/delete.md); preserve sources referenced by retained KBs. Let KS deletion remove recorded `createdResources`; do not pre-delete the index. Verify GET/404 and retained resources. Never delete the lakehouse, shortcuts, or original files.

## Error and output contract

Return operation output plus kind, workspace/lakehouse/path, generated resources, synchronization errors, and validation result. Redact private content.

## Official references

- [Indexed OneLake knowledge sources](https://learn.microsoft.com/azure/search/agentic-knowledge-source-how-to-onelake)
- [OneLake prerequisites and permissions](https://learn.microsoft.com/azure/search/search-how-to-index-onelake-files)
