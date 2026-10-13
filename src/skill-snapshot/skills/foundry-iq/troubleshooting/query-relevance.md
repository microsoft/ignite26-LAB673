# Query Relevance

Use for empty, incorrect, or poorly ranked search results. Record index, query shape, expected document key, status/error, UTC time, and request ID; do not log private query/document text.
Follow the [API version policy](../references/api-version-policy.md) with the original request version as input; do not silently change it. Apply the [HTTP contract](../references/http-contract.md).
Start read-only; require approval before schema, analyzer, reindexing, or billable semantic/model changes. Preserve the caller identity, security filters, and authorization headers in every diagnostic request.

## Workflow

1. **Content missing or wrong index.** [Look up a known document](../operations/data-plane/documents/get.md) and [read the index](../operations/data-plane/indexes/get.md); confirm endpoint/index, searchable content fields, and data freshness.
   Within the approved scope, try a small [simple search](../operations/data-plane/documents/search-post.md) with `{"search":"*","top":1}` plus existing permission filters. This is a diagnostic probe, not a replacement for the user's query; if content is absent, use [ingestion diagnosis](indexers-data-sources.md).
2. **Filter, parser, or analyzer mismatch.** Compare `queryType`, `searchFields`, and business filters with the index schema. Filters require filterable fields and exact, case-sensitive values; they do not use full-text analyzers.
   Simplify one nonsecurity query clause at a time without widening authorized scope. For unexpected token matching, use [Analyze](../operations/data-plane/indexes/analyze.md) with the field's configured analyzer; do not change analyzers or rebuild the index as a diagnostic shortcut.
3. **Semantic or vector configuration mismatch.** Check `semanticConfiguration` names a real configuration with the intended text fields. For vector queries, confirm the requested vector field/profile and matching embedding model/dimensions; a text-vector query also needs a compatible vectorizer.
   Compare a plain-text probe with the original semantic/vector query to isolate the failing stage. Do not remove required security trimming, silently substitute a model, or enable paid features to obtain a better result.

**Verify/stop:** Rerun the original known-answer query once after an approved correction and check the expected document/ranking, not merely a nonempty response. Return the isolated ingestion/filter/analyzer/vector issue and any remaining configuration action; avoid claiming overall relevance improvement from one query.

**Sources:** [Query and filter behavior](https://learn.microsoft.com/azure/search/search-query-overview), [Embedding configuration](https://learn.microsoft.com/azure/search/cognitive-search-skill-azure-openai-embedding).
