# Ground an agent in indexed OneLake content

Answer from a Microsoft Fabric lakehouse's Files area through a generated,
indexed knowledge source.

## When to use / do not use

Use when documents live in a Fabric lakehouse and an agent must answer from
them: "Answer from the files in our OneLake lakehouse." Ingest only the
lakehouse's **Files** area. Explicitly reject and explain, rather than silently
attempt, any request for: the lakehouse **Tables** area, SQL/Parquet-based
access, a Fabric Data Agent, cross-tenant or "My Workspace" sources, private
(non-tenant) synchronization, or per-user ACL inheritance from OneLake/Fabric
permissions — none are supported by this skill's `indexedOneLake` recipe. Use
the [multi-source](../multi-source-knowledge-base/multi-source-knowledge-base.md)
hero when OneLake content must be combined with another source.

## Inputs and discovery

Reuse a compatible existing Search service unless isolation is requested.
Follow [service provisioning](../../references/service-provisioning.md) before
version resolution. Resolve the Fabric workspace ID, lakehouse ID, approved
folder or shortcut path under Files, identity, embedding deployment, target
application/agent, representative questions, freshness requirements and a
known in-scope fact. Verify the selected `dataApiVersion`, region, deployment
and supported source locations/formats before provisioning; Parquet and "My
Workspace" are unsupported regardless of version. Omitting `targetPath` needs
whole-lakehouse approval; never widen an approved folder/shortcut scope.
Inspect representative files for clean text versus diagrams/images/tables/
complex layouts and select a content-processing path appropriate to the
expected questions.

List/get permitted [sources](../../operations/data-plane/knowledge-sources/list.md)
and [KBs](../../operations/data-plane/knowledge-bases/list.md) read-only.
Confirm suitable governed reuse; leave reused assets unchanged.

Use the [shared RBAC check](../../references/authentication-rbac.md) for caller
Search Service Contributor and Search Index Data Contributor to create the
pipeline, plus Search Index Data Reader for retrieval. Require the same
Search/Fabric tenant, the Search identity's Fabric workspace Contributor role
(not Azure subscription Contributor), external OneLake access, and Cognitive
Services User or existing Foundry User on the model account. Ask before granting missing permissions or provide administrator instructions. Private
synchronization is unsupported; stop on a private-only requirement rather than
approximating it.

Approve generated resources, exact folder/shortcut scope, data movement, model
costs, schedule and ownership together. If source permissions must be
preserved, verify supported permission ingestion and query-time enforcement
before proceeding; OneLake ACL inheritance is not supported, so do not imply it
is preserved.

## API version preflight

Follow [API version policy](../../references/api-version-policy.md) to resolve
`managementApiVersion` and `dataApiVersion` before the first request. Pass the
resolved values unchanged to every operation. Verify payloads, limits,
readiness and citation shapes for overrides. Do not remove required settings
or upgrade silently. Disclose preview use before mutations.

## Execute

1. Inspect [service get](../../operations/search-management/services/get.md)
   (`Services_Get`) for readiness, identity and access. Use
   [service create/update](../../operations/search-management/services/create-or-update.md)
   (`Services_CreateOrUpdate`) only for a new service or approved changes; wait
   for `provisioningState: succeeded`.
2. Reuse an unchanged compatible source, or run
   [KS create/update](../../operations/data-plane/knowledge-sources/create-or-update.md)
   (`KnowledgeSources_CreateOrUpdate`) using the
   [indexed OneLake contract](../../references/knowledge-sources/indexed-onelake.md)
   with `dataApiVersion`, `If-None-Match: *` for creation and
   `Prefer: return=representation`. Use bare workspace/lakehouse IDs and the
   approved `targetPath`; approved updates preserve settings and use current
   ETags.
3. Creation provisions the ingestion pipeline. Read back IDs/path and record
   `createdResources` (data source, skillset, indexer, index) and created/reused
   ownership; confirm synchronization below.
4. Poll [source status](../../operations/data-plane/knowledge-sources/get-status.md)
   (`KnowledgeSources_GetStatus`) with bounded backoff and an agreed deadline.
   Require a relevant completed synchronization, zero `itemsUpdatesFailed` and
   expected folder content for a new nonempty corpus; `active` alone is
   insufficient.
5. Use [KB composition and cited retrieval](../../references/knowledge-base-retrieval.md)
   (`KnowledgeBases_CreateOrUpdate`, `KnowledgeRetrieval_Retrieve`) with
   `kind: indexedOneLake`, required-source errors and references. Compose
   alongside another source using the
   [multi-source hero](../multi-source-knowledge-base/multi-source-knowledge-base.md)
   when the request needs it.

## Verify and clean up

Require the known fact and a matching lakehouse reference; confirm a no-answer
query returns no unsupported answer. Verify incremental freshness: add or
change a file under the approved folder, re-run/poll synchronization, and
confirm the update is reflected within the expected interval. Confirm any
requested access restriction is actually enforced before claiming it; do not
assert ACL inheritance since it is unsupported. Report rejected requests
(Tables/Parquet/private sync/ACL inheritance) as explicit limitations in the
final response rather than omitting them.

For failed or stale ingestion, use
[ingestion diagnosis](../diagnose-ingestion-issues/diagnose-ingestion-issues.md)
and its read-only generated-pipeline checks, then
[indexer troubleshooting](../../troubleshooting/indexers-data-sources.md);
check workspace/lakehouse identity, tenant, network and path. Repair only approved
affected resources; no full reset, broader scope or key fallback as a
shortcut. If the request includes an existing Foundry prompt agent, compose
the [agent hero](../knowledge-base-foundry-prompt-agent/knowledge-base-foundry-prompt-agent.md)
after direct retrieval passes, reusing this KB.

On a teardown request, follow
[scenario cleanup](../../references/safety-and-idempotency.md#scenario-cleanup):
delete the owned [KB](../../operations/data-plane/knowledge-bases/delete.md)
before its [KS](../../operations/data-plane/knowledge-sources/delete.md). Let
KS deletion remove generated assets; do not pre-delete the index. Never delete
the lakehouse, shortcuts or original files.

**Official source:** [Indexed OneLake knowledge sources](https://learn.microsoft.com/azure/search/agentic-knowledge-source-how-to-onelake).
