# Indexers and Data Sources

Use for failed, empty, or stale ingestion. Record the indexer/data-source names, latest execution time, status/error, and request ID; redact connection strings and document content.
Follow the [API version policy](../references/api-version-policy.md) with the original request version as input; do not silently change it. Apply the [HTTP contract](../references/http-contract.md).
Start read-only; require approval before data-source updates, runs, resets, permission, or network changes. Use the [shared RBAC check](../references/authentication-rbac.md) for missing access.

## Workflow

1. **Find the failed stage.** [Get indexer status](../operations/data-plane/indexers/get-status.md) and inspect `lastResult`, execution history, errors/warnings, and processed/failed item counts.
   [Read the indexer](../operations/data-plane/indexers/get.md) to confirm `dataSourceName`, `targetIndexName`, `skillsetName`, schedule, and whether it is disabled or already running. Route enrichment failures to [skillsets](skillsets-enrichment.md).
2. **Source access fails (403).** [Read the data source](../operations/data-plane/data-sources/get.md); confirm storage account, container/query prefix, and selected identity or credential mode.
   For managed-identity Blob access, verify the Search identity has Storage Blob Data Reader on the approved storage scope and the connection uses the correct storage `ResourceId`. For SAS-based access, check expiry without exposing the SAS. Persistent firewall/private-link failures go to [network diagnosis](private-network-dns.md).
3. **No new documents.** Check that the approved container/prefix contains supported, changed files and that a recent run actually occurred; an empty or overly narrow prefix is not an authentication failure.
   Propose only the needed [data-source correction](../operations/data-plane/data-sources/create-or-update.md). After approval, [run the indexer](../operations/data-plane/indexers/run.md) once if it is not already running; do not reset the whole pipeline as a first step.

**Verify/stop:** Make at most two spaced status checks, then report success, still-running, or failure accurately. Verify an affected document in the target index and report remaining errors/warnings; escalate persistent failures with the failed stage and required owner action.

**Sources:** [Indexer troubleshooting](https://learn.microsoft.com/azure/search/search-indexer-troubleshooting), [Indexer errors](https://learn.microsoft.com/azure/search/cognitive-search-common-errors-warnings).
