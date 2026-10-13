# Create Or Update Blob Knowledge Sources

## Quick reference

- **Kind:** `azureBlob` (Azure Blob Storage or ADLS Gen2).
- **Operations:** [create](../../operations/data-plane/knowledge-sources/create.md) or [create/update](../../operations/data-plane/knowledge-sources/create-or-update.md).
- **API version:** `dataApiVersion`; inherit the operation's shared contracts.

## When to use / Do not use

Generate an ingestion pipeline over an approved container/prefix. Use [File](file.md) for direct uploads or [Search index](search-index.md) to wrap an already populated index.

## Inputs and context discovery

Reuse or resolve `dataApiVersion` with the [API version policy](../api-version-policy.md). This is a catalog-baseline payload; verify the selected version and never silently change it.

Discover storage ID, container/prefix, formats, Search identity, and embedding deployment. Set `isADLSGen2` from the account's hierarchical namespace. An empty/omitted prefix requires whole-container approval.

## Preconditions and authentication

Use a Search-audience Entra token. Verify caller Search Service Contributor and Search Index Data Contributor access for the generated pipeline. The Search managed identity needs Storage Blob Data Reader on the approved storage scope and Cognitive Services User on the model resource. Check network reachability without enabling public access.

## Safety or approval gate

Obtain approval for data movement, generated resources, model costs, and permission/network changes. If document-level permissions must be preserved, verify supported `ingestionPermissionOptions` and query-time enforcement before ingesting; do not silently omit them.

## Request contract

```json
{
  "name": "<source-name>",
  "kind": "azureBlob",
  "azureBlobParameters": {
    "connectionString": "ResourceId=<storage-resource-id>;",
    "containerName": "<container>",
    "folderPath": "<approved-prefix>",
    "isADLSGen2": false,
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

This text-only recipe uses system-assigned identity. Verify user-assigned identity or chat model/AI Services settings before changing it; do not drop requested image processing.

## Execution and validation

Read the definition with [get](../../operations/data-plane/knowledge-sources/get.md); record `createdResources` and created/reused ownership. Poll [source status](../../operations/data-plane/knowledge-sources/get-status.md) with bounded backoff. Require completed synchronization and zero failed items; `active` alone is insufficient. For a nonempty prefix, verify processed items or existing content on an unchanged update. Verify requested retrieval through an approved KB with a known answer and original Blob citation.

## Rollback or recovery

Use ETags for restoration. For teardown, follow [scenario cleanup](../safety-and-idempotency.md#scenario-cleanup) and reuse scoped authorization. Delete owned KBs before [KS deletion](../../operations/data-plane/knowledge-sources/delete.md); preserve sources referenced by retained KBs. Let KS deletion remove recorded `createdResources`; do not pre-delete the index. Verify GET/404 and retained resources. Never delete source blobs or reused storage.

## Error and output contract

Return the selected operation's output plus kind, source scope, generated resource names, synchronization counts/errors, and validation result. Redact credentials and private content.

## Official references

- [Blob knowledge sources](https://learn.microsoft.com/azure/search/agentic-knowledge-source-how-to-blob)
