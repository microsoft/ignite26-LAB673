# Document Indexing

Use for rejected uploads/merges or missing documents after a batch. Record the index, action, HTTP status, per-item error codes, UTC time, and request ID; redact document content.
Follow the [API version policy](../references/api-version-policy.md) with the original request version as input; do not silently change it. Apply the [HTTP contract](../references/http-contract.md).
Start read-only; require approval before document/schema changes or retries that can overwrite data. Preserve the intended action and keys under the [safety rules](../references/safety-and-idempotency.md).

## Workflow

1. **Partial batch failure.** Inspect every item returned by [Documents_Index](../operations/data-plane/documents/index.md), including `status`, `statusCode`, and `errorMessage`. HTTP 207 means some items failed; do not mark the whole batch successful or replay successful items.
2. **Invalid document (400) or missing merge target (404).** [Read the index schema](../operations/data-plane/indexes/get.md). Check the key field is present and valid, field types match, and vector array length matches the field's `dimensions`.
   A `merge` cannot create a missing key; do not silently change it to `upload`/`mergeOrUpload`. Propose the smallest payload correction rather than deleting/rebuilding the index.
3. **Oversized or overloaded batch.** For 413, split the approved payload below 16 MB and no more than 1,000 documents per batch, counting JSON overhead. A single oversized document needs a content correction.
   For transient 503s, reduce concurrency and retry only failed items at most twice with backoff after checking replay safety. A document-quota 429 needs [limit diagnosis](limits-throttling-cost.md), not repeated retries; re-read state for 409 conflicts.

**Verify/stop:** Inspect all retried item results and [look up an affected key](../operations/data-plane/documents/get.md) with bounded visibility checks. Counts alone are not proof; return failed-item totals and remaining schema/quota/concurrency blockers without private payloads.

**Sources:** [Load an index and per-document status codes](https://learn.microsoft.com/azure/search/search-how-to-load-search-index), [Request limits](https://learn.microsoft.com/azure/search/search-limits-quotas-capacity#api-request-limits).
