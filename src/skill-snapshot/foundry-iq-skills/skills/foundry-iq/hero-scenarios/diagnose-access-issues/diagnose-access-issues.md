# Diagnose access issues

## Activation

Use for an existing app's denied documents or connectivity: 401/403/DNS/timeouts
before setup/quality; not new grounding, unrelated sign-in, tuning or hardening.

## Inputs and versions

Capture ORIGINAL method/operation/path aliases/UTC time/status/error/correlation
ID, principal/failing environment; body/filters/user context stay private.
Discover authorized app/project/pinned agent/connection/KB/KS/Search/index/pipeline/
dependencies/tenant/subscription/region/source/network.
Owner: missing entitlement/runtime/safe-replay facts.

Retain `managementApiVersion`/`dataApiVersion` under
[API version policy](../../references/api-version-policy.md): resolve gaps,
verify contracts, disclose previews.
Pass the resolved values unchanged to every operation.
Independent: connection ARM `2025-10-01-preview`, agent `v1`, Graph `v1.0`.
Apply [HTTP](../../references/http-contract.md) attribution/request IDs,
[shared RBAC check](../../references/authentication-rbac.md).
Ask before granting missing permissions or provide administrator instructions.

## Observe and snapshot

Ledger EACH hop: user/app/managed identity -> Foundry project/agent connection ->
KB MCP/Search -> source/model: principal/tenant, system/user-assigned identity/app,
target/audience/operation/evidence. Private `tid/oid/appid/azp/aud/exp` aren't
signature/access proof; correlate runtime telemetry. Absent evidence is unknown.

Catalog GETs: service/KB/KS/pipeline/private links, in memory.
Connection GET: `https://management.azure.com<project-id>/connections/<name>?api-version=2025-10-01-preview`;
check RemoteTool/ProjectManagedIdentity, sharing, Search audience,
`<search-endpoint>/knowledgebases/<kb>/mcp?api-version=<dataApiVersion>`.
`AIProjectClient(endpoint=..., credential=..., api_version="v1",
allow_preview=True).agents.get_version(agent_name, agent_version)` reads PINNED
MCP connection/tools/approval, no model invocation.

Allowlist: hashed resource/pipeline/agent/connection/source/model/identity refs,
ETags/versions, role ID/scope/type/condition presence, app grant IDs/scopes/consent,
DNS/IP hashes/TCP443/auth/network/link states/schedule/status times/counts.
No connectionStrings/credentials/keys/tokens/auth headers/encryption credentials/
instructions/private content/raw errors/warnings.
Resolve [snapshot_diagnostics.py](../../references/context-resolution.md#script-paths)
from the loaded skill; pipe GET through its fixed allowlist:

```powershell
python $snapshotScript --kind knowledge-source --label affected-source
```

Choose actual kind; same allowlist for DNS/app grants. No raw client errors/
stderr/transcript/debug/files; missing is unknown, snapshot isn't restore input.

## Classify

| Observation | Discriminator and next action |
|---|---|
| 401/auth-like 403 | Check actual tenant/audience/expiry and authOptions/failure mode; refresh ORIGINAL credential flow only. Status alone isn't missing RBAC. |
| Search/ARM 403 | Control-plane Actions vs data-plane DataActions. `az role assignment list --assignee $principalId --scope $scope --include-inherited`; definitions/groups/conditions/denies/PIM/propagation. Graph/effective-access gaps block proof, not authorize wider access. |
| Dependency | Selected KS/data source/skill/model identity: Blob read, model inference, SharePoint app permissions/consent/site grants, Fabric workspace grants differ. |
| Foundry/MCP | Caller Foundry permissions, project-to-Search role, end-user x-ms-query-source-authorization. Project identity isn't entitlement; missing token/ACL metadata mustn't yield unfiltered results. |
| DNS/TCP/firewall-like 403 | ORIGINAL runtime: `nslookup <hostname>`; Windows `Test-NetConnection <hostname> -Port 443`. DNS/VNet/forwarding/IP/TLS/proxy/routes/NSG/firewall/public-network/outbound; ordinary hostname. Laptop success isn't proof. |

Inbound doesn't provide outbound access. Check execution environment, shared
private-link target/group/Approved/Succeeded, dependency approval, region/tier/
version. [Network diagnosis](../../troubleshooting/private-network-dns.md) only
here. Unsupported composition blocks, never public fallback.

## Approve and repair

Approve evidence-supported minimal principal/permission/scope/network diff,
user/data/production impact, non-routine cost/deadline, ownership/recovery.
Verify authority; otherwise approval-required/owner-action, no write.
Reuse equivalent/inherited access; approved IDs only. Scope beyond authorized
principal boundary blocks; verify CLI `--help`.

| Evidence-selected repair | Exact execution contract and readback |
|---|---|
| Missing role | `az role assignment create --assignee-object-id $principalId --assignee-principal-type $principalType --role $roleId --scope $scope --name $assignmentGuid --output none`; list/compare principal/type/role/narrowest supported scope. Search Index Data Reader for retrieval; dependency roles on dependencies. Service-wide Reader exposes all indexes/KBs: unacceptable exposure blocks grant. |
| One site grant | Effective Sites.Selected consent/source matrix. Graph `POST https://graph.microsoft.com/v1.0/sites/<site-id>/permissions`, `{"roles":["read"],"grantedToIdentities":[{"application":{"id":"<app-id>","displayName":"<name>"}}]}`. GET same site's permissions/retain ID. Whole-site reach; Graph audience/existing admin authority required. Never grant this agent Sites.FullControl.All. |
| Existing inbound approval | PUT `https://management.azure.com<connection-id>?api-version=<managementApiVersion>`, `{"properties":{"privateLinkServiceConnectionState":{"status":"Approved","description":"<change-id>"}}}`; GET same state. No confirmed ETag guarantee: serialize/reconcile with owner. |
| Missing DNS VNet link | `az network private-dns link vnet create --subscription $dnsSubscription --resource-group $dnsGroup --zone-name privatelink.search.windows.net --name $linkName --virtual-network $runtimeVnetId --registration-enabled false --output none`; show same link/verify target/Succeeded. Recheck absence; no overwrite/public-resolution fallback. |

Other PIM/consent/federation/identity/app/connection/agent/route/firewall/outbound:
exact owner patch/authority, else `owner-action` with target/diff.
No keys/public access/rotation/architecture swaps/agent-version edits/broad grants/
approval bypass.

## Verify, recover and return

Propagation/refresh: three spaced replays maximum/deadline (default 10 minutes),
Retry-After; longer caches: `propagation-unverified`, not another grant.
Reconcile uncertain writes by GET/list; 409/412 requires discovery.
Replay ORIGINAL request as ORIGINAL principal in ORIGINAL environment, unchanged
filters/user context/pinned version. Unsafe replay needs state check/approval;
missing runtime: `original-replay-blocked`. Require success, authorized fact/
citation, no dependency errors and differently entitled user's denial/no protected
results. Unauthorized users remain denied; absent negative identity:
unverified authorization. HTTP 200/grant isn't proof.

Approved rollback removes ONLY owned unused changes:
`az role assignment delete --ids $ownedAssignmentId`; Graph DELETE same site's
`/permissions/<owned-id>` with documented admin authority; DNS `az network
private-dns link vnet delete --subscription $dnsSubscription --resource-group $dnsGroup
--zone-name privatelink.search.windows.net --name $linkName --yes`.
Verify absence/retained access; endpoint rollback requires supported owner-approved
transition via same PUT, else owner-action; never deletion.
Preserve unrelated grants/connections/sources/agent versions; remove owned local
payloads/mappings per retention, [scenario cleanup](../../references/safety-and-idempotency.md#scenario-cleanup).
Return snapshot/ledger/confidence/diff/approvals/owned-vs-reused,
original/negative checks/versions/request IDs/recovery/blockers:
[output](../../references/output-contract.md). Facts/hypotheses/changes/
unverified outcomes/owner actions stay distinct.
