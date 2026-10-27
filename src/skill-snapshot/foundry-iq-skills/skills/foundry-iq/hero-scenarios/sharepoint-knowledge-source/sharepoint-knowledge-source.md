# Answer from SharePoint content with per-user permissions

Ground SharePoint content with per-user entitlement, not a shared tenant view.

## When to use / do not use

Use for SharePoint-derived answers scoped to each employee's entitlement.
Discover tenant/sites/libraries/Lists/ASPX pages/subsites, target users and
groups, expected questions and freshness. A KB plans across documents and
enforces citations; prefer classic Search only for bounded keyword lookup.
Use [Blob](../agentic-search-blob-knowledge-source/agentic-search-blob-knowledge-source.md)
or [File](../agentic-search-file-knowledge-source/agentic-search-file-knowledge-source.md)
for non-SharePoint storage. Failure diagnosis and quality tuning are separate
routes.

**Remote vs. indexed:** both supported; pick one, never both for the same
content. Choose **Remote** (`remoteSharePoint`, preview) only when every
target user holds an M365 Copilot add-on or Retrieval API pay-as-you-go
(preview), SharePoint/Search share one Entra tenant, and the workload is
textual with no retrieval-control need — see the
[Remote guide](../../references/knowledge-sources/remote-sharepoint.md) for
prerequisites/limits. Otherwise choose **Indexed** (`indexedSharePoint`) —
see the [Indexed guide](../../references/knowledge-sources/indexed-sharepoint.md).
A mix of eligible/ineligible users for Remote is a reportable split, not a
silent fallback or a leaked grant to ineligible users.

## Inputs and access

Reuse a compatible existing Search service unless isolation is requested.
Follow [service provisioning](../../references/service-provisioning.md) before
version resolution. Resolve the SharePoint tenant/site, two test users with
different entitlements, a known in-scope fact and ownership.

**Remote-specific:** verify service region, per-user Copilot add-on/paygo
entitlement and same-tenant alignment; an ineligible user blocks only that
user, not the whole hero.

**Indexed-specific:** confirm these prerequisites:
- Approved library/Lists/ASPX/subsite scope and `Sites.Selected` grants;
  whole-site approval when scope is empty/omitted.
- Search managed identity/federated credential, Entra app permissions and
  tenant admin consent.
- Permission ingestion, query-time group resolution and differently entitled test users.
- Compatible embedding deployment and model-account inference access.

List/get permitted [sources](../../operations/data-plane/knowledge-sources/list.md)
and [KBs](../../operations/data-plane/knowledge-bases/list.md) read-only;
confirm governed reuse and delegate SharePoint/Entra-application lifecycle to
their owners.

Use the [shared RBAC check](../../references/authentication-rbac.md) for
caller **Search Service Contributor** (both paths; Indexed additionally needs
**Search Index Data Contributor** for the ingestion pipeline), plus Search
Index Data Reader for retrieval. Search RBAC does not grant SharePoint
access: Indexed needs separate Graph/SharePoint app/consent/site-grant
verification; Remote needs per-user licensing/paygo verification. Indexed
also needs Cognitive Services User or Foundry User on the model account.
Ask before granting missing permissions or provide administrator instructions.

Approve generated resources, preview status (Remote) or exact scope and ACL
ingestion decision (Indexed), extraction/model costs (Indexed),
licensing/paygo billing (Remote), schedule, missing grants, network changes
and ownership together. Ingestion credentials alone do not preserve
end-user access; verify query-time ACL enforcement first.

## API version preflight

Resolve `managementApiVersion`/`dataApiVersion` under
[API version policy](../../references/api-version-policy.md).
Use its Remote SharePoint lifecycle contract for that path; honor explicit
constraints and include preview use in mutation approval.

## Execute

1. Inspect [service get](../../operations/search-management/services/get.md)
   (`Services_Get`) for readiness, identity and access. Use
   [service create/update](../../operations/search-management/services/create-or-update.md)
   only for a new service or approved changes; wait for
   `provisioningState: succeeded`.
2. Reuse an unchanged compatible source, or run
   [KS create/update](../../operations/data-plane/knowledge-sources/create-or-update.md)
   (`KnowledgeSources_CreateOrUpdate`) with `If-None-Match: *` for creation and
   `Prefer: return=representation`. **Remote:** the
   [Remote contract](../../references/knowledge-sources/remote-sharepoint.md),
   resolved version, approved `filterExpression`. **Indexed:** the
   [Indexed contract](../../references/knowledge-sources/indexed-sharepoint.md)
   with `dataApiVersion`; preserve settings/current ETags on update; scope
   `containerName`/`query` to the approved set; use Content Understanding
   Standard only when needed and approved.
3. Compare effective readback, normalizing documented defaults. Indexed returns `createdResources` (data
   source, skillset, indexer, index); Remote returns none — queryable
   immediately.
4. **Indexed only:** poll
   [source status](../../operations/data-plane/knowledge-sources/get-status.md)
   with bounded backoff/deadline. Require completed synchronization, zero
   `itemsUpdatesFailed` and expected content for a new nonempty corpus.
   Diagnose a stalled/failing sync against its actual dependency
   (identity/consent/site grant/group resolution/content type), not a
   generic permission error.
5. Use [KB composition and cited retrieval](../../references/knowledge-base-retrieval.md)
   with `kind: remoteSharePoint` or `indexedSharePoint` to match the created
   source, required-source errors and references.

## Verify and clean up

Require the known fact, matching SharePoint reference and no errors. Run
trial queries as each test user: pass each user's token in
`x-ms-query-source-authorization` and confirm the allowed user receives
authorized content/citations while the denied user receives neither in
results, answers or citations. **Indexed:** change a document or permission
and repeat both checks after the expected synchronization interval to
confirm content and permission freshness. **Remote:** repeat both checks
immediately (no sync wait) since enforcement is per request. Do not equate
HTTP success with supported citations, and do not claim ACL enforcement from
ingestion credentials alone.

For permission blockers first use
[access diagnosis](../diagnose-access-issues/diagnose-access-issues.md).
For Indexed failures, use
[ingestion diagnosis](../diagnose-ingestion-issues/diagnose-ingestion-issues.md)
without changing generated assets. Inspect SharePoint
app/consent/site-grant state, group resolution, network and freshness. For
Remote failures, inspect licensing/paygo state and filter syntax. Repair only
approved resources; no full reset, broader scope, key fallback, or parallel
pipeline. If the request includes an existing Foundry prompt agent, compose
the [agent hero](../knowledge-base-foundry-prompt-agent/knowledge-base-foundry-prompt-agent.md)
after direct retrieval and both allow/deny checks pass, using
`--per-user-authorization` so each signed-in user's token drives retrieval.

On a teardown request, follow
[scenario cleanup](../../references/safety-and-idempotency.md#scenario-cleanup):
delete the owned [KB](../../operations/data-plane/knowledge-bases/delete.md)
before its [KS](../../operations/data-plane/knowledge-sources/delete.md).
Indexed KS deletion removes generated assets; do not pre-delete the index.
Never delete SharePoint originals, groups, or the Entra app registration.

**Official sources:** [Remote SharePoint knowledge sources](https://learn.microsoft.com/azure/search/agentic-knowledge-source-how-to-sharepoint-remote),
[Indexed SharePoint knowledge sources](https://learn.microsoft.com/azure/search/agentic-knowledge-source-how-to-sharepoint-indexed),
[Indexer prerequisites](https://learn.microsoft.com/azure/search/search-how-to-index-sharepoint-online).
