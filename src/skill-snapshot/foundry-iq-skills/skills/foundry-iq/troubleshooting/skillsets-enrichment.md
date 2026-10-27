# Skillsets and Enrichment

Use for skill execution errors, missing enriched fields, or vectorization failures. Record indexer/skill names, error stage, UTC time, and request ID; redact source content and model credentials.
Follow the [API version policy](../references/api-version-policy.md) with the original request version as input; do not silently change it. Apply the [HTTP contract](../references/http-contract.md).
Start read-only; require approval for skillset edits, reprocessing, grants, or model spend. Use the [shared RBAC check](../references/authentication-rbac.md) and retain the prior definition/ETag before updates.

## Workflow

1. **Missing input or output mapping.** [Get indexer status](../operations/data-plane/indexers/get-status.md) and identify the failed skill from errors/warnings, then [read the skillset](../operations/data-plane/skillsets/get.md).
   Compare `context` and input `source` paths with the actual enrichment tree; a wrong path or scalar/array mismatch can produce empty inputs. Check output names against the indexer's `outputFieldMappings` or index projections and the target field types.
2. **Embedding endpoint or access error (401/403/404).** Verify `resourceUri` targets the owned model resource and `deploymentId` is an existing deployment, not just the model's name; confirm `modelName` matches it.
   For Azure OpenAI managed-identity embedding, the selected Search identity needs Cognitive Services OpenAI User on the model resource. Check model/private-network access separately from caller Search permissions; do not fall back to API keys.
3. **Oversized input, wrong dimensions, or model 429.** Check text is nonempty and within the embedding model's input limit; propose chunking through Text Split for oversized text. Match embedding skill `dimensions` to the target vector field.
   For model throttling, use [limit diagnosis](limits-throttling-cost.md). Apply approved corrections through [skillset update](../operations/data-plane/skillsets/create-or-update.md) while preserving unrelated settings; do not raise failed-item tolerances to hide the error.

**Verify/stop:** After approval, [run the indexer](../operations/data-plane/indexers/run.md) once and check the affected document's enriched fields/vector and execution errors. If change tracking/cache skips it, propose a supported [selective skill reset](../operations/data-plane/skillsets/reset-skills.md) with impact/approval; never blanket-reset or claim success from an HTTP response alone.

**Sources:** [Enrichment errors and warnings](https://learn.microsoft.com/azure/search/cognitive-search-common-errors-warnings), [Embedding inputs, identity, and dimensions](https://learn.microsoft.com/azure/search/cognitive-search-skill-azure-openai-embedding).
