# Limits, Throttling, and Cost

Use for 429/503, quota exhaustion, or unexpectedly expensive runs. Record the issuing service, operation, status/error, `Retry-After`, UTC time, and request ID; redact private content.
Follow the [API version policy](../references/api-version-policy.md) with the original request version as input; do not silently change it. Apply the [HTTP contract](../references/http-contract.md).
Start read-only; require approval for scaling, quota/configuration changes, deletion, or additional model spend. Preserve existing resources under the [safety rules](../references/safety-and-idempotency.md).

## Workflow

1. **Identify whose limit was hit.** Distinguish a Search response from an Azure OpenAI/Foundry dependency error in indexer or retrieval activity; adding Search capacity does not fix model token-per-minute quota.
   For Search, [get service statistics](../operations/data-plane/service-statistics/get.md) and [index statistics](../operations/data-plane/indexes/get-statistics.md). Compare `storageSize`, `vectorIndexSize`, and object counts with the actual service/tier limits; older services can have lower quotas.
2. **Separate transient load from a hard cap.** Reduce concurrency for throttling and honor `Retry-After`; allow at most two retries with backoff, only for replay-safe operations.
   Do not retry document/storage/vector/object quota failures blindly. For model throttling, inspect deployment quota and reduce request rate or approved input/chunk size. Propose scaling or quota changes only after identifying the bottleneck.
3. **Explain the cost before changing it.** Read current pricing model/capacity through [service get](../operations/search-management/services/get.md), then review retrieval activity token counts or indexer enrichment calls.
   Dedicated Search Units are replicas times partitions; serverless does not use those counts. Storage, model calls, enrichment, and private links can add charges. Use [provisioning guidance](../references/service-provisioning.md) for an approved, evidence-based capacity proposal; do not delete resources to cut cost automatically.

**Verify/stop:** Retry one representative request within the approved budget and confirm the original error is gone. If the cap persists, return measured usage/limit, issuing service, proposed change/cost, and required owner approval rather than looping.

**Sources:** [Search quotas and throttling](https://learn.microsoft.com/azure/search/search-limits-quotas-capacity), [Embedding model quota guidance](https://learn.microsoft.com/azure/search/cognitive-search-skill-azure-openai-embedding#best-practices).
