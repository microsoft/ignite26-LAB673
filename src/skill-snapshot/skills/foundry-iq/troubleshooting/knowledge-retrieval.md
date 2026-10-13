# Knowledge Retrieval

Use for knowledge-source setup failures, empty retrieval, or missing grounding/citations. Record KB/source names, status/error, activity failures, UTC time, and request ID; redact private content.
Follow the [API version policy](../references/api-version-policy.md) with the original request version as input; do not silently change it. Apply the [HTTP contract](../references/http-contract.md).
Start read-only; require approval for grants, source/KB updates, ingestion, or model spend. Use the [shared RBAC check](../references/authentication-rbac.md); preserve document permissions.

## Workflow

1. **Wrong or unready source.** [Read the KB](../operations/data-plane/knowledge-bases/get.md) and each [referenced source](../operations/data-plane/knowledge-sources/get.md); confirm names and source scope.
   For ingested sources, [check synchronization status](../operations/data-plane/knowledge-sources/get-status.md), processed/failed items, and the generated indexer's errors. `active` alone is not proof of indexed content. A `searchIndex` source instead needs a populated backing index and matching fields/semantic configuration.
2. **Blob knowledge source cannot ingest (403).** Check the Search managed identity, not just the user's Storage access: it needs Storage Blob Data Reader on the source storage account/approved scope.
   Follow the [Blob setup guide](../references/knowledge-sources/azure-blob.md) to verify `ResourceId`, container/folder, selected identity, and model access. Ask before a missing grant; use [network diagnosis](private-network-dns.md) if storage is private. Do not widen the ingestion prefix or disable ACL ingestion.
3. **Model or request mismatch.** When planning/vectorization fails, verify the configured model endpoint and actual deployment name, and the Search identity's model permission. Model 429s go to [limit diagnosis](limits-throttling-cost.md).
   Check that input shape, `models`, reasoning effort, and output mode are supported by the original version. Do not silently migrate the API, remove the model, or drop requested reasoning to make the call succeed.
4. **Verify retrieval, not just HTTP success.** Make one approved known-answer [retrieve request](../operations/data-plane/knowledge-retrieval/retrieve.md); inspect activity errors, retrieved references, and the requested grounded response.
   If the backing index has data but retrieval is empty, check selected sources, searched/returned fields, and query-time permission filters under the same user identity. Never remove security filters or authorization headers.

**Verify/stop:** For ingested sources, require successful synchronization; for all sources, require an expected reference for the known answer. Report source/model/access blockers or partial retrieval explicitly; do not recreate generated resources or claim success from an empty response.

**Sources:** [Blob prerequisites](https://learn.microsoft.com/azure/search/agentic-knowledge-source-how-to-blob), [Retrieve and inspect results](https://learn.microsoft.com/azure/search/agentic-retrieval-how-to-retrieve).
