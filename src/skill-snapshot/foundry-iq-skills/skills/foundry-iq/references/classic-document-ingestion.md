# Ingest a document library into classic Search

Conditional on a **classic** architecture chosen by the autonomous hero.
Use actual customer documents, never Simple Search's demo records; no KS/KB.
Reuse a compatible existing index/pipeline only after verifying corpus,
freshness, access, citations and owner authority.

## Preflight and approval

For new ingestion, this bounded recipe uses an approved Blob container/prefix
and standard text extraction, without embeddings or generated KS resources.
Verify supported formats before spending: plain text/Markdown can use `text`;
format-supported PDF/Office uses `default`. Mixed parsing modes need separate
approved prefixes/indexers sharing the same compatible index. If richer
extraction, source ACLs or another source/push pipeline is required, verify its
supported exact contract first or return `classic-ingestion-contract-required`
before provisioning; do not silently switch to a KB or tutorial.

Resolve Search versions under [policy](api-version-policy.md), then
[RBAC](authentication-rbac.md): index/data-source/indexer management needs
Search Service Contributor; Search identity needs Storage Blob Data Reader
on the approved container; querying needs Search Index Data Reader.
Customer uploads require independent storage write authority. Discover
existing grants and approve only missing exact scopes, data movement,
storage/indexer costs, corpus exposure, schedule and ownership.

For local seeds, stage only approved files with
`az storage blob upload-batch --account-name "<account>" --destination "<container>" --source "<approved-local-directory>" --auth-mode login --overwrite false`.
Never upload the skill, credentials/operator files or unrelated subdirectories.
List/read back names and metadata; unsupported upload/auth/format is a blocker,
not public-container/key fallback.

## Execute the owned pipeline

List/get before writes. Use these complete bodies at the verified selected
version through the linked catalog operations. Substitute approved names.
Create with `If-None-Match: *`; approved updates preserve prior definitions/
unrelated fields with current `If-Match`, never an unconditional overwrite.

[Index](../operations/data-plane/indexes/create-or-update.md):

```json
{"name":"<index-name>","fields":[{"name":"id","type":"Edm.String","key":true,"filterable":true},{"name":"title","type":"Edm.String","searchable":true,"retrievable":true},{"name":"content","type":"Edm.String","searchable":true,"retrievable":true},{"name":"url","type":"Edm.String","retrievable":true}]}
```

[Data source](../operations/data-plane/data-sources/create-or-update.md):

```json
{"name":"<data-source-name>","type":"azureblob","credentials":{"connectionString":"ResourceId=/subscriptions/<subscription>/resourceGroups/<rg>/providers/Microsoft.Storage/storageAccounts/<account>/;"},"container":{"name":"<container>","query":"<approved-prefix>"}}
```

[Indexer](../operations/data-plane/indexers/create-or-update.md):

```json
{"name":"<indexer-name>","dataSourceName":"<data-source-name>","targetIndexName":"<index-name>","disabled":true,"schedule":{"interval":"PT1H"},"parameters":{"configuration":{"dataToExtract":"contentAndMetadata","parsingMode":"default"}},"fieldMappings":[{"sourceFieldName":"metadata_storage_path","targetFieldName":"id","mappingFunction":{"name":"base64Encode","parameters":{"useHttpServerUtilityUrlTokenEncode":true}}},{"sourceFieldName":"metadata_storage_path","targetFieldName":"url"},{"sourceFieldName":"metadata_storage_name","targetFieldName":"title"}]}
```

For all-text input replace only `parsingMode` with `text`. Approve the actual
cadence; creation stays disabled until definitions/permissions/network and
source scope read back correctly. ETag-update `disabled:false`, then
[run](../operations/data-plane/indexers/run.md) once only if idle and authorized.
Inspect [status](../operations/data-plane/indexers/get-status.md) with bounded
polling; require terminal success and zero failed items. Uncertain POST or
active work means status reconciliation, never blind run/reset.

## Verify, recover and return

Use [search](../operations/data-plane/documents/search-post.md):

```json
{"search":"<known-fact terms>","select":"id,title,content,url","top":5}
```

Require actual customer fact/text and original Blob URI in `url`, not encoded
key or invented citation. Test a known add/update through ingestion and
observe the next scheduled run. Deletions require a verified configured
soft-delete/tombstone policy at source creation; absent tracking is explicitly
unverified, never an orphan-deletion/full-reset shortcut. Confirm the native
Foundry tool's index/query/citation contract before binding.

Diagnose only the failed source/job/permission/configuration; preserve cursor
and other consumers. Return created/reused IDs, ETags, source scope, schedule,
freshness/deletion/citation evidence, cost, remaining blockers and cleanup.
Restore only approved prior owned definitions. Teardown unbinds the owned
agent version, then deletes owned indexer, data source and index; approved
test blobs/storage last. Never delete a reused pipeline or original library.

Sources: [Blob indexers](https://learn.microsoft.com/azure/search/search-how-to-index-azure-blob-storage),
[field mappings](https://learn.microsoft.com/azure/search/search-indexer-field-mappings).
