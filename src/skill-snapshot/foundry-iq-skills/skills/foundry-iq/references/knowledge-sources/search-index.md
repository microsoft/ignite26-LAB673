# Create Or Update Search Index Knowledge Sources

## Quick reference

- **Kind:** `searchIndex` (existing Azure AI Search index / AZS).
- **Operations:** [create](../../operations/data-plane/knowledge-sources/create.md) or [create/update](../../operations/data-plane/knowledge-sources/create-or-update.md).
- **API version:** `dataApiVersion`; inherit the operation's shared contracts.

## When to use / Do not use

Wrap an existing populated index on the same Search service. This recipe does not upload files, create an indexer, or connect to an index on another service.

## Inputs and context discovery

Reuse or resolve `dataApiVersion` with the [API version policy](../api-version-policy.md). This payload describes the catalog baseline; verify the exact selected version before execution and never silently change it.

Read the index definition and confirm its name, semantic configuration, searchable fields, and retrievable source/citation fields. Resolve the placeholders from that schema, not guessed field names. Check for an existing knowledge source before choosing its name.

## Preconditions and authentication

Use a Search-audience Entra token and Search Service Contributor for the definition. Query verification additionally needs Search Index Data Reader or Contributor. Verify agentic retrieval support and the index criteria in the official guide.

## Safety or approval gate

Show the desired-state diff and obtain approval for production or access-boundary changes. Do not rebuild or modify the existing index to make the example fit. Preserve document-level access controls; selecting fields is not an authorization filter.

## Request contract

Use this body with the selected create or create/update operation:

```json
{
  "name": "<source-name>",
  "kind": "searchIndex",
  "searchIndexParameters": {
    "searchIndexName": "<existing-index-name>",
    "semanticConfigurationName": "<existing-semantic-configuration>",
    "searchFields": [{"name": "<searchable-content-field>"}],
    "sourceDataFields": [
      {"name": "<retrievable-key-field>"},
      {"name": "<retrievable-content-field>"},
      {"name": "<retrievable-citation-field>"}
    ]
  }
}
```

`searchFields` restricts searched fields; `sourceDataFields` selects fields returned with referenced source data. Keep an explicit semantic configuration for compatibility with versions that require it. Do not add ingestion parameters to a `searchIndex` source.

## Execution and validation

Read the source with [get](../../operations/data-plane/knowledge-sources/get.md); compare kind, index, and fields and record created/reused ownership. There is no generated pipeline to wait for. Verify requested retrieval through an approved KB with a known answer and source/citation fields. An empty index is not successful content validation.

## Rollback or recovery

Restore an approved definition with its ETag. For teardown, follow [scenario cleanup](../safety-and-idempotency.md#scenario-cleanup) and reuse scoped authorization. Delete owned KBs before [KS deletion](../../operations/data-plane/knowledge-sources/delete.md); preserve sources referenced by retained KBs. Verify GET/404 for the KS and confirm the reused index remains intact. Never delete or recreate the reused index.

## Error and output contract

Return the selected operation's output plus kind, backing index, field mappings, validation result, and remaining action. Surface missing fields/configuration or denied access; redact private document content.

## Official references

- [Search index knowledge sources](https://learn.microsoft.com/azure/search/agentic-knowledge-source-how-to-search-index)
- [Create contract: catalog baseline](https://learn.microsoft.com/rest/api/searchservice/knowledge-sources/create?view=rest-searchservice-2026-08-01-preview)
