# Plan and apply

## Quick starts

- "Check whether this machine is ready to build a GRZ sidecar."
- "Inspect the source index `<index>` and plan a GRZ build; show me the approval card."
- "Apply the approved plan and verify the new generation."

## Use this path

Use this path to go from a Search source index with stored chunk vectors to a verified, unpublished `grz-*` generation.

## Preflight

1. Run `grz-build --version`. If missing, read the [local runtime installation instructions](../../../README.md#install-the-local-runtimes) first. Install or run the shipped `runtime/grz-skills[azure,embed]` package through the Microsoft CFS feed. Check the [native prerequisite](../../../README.md#grz-native-runtime-prerequisite) before apply; this snapshot has no fixture fallback.
2. Run `grz-build doctor --json` (or `grz-skills-grz_doctor`) with the same `--tenant-id`, `--state-dir`, and Search flags you will use. Doctor only reads. Fix the first `fail` check using the top-level `next_step`; `warn` does not block.
3. For community naming, add `--naming-endpoint`, `--naming-deployment`, and `--naming-resource-group` to doctor. It lists models and does a read-only deployment GET, with no completion and no spend.

## Inspect and plan (`--backend azure`)

1. Tell the operator the tenant, subscription, resource group, and Search service, then run `inspect` and `plan`.
2. Show the plan's approval card verbatim. Say in one sentence that one new index is created from the source, the source is unchanged, and nothing goes live until publish is approved.
3. Add `--naming-*` flags to `plan` only when the operator wants community names; the card then lists the most it can call and spend.
4. Use `--reader` or `--drop-reader` only when the operator names a principal. If you re-plan, show the new card and ask again.
5. If `plan` stops with `SOURCE_VISIBILITY_UNVERIFIED`, the index has no visibility field. Ask the operator to confirm every document is public. Only after a yes, add `--source-visibility public-attested`, re-plan, show the new card, and pass the same flag to `apply`. It never overrides an existing field; map that with `--security-field`.
6. Use `--profile build-config-hnsw` when the source exceeds 4,096 chunks.

## Apply and verify

1. After `approved <plan-id>`, run `grz-build apply --plan-id <id> --approved-budget-bytes <bytes> --confirm-writes`, adding `--approve-model-calls` when the plan names communities.
2. Do not pass `--naming-*` or `--reader` flags to `apply`; the plan holds them. On `PLAN_BOUND_FLAG`, drop them and rerun.
3. Run `grz-build verify`. It reads every document back and returns the publish approval card. Stop there; publishing is a separate path.

## Return

Report the phase, exact plan ID, target index, whether the result is planned, applied, or verified, and the single safe next action. Never claim a plan proves access, quota, or readiness to publish.
