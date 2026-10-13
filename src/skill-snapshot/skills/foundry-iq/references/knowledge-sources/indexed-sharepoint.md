# Create Or Update Indexed SharePoint Knowledge Sources

## Quick reference

- **Kind:** `indexedSharePoint` (indexed).
- **Operations:** [create](../../operations/data-plane/knowledge-sources/create.md) or [create/update](../../operations/data-plane/knowledge-sources/create-or-update.md).
- **API version:** `dataApiVersion`; inherit the operation's shared contracts.

## When to use / Do not use

Index approved SharePoint content. Do not substitute `remoteSharePoint` and its query-time permission model.

## Inputs and context discovery

Reuse or resolve `dataApiVersion` with the [API version policy](../api-version-policy.md). This is a catalog-baseline payload; verify the selected version and never silently change it.

Resolve site/tenant, app/credential, library scope, identity, and embedding deployment. Verify indexer preview prerequisites. This selects the default library; do not broaden it without approval.

## Preconditions and authentication

Use a Search-audience Entra token with caller Search Service Contributor and Search Index Data Contributor roles. Search RBAC does not grant SharePoint access: verify app permissions, consent, and site grants. Prefer supported secretless auth. The Search identity needs Cognitive Services User on the model.

## Safety or approval gate

Obtain approval for data movement, model costs, and permission changes. Ingestion credentials alone do not preserve end-user access. If ACLs are required, verify `ingestionPermissionOptions` and query-time enforcement; stop rather than dropping permissions.

## Request contract

```json
{
  "name": "<source-name>",
  "kind": "indexedSharePoint",
  "indexedSharePointParameters": {
    "connectionString": "<approved-sharepoint-connection-string>",
    "containerName": "defaultSiteLibrary",
    "query": null,
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

Use SharePoint syntax (`SharePointOnlineEndpoint`, `ApplicationId`, credential/tenant fields), not Blob syntax. Inject secrets privately; never commit or print them. Verify `containerName`/`query` for narrower scope. Do not substitute text-only for requested image processing.

## Execution and validation

Read the source with [get](../../operations/data-plane/knowledge-sources/get.md); record `createdResources` and created/reused ownership. Poll [source status](../../operations/data-plane/knowledge-sources/get-status.md) with bounded backoff. Require completed synchronization, zero failed items, and expected library content; `active` alone is insufficient. Verify requested retrieval with a known answer/SharePoint reference and allowed/denied-user checks for ACLs.

## Rollback or recovery

Use ETags for restoration. For teardown, follow [scenario cleanup](../safety-and-idempotency.md#scenario-cleanup) and reuse scoped authorization. Delete owned KBs before [KS deletion](../../operations/data-plane/knowledge-sources/delete.md); preserve sources referenced by retained KBs. Let KS deletion remove recorded `createdResources`; do not pre-delete the index. Verify GET/404 and retained resources. Never delete SharePoint originals or shared app registrations.

## Error and output contract

Return kind, site/library scope, generated resources, errors, and validation with operation output. Redact credentials/private content.

## Official references

- [Indexed SharePoint knowledge sources](https://learn.microsoft.com/azure/search/agentic-knowledge-source-how-to-sharepoint-indexed)
- [Indexer prerequisites](https://learn.microsoft.com/azure/search/search-how-to-index-sharepoint-online)
