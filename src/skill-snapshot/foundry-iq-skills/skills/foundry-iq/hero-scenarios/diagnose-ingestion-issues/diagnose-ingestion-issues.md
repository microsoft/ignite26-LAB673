# Diagnose ingestion issues

## Activation

Existing missing files/stale facts/stalled processing: before
setup/quality, not new ingestion/sources/scaling/relevance-only tuning.
No parallel stack/blanket reset/permission reduction.

## Inputs and versions

Require app/runtime/files/change times/new facts/citations/freshness/query/deadline;
discover authorized service/index/KB/KS/pipeline/model/source/identity/network/
tenant/subscription/RG/region/tier/owner. Inventory aliases/private keys/children/
File IDs/stage/retry/verification; no unrelated docs.

Retain `dataApiVersion`/`managementApiVersion` under
[API version policy](../../references/api-version-policy.md): resolve gaps,
verify type/version/previews. Pass the resolved values unchanged
to every operation; other providers' versions are independent.
Apply [HTTP](../../references/http-contract.md),
[shared RBAC check](../../references/authentication-rbac.md).
Ask before granting missing permissions or provide administrator instructions.
No keys/public fallback or hidden data/privilege expansion.

## Observe first

| Path | Read-only evidence |
|---|---|
| Classic pull | GET I, I/search.status, D, S, X, app alias/query: source -> enrich -> writes -> app. |
| Managed KS | GET K, K/status, createdResources/generated diagnostics READ-ONLY. searchIndex: ingestion owner; remote/web: no local reset. |
| File | GET K/files; follow continuation/receipts. Synchronous/no indexer/schedule; baseline 100 files/50 MB each/minimal/no images/180s. |
| Push | Every item's status/statusCode/errorMessage; HTTP 207 partial failure, no indexer. |

Bind I=`/indexers('<name>')`, D=`/datasources('<name>')`,
S=`/skillsets('<name>')`, X=`/indexes('<name>')`, K=`/knowledgesources('<name>')`
on EXISTING endpoint; add `?api-version=<dataApiVersion>` to every URL.
Allowlist: hashed resource/key/identity/source/model refs, auth/network/schedule/
disabled/times/counts/status/queues/codes; no connectionStrings/credentials/keys/
tokens/auth headers/raw messages/enrichment trees/content.
Use [snapshot_diagnostics.py](../../references/context-resolution.md#script-paths);
pipe GET:

```powershell
python $snapshotScript --kind indexer-status --label affected-run
```

Match kind; no raw input/errors/transcript/debug/export/stderr.
Absent=unknown; snapshot isn't restore input.

BEFORE interruption/reset: lastResult/executionHistory/times/itemsProcessed/
itemsFailed/errors/warnings/currentState.mode/queues/runtime/limits; processed
isn't success. KS current/lastSynchronizationState times/counts/skips.
`status: running` isn't active; `lastResult.status: inProgress` is.
PERSISTED schedule.interval/startTime/disabled, KS
ingestionParameters.ingestionSchedule. Public status cannot prove internal lease/
worker ownership/next-run time; inferred windows never establish ownership.
No rerun while processing or run/reset pause/stop.
Beyond runtime limit/no progress: preserve state; escalate
`service-ownership-unobservable` with times/IDs.

## Classify

| Evidence | Decision |
|---|---|
| Enumeration/change/deletion | Scope/exclusions/time/tracking/last success; owner-scoped enumeration. Reset won't remove hard-deleted orphans. |
| Auth/network | [Access diagnosis](../diagnose-access-issues/diagnose-access-issues.md) only here, same principal/runtime/approval. |
| Format/size/parser | Type/tier/version/parsingMode/encoding/malformed/oversized/protected/truncated; no skips/failure-tolerance increases. |
| Content Understanding/custom skills | Standard extraction/analyzer/region/model/auth; text/image/table outputs in index; timeout/batch/concurrency/item errors. No text-only fallback. |
| Azure OpenAI latency/quota/429 | Issuer/quota/Retry-After/retries; two replay-safe resumes/deadline, never while processing. |
| Transform/write | Mappings/projections/key/type/vector dimensions/size/item errors; safe failed items/original action only. |
| App stale | Original alias/KB/filters/cache/pinned agent/referenced GET `/synonymmaps('<name>')`; ACLs/ranking retained. Code/cache: owner; quality AFTER freshness proof. |

Poll 20/40/80s backoff/Retry-After to deadline (default 10 min).
Eventual visibility within freshness window isn't failure; active/HTTP 200 isn't
completion, deadline isn't interruption approval.

## Approve and repair

Routine manual idle runs need no extra confirmation. Approve component/diff/
data movement/non-routine cost/production/schedule/ownership/recovery.
Re-read; unapproved writes block. REST: audience `https://search.azure.com`,
Bearer auth/HTTP attribution/request ID/JSON Content-Type. PUT full writable
source-of-truth + approved delta, `If-Match: <etag>`,
`Prefer: return=representation`; preserve unrelated settings/credentials.
409/412: discover; GET/compare diff. Unresolved POST: `operation-ambiguity`, no retry.

| Branch | Exact action/guard |
|---|---|
| Independent | PUT affected D/S/I delta. Schedule: 5 minutes-24 hours/UTC startTime. Proven idle non-triggering scheduler: disabled:true PUT -> GET/new ETag -> disabled:false PUT; schedule retained/new timing disclosed. Never stop active/enable intentionally-disabled jobs. |
| Managed | PUT K supported indexer-backed `<kind>Parameters.ingestionParameters` field/ingestionSchedule; preserve kind/scope/models/permissions, await sync. Inventory source-wide impact; source/version support or `managed-repair-blocked`. |
| Idle run | POST I/search.run, no body/no active job; reconcile new history before retry. |
| Doc reset | POST I/search.resetdocs, `{"documentKeys":["<key>"]}` OR `{"datasourceDocumentIds":["<id>"]}`, never both; `&overwrite=false`, foreign queues block. currentState -> idle run -> complete -> incremental cadence; verify keys. |
| Cache | POST S/search.resetskills, `{"skillNames":["<skill>"]}` -> idle run; approve ALL affected docs. |
| ACL resync | POST I/search.resync, `{"options":["permissions"]}`, supported type/version; all docs/permissions, not text. Idle run -> complete -> incremental cadence. |
| Push/orphan | POST X/docs/search.index, `{"value":[<failed-actions>]}`, original action/key/concurrency. Source-confirmed orphan/children: `{"value":[{"@search.action":"delete","<key-field>":"<key>"}]}`. Check EVERY item; never write generated indexes. |
| File | POST K/files: bytes/application/octet-stream, `Content-Disposition: attachment; filename="<safe-name>"`, private token; check fileId/size/errorMessage. Replace: DELETE K/files('<id>') -> upload, non-atomic. LIST before retry: name/size isn't byte proof; unknown POST/ownership: `upload-ambiguity`, no duplicate/indexer/blanket delete. |

Reset/resetskills/resync: independent pipelines only, never full reset.
Source/code/quota/schema/retrieval: `owner-action` until exact owner patch/
authority; retain evidence/target.

## Verify, recover and return

Completed run/sync AFTER change/resolved items/classified errors/new facts within
interval. Additions/updates/children: keys/versions; supported configured deletions/
children, else `deletion-unverified`. ORIGINAL app/agent/runtime/user/pinned
queries: NEW fact/original citation, no old/deleted fact/leakage.
Index/File receipt isn't app freshness.
Persisted schedule/disabled + NEXT scheduled run, else `schedule-unverified`/
inferred window; manual run isn't schedule health.

Resume receipts/state, never blind writes. Restore approved diff: same PUT/current
ETag/concurrency; missing config/credential blocks. Reset/resync/run/delete/upload
aren't reversible; report remainder. Preserve reused pipelines/KS/KBs/source/
unrelated docs. Only owned approved File duplicates: DELETE/verify absence/retained
files. Remove owned payloads/mappings per retention,
[scenario cleanup](../../references/safety-and-idempotency.md#scenario-cleanup).
Return diagnosis/inventory/repair/approvals/ownership/
verified freshness/citations/schedule/costs/versions/request IDs/recovery/
blockers: [output](../../references/output-contract.md).
Facts != hypotheses/changes/unverified outcomes.
