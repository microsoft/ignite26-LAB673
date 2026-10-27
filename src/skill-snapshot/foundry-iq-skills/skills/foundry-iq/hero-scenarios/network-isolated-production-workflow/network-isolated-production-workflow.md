# Deploy a network-isolated production workflow

Preserve classic/KB behavior; prove whole-workflow isolation support before writes.

## When to use / do not use

Use when an existing prototype must run in production with no public network
exposure: "Deploy this into our regulated environment with no public
endpoint." Preserve the architecture best suited to the workload: retain
classic Search for bounded keyword/Q&A, or deploy existing Knowledge
Sources/KB for agentic retrieval; production alone does not mandate a KB
move. Do not rebuild the architecture to "make it production."
[Autonomous](../instruction-to-production-agent/instruction-to-production-agent.md)
satisfies this preflight if it already ran it for the same composition.

## Inputs and discovery

Discover the requested application, Foundry project/agent and Search service,
then follow their referenced sources, models and endpoints. Prioritize supplied
resource IDs and resource-group/type-scoped lists for gaps.
Record the retained classic/KB architecture, subscription/resource group,
region/regulatory constraints. Inventory each dependency's
SKU/region/features, identity, private DNS/routing, firewalls and outbound access. Follow
[service provisioning](../../references/service-provisioning.md) for any
missing/changed Search resource; private-link indexer execution
**requires dedicated S2+** — verify before relying on it.

Use the [shared RBAC check](../../references/authentication-rbac.md) for
every dependency's managed identity across Search, Foundry, and each
source's ingestion identity; least privilege applies inside the isolated
network as publicly. Ask before granting missing permissions or provide administrator instructions.

## API version preflight

Follow [API version policy](../../references/api-version-policy.md) to resolve
`managementApiVersion`/`dataApiVersion` before the first request; reuse
values resolved by the preserved architecture's own hero. Resolve
`connectionApiVersion` via [Foundry project connection](../../references/foundry-project-connection.md)
only if an agent binding is in scope. Pass resolved values unchanged and
verify private-network feature support before mutating.

## Preflight: exact composition supportability (before any write)

Check the **complete composed architecture**; separate component support
does not prove isolated composition support:
1. **Regional availability** of every required Search SKU/feature,
   Foundry/agent surface, model/embedding deployment and enterprise source.
2. **SKU/feature compatibility**: confirm the SKU supports the requested
   private-link/private-execution combination (S2+ for private indexer
   execution) and the retained architecture's required features (semantic
   ranking, vectors, agentic retrieval).
3. **Quota** for model deployments, Search units, and any APIM/custom-
   endpoint dependency; existing quota does not guarantee capacity.
4. **Private networking.** Confirm private-endpoint, private DNS, firewall,
   routing and outbound-dependency requirements for Search, Foundry/MCP,
   model endpoints, and every source's ingestion identity (Blob/SharePoint/
   OneLake indexer `executionEnvironment` must support `private` where used).
5. **Managed identity and least-privilege RBAC** across every dependency.
6. **Known preview limitations** for this composition.

Record each dependency's actual public-access, private routing/DNS, identity
and enforcement evidence. Search private links do not isolate Foundry, models,
storage, SharePoint/Web or APIM. Missing non-Search support, execution surface
or owner authority blocks the whole-workflow isolation claim before writes.
On failure, stop and propose the smallest viable adjustment; never public/key
fallback or an unsupported substitution.

## Execute

1. Inspect read-only: [service get](../../operations/search-management/services/get.md),
   [private endpoint connections list](../../operations/search-management/private-endpoint-connections/list-by-service.md),
   [shared private link resources list](../../operations/search-management/shared-private-link-resources/list-by-service.md),
   and [NSP configuration](../../operations/search-management/network-security-perimeter-configurations/get.md)
   if applicable.
2. For the approved composition, apply changes in dependency order with
   consolidated approval for permission/architecture/region/SKU/cost changes.
   Configure managed identities and least-privilege RBAC. Create or hand off
   the inbound private endpoint per
   [inbound private endpoint/DNS](../../references/networking.md#inbound-private-endpoint-and-dns-creation-surface)
   (needs Network Contributor, not a Search permission); then
   [approve the connection](../../operations/search-management/private-endpoint-connections/update.md)
   (`PrivateEndpointConnections_Update` — Search never creates the request);
   create outbound [shared private link resources](../../operations/search-management/shared-private-link-resources/create-or-update.md)
   (`SharedPrivateLinkResources_CreateOrUpdate`) per private dependency; set
   each indexer's `executionEnvironment: private` via an approved
   [indexer update](../../operations/data-plane/indexers/create-or-update.md)
   only where verified, and only on an indexer this hero owns — never a
   classic-owned or KS-generated indexer absent verified authority;
   reconcile the [NSP configuration](../../operations/search-management/network-security-perimeter-configurations/reconcile.md)
   if in scope. Preserve the retained classic/KB definitions unchanged.
3. Wait for `Approved`/`Succeeded` states on every private endpoint and shared
   private link; pending approval is not success per
   [networking](../../references/networking.md).
4. Run a managed-identity canary over the private path (through the
   deployed app/agent) before removing public access. Disable public
   exposure via an approved
   [service update](../../operations/search-management/services/update.md)
   (`Services_Update`): set `properties.publicNetworkAccess` to `disabled`,
   read back with `Services_Get`, and rerun the canary. Then PATCH
   `{"properties":{"disableLocalAuth":true}}` without `authOptions`, per
   [roles-only cutover](../../references/networking.md#search-roles-only-cutover):
   readback must show `disableLocalAuth:true` and `authOptions:null`.
   **Re-run the canary after `disableLocalAuth` takes effect**; the earlier
   network-only run is insufficient. Never send `aadOrApiKey` with
   `disableLocalAuth:true` or mutate extra indexers.

## Verify and clean up

Validate DNS and connectivity **from the actual execution environment**
(the deployed app/agent's network), not a developer laptop; use
[private networking and DNS diagnosis](../../troubleshooting/private-network-dns.md)
for any failing hop. For permission blockers use
[access diagnosis](../diagnose-access-issues/diagnose-access-issues.md).
Run ingestion/synchronization through the private path
and end-to-end trial queries through the agent/app. Produce a
supportability-preflight report, identity/network summary, architecture
inventory, retrieval evidence and unresolved limitations as the artifact.

On a teardown or re-scoping request, follow
[scenario cleanup](../../references/safety-and-idempotency.md#scenario-cleanup):
network changes need an explicit impact statement before removal, since
private endpoints/shared private links can affect other consumers. Record
prior `publicNetworkAccess`/`disableLocalAuth`/`authOptions` values before
this hero's write so an approved rollback restores them exactly; never
widen deletion scope or re-enable public access/keys beyond the approved
restore — stop and report remaining dependents instead.

**Official sources:** [Inbound private endpoint/DNS](https://learn.microsoft.com/azure/search/service-create-private-endpoint),
[Outbound shared private links](https://learn.microsoft.com/azure/search/search-indexer-howto-access-private).
