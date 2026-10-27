# Plan and apply

## Quick starts

- "Check whether this machine is ready to build a GRZ sidecar."
- "Inspect the source index `<index>` and plan a GRZ build; show me the approval card."
- "Apply the approved plan and verify the new generation."

## Use this path

Use this path to go from a Search source index with stored chunk vectors to a verified, unpublished `grz-*` generation.

## Preflight

1. Follow [runtime setup](../../graph-guide/references/install-and-checks.md#plugin-and-clis): explicit `setup grz`, then `run grz grz-build --help`. Retain the launcher prefix on later commands; warm run never installs.
   Community generation also requires the [separate pinned native binary](native-runtime.md).
2. Put global flags **before** the verb: `grz-build --state-dir <absolute-state> --tenant-id <tenant> <Search/source flags> doctor --json`. Retain that scope on every command. Doctor only reads. Follow the first `fail` check's `next_step`; `warn` does not block.
3. For community naming, add `--naming-endpoint`, `--naming-deployment`, and `--naming-resource-group` to doctor. It lists models and does a read-only deployment GET, with no completion and no spend.

## Inspect and plan

1. Tell the operator the tenant, subscription, resource group, and Search service, then run `inspect` and `plan`.
2. Show the plan's approval card verbatim. Say in one sentence that one new index is created from the source, the source is unchanged, and nothing goes live until publish is approved.
3. Add `--naming-*` flags to `plan` only when the operator wants community names; the card then lists the most it can call and spend.
4. Use `--reader` or `--drop-reader` only when the operator names a principal. If you re-plan, show the new card and ask again.
5. If `plan` stops with `SOURCE_VISIBILITY_UNVERIFIED`, the index has no visibility field. Ask the operator to confirm every document is public. Only after a yes, add `--source-visibility public-attested`, re-plan, show the new card, and pass the same flag to `apply`. It never overrides an existing field; map that with `--security-field`.
6. Use `--profile build-config-hnsw` when the source exceeds 4,096 chunks.

For an active managed producer, the distinct [captured-input path](captured-input.md)
requires explicit selection and acceptance of non-atomic capture; never invent freeze evidence.

Unknown, malformed or exhausted Search quotas block planning; inspection never treats missing statistics as zero.
For ARM-verified Serverless services reporting null aggregate storage/vector
quotas, inspection instead requires finite per-index storage/vector limits,
two-times estimated size margins, and a free index slot. Aggregate quotas remain
explicitly unreported, not unlimited; missing or insufficient per-index limits
still block.
Serverless selects `2026-08-01-preview` and binds that API into the source
plan because older statistics omit its per-index vector limit. Dedicated
services keep `2026-04-01`; there is no fallback.
Serverless Build cards separate any model-only budget from unknown, billable
compute/indexed-storage usage; zero model calls does not mean no ongoing cost.

For native-direct use, the physical key must be retrievable, sortable **and filterable**.
A managed `uid` that is only retrievable/sortable cannot support continuation
scans. Native admission also checks an explicit cosine HNSW profile, no
compression, and stored retrievable float32 vectors. It reports the actual
metric/compression; unknown or incompatible metadata blocks before export/native
execution. This is this adapter's conservative schema policy, not a claim that
every quantized index is invalid for all native implementations, nor proof of
coverage or publication. Do not mutate a managed field or automatically make a
task index. Any separately approved compatible replacement needs verified content,
embedding identity, stored vectors and visibility; preserve the original source.

Naming binds model-specific request defaults into the approved plan; non-reasoning
models omit reasoning effort, and supported reasoning models use their pinned
default rather than universally forcing `minimal` or `low`. Unknown model names
block. The pinned Chat Completions policy omits effort for4.x, uses `minimal`
only for GPT-5/mini/nano, and `low` for admitted versioned5.x models.
GPT-6 naming is blocked until support for this exact transport/API is established;
Search graph model-name admission or a Responses catalog entry is not that proof.
Doctor's observed deployment model must match the supplied `--naming-model`;
policy admission does not prove a completion will succeed.
Both finite nonnegative token prices are required. Incomplete usage or an
ambiguous request outcome stops further calls and leaves total cost **UNKNOWN**,
retaining the known subtotal in operator evidence. Review provider usage before
approving another budget. Reserve estimates are not Azure billing.

## Apply and verify

1. After `approved <plan-id>`, run `grz-build apply --plan-id <id> --approved-budget-bytes <bytes> --confirm-writes`, adding `--approve-model-calls` when the plan names communities.
2. Do not pass `--naming-*` or `--reader` flags to `apply`; the plan holds them. On `PLAN_BOUND_FLAG`, drop them and rerun.
3. Run `grz-build verify`. It reads every document back and returns the publish approval card. Stop there; publishing is a separate path.

Uploads are bounded by document count and a 15 MiB complete JSON request budget.
`PUBLICATION_DOCUMENT_TOO_LARGE` requires reducing the named document payload, not retrying it.
After a partial upload failure, use reconcile; confirmed sub-batches are not rolled back or blindly retried.

## Return

Report the phase, exact plan ID, target index, whether the result is planned, applied, or verified, and the single safe next action. Never claim a plan proves access, quota, or readiness to publish.
