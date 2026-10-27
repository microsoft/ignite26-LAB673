# Compose a KB and retrieve cited evidence

Use the selected hero's source boundaries/ownership and
[routine validation rules](safety-and-idempotency.md#routine-validation).

## Discover and select

Resolve `dataApiVersion` under [policy](api-version-policy.md). Search-audience Entra and
[HTTP attribution](http-contract.md). Creation: Search Service Contributor;
query: Search Index Data Reader. Search identity: Cognitive Services User or
existing Foundry User on configured model accounts. Missing access blocks, never keys.

Use [KB list](../operations/data-plane/knowledge-bases/list.md) and
[get](../operations/data-plane/knowledge-bases/get.md) before PUT. Confirm
corpus, freshness, access and governed reuse; names alone prove none.
Preserve shared sources/settings or create an approved isolated KB.
Approve every retained source's boundary; request parameters are not access controls.

`minimal` with explicit `intents` requires `extractiveData`: no answer synthesis,
answer instructions or Web. It searches all compatible KB sources without a
planning model. Use `low`/`messages` with a chat model for decomposition/source
selection or service `answerSynthesis`. Check actual required-source activity,
including zero-result activity; flags/instructions are not coverage proof.

## Lifecycle version compatibility

Verify one compatible version across sources, KB and retrieve; adapt each kind's
DTO under policy without a separate API-version permission question.

- **`2026-08-01-preview`**: use the recipes below with each actual kind.
  Web requires a chat model and `low`, not the minimal body.
- **GA `2026-04-01`**: use [complete GA bodies](knowledge-base-ga-web.md). Supported
  kinds are `azureBlob`/`indexedOneLake`/`searchIndex`/`web`; never combine
  Remote/File/indexed SharePoint on GA or carry preview-only fields into it.

## Create only when needed (baseline or selected preview)

Run [KB create/update](../operations/data-plane/knowledge-bases/create-or-update.md)
(`KnowledgeBases_CreateOrUpdate`) using one of these complete bodies.
Replace names with approved, ready sources on the same Search service.

Minimal, extractive KB:

```json
{"name": "<kb-name>", "knowledgeSources": [{"name": "<source-name>"}], "outputMode": "extractiveData", "retrievalReasoningEffort": {"kind": "minimal"}}
```

For query planning, use this body instead:

```json
{"name": "<kb-name>", "knowledgeSources": [{"name": "<source-name>"}], "models": [{"kind": "azureOpenAI", "azureOpenAIParameters": {"resourceUri": "<chat-model-endpoint>", "deploymentId": "<chat-deployment>", "modelName": "<chat-model>"}}], "outputMode": "extractiveData", "retrievalReasoningEffort": {"kind": "low"}}
```

Use `If-None-Match: *` for creation. For an approved update, retain the prior
definition, preserve other sources/settings and use its ETag with `If-Match`.
Include `Prefer: return=representation`. Compare effective sources/models/
reasoning/output, normalizing documented defaults, not raw JSON equality.
A 412 requires re-discovery, never an unconditional overwrite.

## Retrieve (baseline or selected preview)

Run [retrieve](../operations/data-plane/knowledge-retrieval/retrieve.md)
(`KnowledgeRetrieval_Retrieve`), `POST /knowledgebases('<kb-name>')/retrieve`,
with the inherited `dataApiVersion`. Substitute the source's actual `kind`
(`file`, `azureBlob`, or the selected source's documented kind), not `searchIndex`
merely because a KS generated an index.
This full request uses minimal reasoning and an explicit known-answer query:

```json
{"intents": [{"type": "semantic", "search": "<known-answer question>"}], "retrievalReasoningEffort": {"kind": "minimal"}, "outputMode": "extractiveData", "includeActivity": true, "maxRuntimeInSeconds": 60, "maxOutputSize": 6000, "knowledgeSourceParams": [{"knowledgeSourceName": "<source-name>", "kind": "<source-kind>", "alwaysQuerySource": true, "failOnError": true, "includeReferences": true, "includeReferenceSourceData": true}]}
```

For a KB configured for `low`, replace `intents` and the reasoning field with:

```json
{"messages": [{"role": "user", "content": [{"type": "text", "text": "<representative multi-hop question>"}]}], "retrievalReasoningEffort": {"kind": "low"}}
```

This fragment replaces those fields; do not submit it alone or send both
`intents` and `messages`. Confirm limits against the selected version and
preserve a reused KB's reasoning/settings unless an override is approved.
For permission-protected indexed content, verify ingestion-time permission
metadata and query-time enforcement. Remote SharePoint instead requires native
query-time entitlement/identity, not ingested ACLs. Pass the signed-in user's token in
`x-ms-query-source-authorization` (caller and end-user identities differ);
missing identity or enforcement blocks retrieval, never unfiltered fallback.

## Verify, recover and return

Require HTTP 200, no activity errors, and expected-source activity. Treat 206,
source/model errors or missing required evidence as incomplete. Decode text
items in `response[].content[]` as JSON for extractive output; join each
chunk's `ref_id` (integer or string) to string `references[].id` by their string
forms, not JSON type equality or a document key; synthesized `[ref_id:0]` uses
the same ID. Join reference
`activitySource` to activity `id` for actual source names. Require the known
fact and matching source-kind reference: File `docName`, Blob original
`blobUrl`, Remote SharePoint `webUrl`, Web `url`. For indexed SharePoint/OneLake
or Search-index wrappers, resolve the selected version's original-source URI/
retrievable citation-field contract in its type guide; absent provenance is
unverified, not a File/Blob failure. Never fabricate URLs or confuse a preview
index's `citationUrl` with the original document. Web text is a cited LLM
summary, not a verbatim passage. Excerpts stay inside the approved boundary.

Reject missing/unknown synthesis markers; never invent their links. Ranked
passages do not prove an answer. Smoke checks are not quality evidence.

Inspect empty-result readiness, kind, query and budgets using
[retrieval diagnosis](../troubleshooting/knowledge-retrieval.md).
401/403: [diagnose identities](../hero-scenarios/diagnose-access-issues/diagnose-access-issues.md);
bound retries, never recreate to hide errors.
Return ownership, versions/reasoning, endpoint, request IDs, warnings, citations,
costs and remaining actions via the [output contract](output-contract.md).
Delete only approved, owned KBs before their sources using
[scenario cleanup](safety-and-idempotency.md#scenario-cleanup).

## Conditional: permission-aware agent handoff

For protected indexed content verify supported ingestion permissions; for
Remote SharePoint verify query-time entitlements. Both need per-user query
identity and differently entitled denial checks — the project connection
authenticates the tool, not the user. Use the binding helper's
`--per-user-authorization` to add required structured input
`foundry_iq_search_auth_token` and MCP header
`x-ms-query-source-authorization: {{foundry_iq_search_auth_token}}`. Pass
each signed-in user's Search token privately in `structured_inputs`; never
persist/log it, substitute setup/project identity, or expose it to
prompts/unrelated tools. Missing/unverified flows block attachment with
`user-authorization-required`, not unfiltered retrieval. File baseline does
not inherit local ACLs; verify every mixed/remote source's identity contract
rather than inventing OAuth/Work IQ passthrough.

The agent invocation uses a version-pinned `agent_reference`, not latest:
[SDK 2.4.0](https://github.com/Azure/azure-sdk-for-python/tree/azure-ai-projects_2.4.0/sdk/ai/azure-ai-projects).

## Official contracts

- [KB configuration](https://learn.microsoft.com/azure/search/agentic-retrieval-how-to-create-knowledge-base)
- [Retrieve, REST response and MCP differences](https://learn.microsoft.com/azure/search/agentic-retrieval-how-to-retrieve)
