# Conditional: complete GA Web KB/retrieve lifecycle

Read only when Web's selected, approved lifecycle version is GA `2026-04-01`,
not the catalog's preview. Apply [shared discovery, ETags and verification](knowledge-base-retrieval.md)
and the [Web source contract](knowledge-sources/web.md).
Preserve inherited versions or block/reconcile; no silent upgrades.

Use the same catalog create/update and retrieve operations at the selected GA
version. These are complete bodies, not field-removal instructions.

```json
{"name": "<kb-name>", "knowledgeSources": [{"name": "<web-source-name>"}], "models": [{"kind": "azureOpenAI", "azureOpenAIParameters": {"resourceUri": "<chat-model-endpoint>", "deploymentId": "<chat-deployment>", "modelName": "<chat-model>"}}]}
```

```json
{"intents": [{"type": "semantic", "search": "<known-answer question>"}], "includeActivity": true, "maxRuntimeInSeconds": 60, "maxOutputSizeInTokens": 6000, "knowledgeSourceParams": [{"knowledgeSourceName": "<web-source-name>", "kind": "web", "includeReferences": true, "includeReferenceSourceData": true}]}
```

Compare GA sources/models on readback, not absent preview settings.
No `messages`, `outputMode`, `retrievalReasoningEffort`, `maxOutputSize`,
`alwaysQuerySource` or `failOnError` on GA. Inspect activity/source errors and
missing evidence explicitly; an HTTP success alone is not verification.

Require a known fact, Web `url`/title references and `web`/
`modelWebSummarization` activity. Text is a cited LLM summary, never verbatim.
Unknown public discoverability, absent citations or unsupported identity/version
remains blocked/unverified. Recover and clean up only approved owned definitions
under the shared contract; do not recreate sources to hide failures.
If a Web KS was created, include the
[Web compliance note](knowledge-sources/web.md#error-and-output-contract)
in the final status update.

Sources: [GA KB schema](https://learn.microsoft.com/rest/api/searchservice/knowledge-bases/create-or-update?view=rest-searchservice-2026-04-01),
[GA retrieve schema](https://learn.microsoft.com/rest/api/searchservice/knowledge-retrieval/retrieve?view=rest-searchservice-2026-04-01).
