# Create or Update Web Knowledge Sources

## Quick reference

- **Kind:** `web` (Bing Custom Search; no ingestion, queries internet).
- **Operations:** [create](../../operations/data-plane/knowledge-sources/create.md) or [create/update](../../operations/data-plane/knowledge-sources/create-or-update.md).
- **`dataApiVersion`:** GA `2026-04-01` or preview `2026-08-01-preview`.
  [Policy](../api-version-policy.md): verify source/KB/retrieve compatibility
  and honor explicit pins/GA-only constraints; no separate version permission.
  Preview enables answer synthesis; GA returns extractive citations.
  Never mix their fields or substitute only a URL date.

## When to use / Do not use

Use for public-region Search services. Web content is LLM-summarized;
private/sovereign-cloud Search is unsupported.

## Inputs and context discovery

Verify the subscription has Web Knowledge Source access (default-enabled). An
admin may disable it:
`az feature show --name WebKnowledgeSourceDisabled --namespace Microsoft.Search`;
`Registered` means disabled — report the blocker; do not fall back silently.
Verify the Search service is in a public region.

## Preconditions and authentication

Use a Search-audience Entra token. Creation needs **Search Service
Contributor** (keyless); no key fallback and no Search Index
Data Contributor, since there is no index/indexer.

## Safety or approval gate

Approve creation/update, domain scope and Bing API costs under the
[shared safety contract](../safety-and-idempotency.md). Web Knowledge Source is a
First Party Consumption Service under the Grounding with Bing terms and
Microsoft Privacy Statement.

## Request contract

```json
{
  "name": "<source-name>",
  "kind": "web",
  "webParameters": {
    "domains": {
      "allowedDomains": [{"address": "learn.microsoft.com", "includeSubpages": true}],
      "blockedDomains": []
    }
  }
}
```

Omitting `domains` allows unrestricted internet access; confirm approval before
omitting it. Use `If-None-Match: *` for creation; use the current ETag with
`If-Match` for an approved update.

## Execution and validation

No `createdResources`, polling, or sync wait — PUT is immediately queryable.
The KB **must** reference a chat model, including GA summarization/citations.
Apply the selected whole-lifecycle version: GA's separate `intents` recipe or
preview `low`/model planning and optional synthesis, never preview `minimal`.
Use complete
[KB/retrieve bodies](../knowledge-base-retrieval.md), never mixed fields.
Confirm the `activity` array's `web` and `modelWebSummarization` records are
present. Content is always LLM-summarized — never claim verbatim web text as
a citation.

## Rollback or recovery

Use ETags for restoration. Teardown deletes the KS; no generated indexer/index
objects exist. Follow
[scenario cleanup](../safety-and-idempotency.md#scenario-cleanup) for owned
KBs that referenced it.

## Error and output contract

Return kind, domain scope, API version choice/source, correlation ID, cost
disclosure, and validation. Redact credentials/private content.

If a Web KS was created, include this note in the final status update:

**Web Knowledge Source note:** The Microsoft Data Protection Addendum does not
apply to data sent to Web Knowledge Source. Customer data flows outside the Azure
compliance and Geo boundary, waiving applicable elevated Government Community
Cloud commitments, including data sovereignty and screened/citizenship-based support.

## Official references

- [Web knowledge sources](https://learn.microsoft.com/azure/search/agentic-knowledge-source-how-to-web)
- [Manage/disable Web sources](https://learn.microsoft.com/azure/search/agentic-knowledge-source-how-to-web-manage)
- [Microsoft Data Protection Addendum](https://www.microsoft.com/licensing/docs/view/Microsoft-Products-and-Services-Data-Protection-Addendum-DPA)
