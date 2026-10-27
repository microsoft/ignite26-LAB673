# Build a production Foundry prompt agent from instructions, autonomously

Plan, build, verify and connect retrieval to an existing production Foundry
prompt agent, keeping consequential decisions approval-gated.

## When to use / do not use

Use for an outcome, not a prescribed architecture. Humans authenticate and
approve subscription/region and consequential choices. Compose existing
procedures; never replace the target agent unless requested.

## Inputs and discovery

Discover outcome, existing Foundry project/prompt agent, data, subscription,
approved regions and constraints. Inspect rather than assume permissions,
resource compatibility, ingestion, quality, extraction and networking. List/get permitted
[sources](../../operations/data-plane/knowledge-sources/list.md),
[KBs](../../operations/data-plane/knowledge-bases/list.md) and the
[service](../../operations/search-management/services/get.md) read-only
before deciding what to reuse vs. provision.

Use the [shared RBAC check](../../references/authentication-rbac.md) for every
resource. For permission blockers first use
[access diagnosis](../diagnose-access-issues/diagnose-access-issues.md).
Ask before granting missing permissions or provide administrator instructions.
Follow
[service provisioning](../../references/service-provisioning.md) for any new
or changed resource before version resolution.

## API version preflight

Before requests, resolve/reuse `managementApiVersion`, `dataApiVersion` and
binding's independent `connectionApiVersion` under
[API version policy](../../references/api-version-policy.md).
Record documented compatible overrides without a version-only permission question;
respect explicit pins/GA-only constraints. Disclose previews before mutations.

## Decide: architecture

Apply the [shared retrieval decisions](../../references/context-resolution.md#retrieval-setup-decisions)
to select extraction, classic/KB architecture, retrieval mode and reuse.
Recommend from discovered evidence; ask when confidence is low.

## Preflight: supportability before provisioning

Before any write, confirm the target agent's harness supports the decided
binding (classic: Azure AI Search tool definition; KB: KB-agent binding) —
unsupported harnesses block; KB MCP never attaches to a classic tool. Classic
libraries require the real [ingestion contract](../../references/classic-document-ingestion.md):
unsupported formats/permissions/pipelines block, never demo records substituted
for the customer's corpus. Auto-ingesting sources
need a verified private-at-creation contract when isolation is required;
otherwise block before creation. When discovery requires
network isolation, run the composed
[network-isolated preflight](../network-isolated-production-workflow/network-isolated-production-workflow.md#preflight-exact-composition-supportability-before-any-write);
otherwise confirm regional/SKU/quota support via
[service provisioning](../../references/service-provisioning.md). Stop and
report the incompatibility and smallest viable adjustment on failure; never
fall back to public access or keys.

## Consolidated approval

Consolidate environment/failures, architecture, reuse/provisioning, preflight,
costs, grants and ownership into one approval. Material recovery changes
require renewed identity/network/cutover approval.

## Execute

For isolation, establish approved private paths/managed identity before any
uploads or ingestion. Only empty definitions/disabled classic jobs may stage
first; never process private content in a temporary public phase.

1. Provision or reuse the Search service per
   [service provisioning](../../references/service-provisioning.md).
2. Branch by the decided architecture; never create a KS/KB solely to reach
   the classic tool:
   - **Classic Search:** ingest/reuse the actual corpus through
     [classic document ingestion](../../references/classic-document-ingestion.md).
     For hybrid/vector retrieval, apply the supported configuration from
     [vector search](../integrated-vector-search/integrated-vector-search.md)
     to the actual ingested documents.
   - **Knowledge Base:** create/reuse source(s) via the matching hero
     ([Blob](../agentic-search-blob-knowledge-source/agentic-search-blob-knowledge-source.md),
     [File](../agentic-search-file-knowledge-source/agentic-search-file-knowledge-source.md),
     [SharePoint](../sharepoint-knowledge-source/sharepoint-knowledge-source.md),
     [Search index](../search-index-knowledge-source/search-index-knowledge-source.md),
     [OneLake](../indexed-onelake-knowledge-source/indexed-onelake-knowledge-source.md))
     or the
     [multi-source hero](../multi-source-knowledge-base/multi-source-knowledge-base.md).
     Verify version compatibility for the **whole** KS→KB→retrieve lifecycle
     using [KB composition and retrieval](../../references/knowledge-base-retrieval.md).
3. Apply network isolation per the
   [network-isolated hero](../network-isolated-production-workflow/network-isolated-production-workflow.md)
   when discovery requires it.
4. Verify real ingestion/sync, freshness and known-fact/citation retrieval
   through the chosen architecture's contract.
5. Default to [lightweight manual verification](../../references/validation.md):
   bounded known-fact/citation, no-answer, source/freshness and actual-runtime
   allow/deny checks under routine-query limits, not datasets/cloud judges.
   Only an explicit evaluation/benchmark/quality-optimization request invokes
   the [Hill-Climb loop](../hill-climb-retrieval-quality/hill-climb-retrieval-quality.md)
   and its full verification gate. Pilot feedback is not production-ready
   assurance; never skip separately agreed production acceptance.
6. Connect to the production Foundry prompt agent: KB architecture uses the
   [agent-binding hero](../knowledge-base-foundry-prompt-agent/knowledge-base-foundry-prompt-agent.md)
   and [Foundry project connection](../../references/foundry-project-connection.md);
   classic Search uses the
   [Azure AI Search tool](../../references/foundry-ai-search-tool.md)
   instead — never the KB MCP path. Preserve existing instructions/model/tools/
   metadata and identity; draft verification is not a production cutover.
   For either binding, finish [production cutover](../../references/foundry-agent-cutover.md):
   approved baseline/release pinning, original-runtime canary and rollback.

## Recover from injected failures

Use the owning step's recovery for permission, compatibility, ingestion,
quality or networking failures. Repair only the affected resource with approval,
never full resets/public/key shortcuts. Unsupported outcomes need an explicit
blocker and smallest adjustment, not a silently substituted architecture.

## Verify and deliver

Verify through the connected production agent and provide the
[customer handoff](../../references/output-contract.md#customer-handoff):
architecture rationale, sanitized security/network summary and
verification/supportability results (Hill-Climb only if run).

On teardown, follow
[scenario cleanup](../../references/safety-and-idempotency.md#scenario-cleanup),
delegating to each composed hero's cleanup in reverse dependency order
(agent binding, KB, sources, network, service); never delete the
pre-existing production agent.

**Official source:** [Agentic retrieval overview](https://learn.microsoft.com/azure/search/search-agentic-retrieval-concept-overview).
