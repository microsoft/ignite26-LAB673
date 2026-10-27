# Combine multiple knowledge sources in one Knowledge Base

Preserve each source's identity, freshness and citations.

## When to use / do not use

Use for cross-source retrieval. Prefer reading the relevant guides for
requested sources; the others remain available:
[Blob](../agentic-search-blob-knowledge-source/agentic-search-blob-knowledge-source.md),
[File](../agentic-search-file-knowledge-source/agentic-search-file-knowledge-source.md),
[SharePoint](../sharepoint-knowledge-source/sharepoint-knowledge-source.md)
(Indexed or Remote),
[Search index](../search-index-knowledge-source/search-index-knowledge-source.md),
[indexed OneLake](../indexed-onelake-knowledge-source/indexed-onelake-knowledge-source.md)
and the [Web reference](../../references/knowledge-sources/web.md).
Use its hero for one source.

Check [kinds](../../operations/data-plane/knowledge-sources/create.md).

## Inputs and access

Reuse a compatible existing Search service unless isolation is requested.
Follow [service provisioning](../../references/service-provisioning.md)
before version resolution; approve the selected plan. For each requested
source, resolve its own inputs through its owning hero/reference (storage/
site/index/lakehouse identity, scope, extraction, embedding, or Web's
domain scope). Record new versus reused sources. List/get
permitted [sources](../../operations/data-plane/knowledge-sources/list.md)
and [KBs](../../operations/data-plane/knowledge-bases/list.md) read-only
first; a name match alone does not establish access compatibility.

Confirm each source's identity/freshness model independently: composing
several sources into one KB does not harmonize query-time enforcement or
sync cadence. Blob/File are unfiltered unless ingestion carried ACLs; indexed
SharePoint enforces ingested ACLs on a sync interval; remote SharePoint
enforces per-user entitlement per request; a reused index keeps its own
access model; Web has no access control and is always public.

Use the [shared RBAC check](../../references/authentication-rbac.md) across
every source's own requirements, plus **Search Service Contributor** for KB
composition (not Search Index Data Contributor, which only covers
index-level data operations) and Search Index Data Reader for retrieval.
Ask before granting missing permissions or provide administrator instructions.
Approve the combined corpus exposure, per-source costs, missing grants and
ownership together.

## API version preflight

Resolve `managementApiVersion`/`dataApiVersion` under
[API version policy](../../references/api-version-policy.md) before requests.
Verify every kind across the **whole** KS→KB→retrieve lifecycle using
[KB composition and retrieval](../../references/knowledge-base-retrieval.md).
Record documented version overrides without another permission question;
respect explicit pins/GA-only constraints. Disclose previews; unsupported
combinations block.

## Execute

1. For each requested source, run its owning hero/reference to reach a
   ready, verified state under its sync or query-time retrieval contract.
2. Create/update the KB via
   [KB composition and retrieval](../../references/knowledge-base-retrieval.md)
   (`KnowledgeBases_CreateOrUpdate`) with one array listing every validated
   source by name; approve the combined corpus exposure before this write.
3. Compare effective `knowledgeSources`, models/settings on readback, normalizing
   documented defaults, not raw JSON equality; preserve all approved sources.
4. Run [retrieval](../../references/knowledge-base-retrieval.md) (`KnowledgeRetrieval_Retrieve`)
   with `knowledgeSourceParams` matching each source's actual `kind`.
   In a supported preview body, set `failOnError:true` deliberately to surface
   an outage. GA lacks that flag; inspect activity/errors and mark missing sources incomplete
   rather than inventing equivalent behavior.

## Verify and clean up

Verify one known fact per source through the composed KB, confirm citations
attribute each answer to its originating source `kind`/name, and run a
cross-source query needing synthesis across at least two sources. Run a
no-answer query and confirm no unrelated source is cited. Where a source
enforces per-user ACLs/entitlement (indexed/remote SharePoint), repeat its
allow/deny verification through the combined KB.

For required non-Web coverage in a KB without Web, use
`intents`/`minimal`/`extractiveData`; otherwise follow Web's version-specific
model-backed recipe. Preview `low` plans/selects sources.
Verify activity even for zero results; flags and
instructions are not proof. Never use `minimal` + `answerSynthesis`.
If coverage/citations fail, prefer supported extractive requests plus the
app's existing answering layer without changing its output/privacy contract.
Report observed unmet checks/request IDs, not an unconfirmed product bug.
Ask only for changed customer-visible behavior, not a technical mode.

For supported preview flags, verify `failOnError` with an approved,
test-owned **upstream** failure, never an invalid source name or deleting
the KS definition. Example: a disposable index containing only restorable
test records, its Search-index wrapper and test KB on the same service.
Record definitions, seed records, ownership and exact approved restore.
Use [index delete](../../operations/data-plane/indexes/delete.md)
(`Indexes_Delete`) only on that disposable target; verify index GET 404
while KS/KB definitions and references remain unchanged. If deletion is
blocked or definitions disappear, report a non-valid canary, not a pass.
Force the still-defined source with `alwaysQuerySource:true`; compare
`failOnError:true` versus `false` with the same request/identity, inspecting
errors/missing evidence. Restore the owned index/records with create-only
index PUT and document indexing, replay the known fact, then clean up canaries.
No fault-capable dependency/authority means **unverified failure handling**,
not a fabricated pass. Never fault shared resources.

For permission blockers use
[access diagnosis](../diagnose-access-issues/diagnose-access-issues.md);
diagnose the actual source before asking for a grant.
Never reset/recreate the whole KB. For a Foundry prompt agent, compose the
[agent hero](../knowledge-base-foundry-prompt-agent/knowledge-base-foundry-prompt-agent.md)
after retrieval/citation checks pass, reusing this KB.

On teardown, follow
[scenario cleanup](../../references/safety-and-idempotency.md#scenario-cleanup):
delete the owned [KB](../../operations/data-plane/knowledge-bases/delete.md)
first, then walk each source's own cleanup.
Never delete a reused/shared source still referenced by another retained KB.

If a Web KS was created, include this note in the final status update:

**Web Knowledge Source note:** The Microsoft Data Protection Addendum does not
apply to data sent to Web Knowledge Source. Customer data flows outside the Azure
compliance and Geo boundary, waiving applicable elevated Government Community
Cloud commitments, including data sovereignty and screened/citizenship-based support.

**Official source:** [KB configuration](https://learn.microsoft.com/azure/search/agentic-retrieval-how-to-create-knowledge-base).
