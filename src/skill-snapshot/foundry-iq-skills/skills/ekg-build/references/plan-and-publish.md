# Plan and publish

## Quick starts

- "Build an EKG from the documents in `<folder>`."
- "Plan the build with my OWL file and show the approval card."
- "Publish the verified generation."

## Use this path

Use this path to go from a document source and an existing Azure target to an approved plan, a verified generation, and a published descriptor.

## Preflight

1. Follow [runtime setup](../../graph-guide/references/install-and-checks.md#plugin-and-clis): explicit `setup ekg`, then `run ekg ekg-build --help`. Retain the launcher prefix on later commands; warm run never installs.
2. Run `ekg-build doctor --json`, adding `--tenant-id`, `--build-journal`, and `--descriptor` when known. It is read-only.
3. Use `ekg-provision` to create or connect a target first. Retain the ready Connect result's `build_binding.build_args` array unchanged; it includes observed endpoints, ARM IDs, identity, deployments, models and dimensions.

## Plan

1. `ekg-build inventory --source-kind local_path --source-reference <absolute-folder> --output <absolute-new-manifest.json> --json`.
2. `ekg-build plan <build_binding.build_args> --source-kind local_path --source-reference <absolute-folder> --source-manifest <saved-manifest.json> --build-journal <absolute-new-file outside the folder> --json`.
3. Target flags: `--tenant-id`, `--subscription-id`, `--resource-group`, `--location`, the Search, Storage, and OpenAI endpoints and ARM IDs, `--search-identity-resource-id`, both deployments and models, `--storage-container`, `--search-sku`.
4. Choose one ontology route:
   - `none`: document-only, creates no graph resources.
   - `--ontology schema_org`: built-in business ontology.
   - `--ontology owl_file --ontology-path <owl>`: the user's classes; offer a trial first.
   Add `--graph` for multi-hop retrieval. Ontology selection alone does not enable it; keep the flag through apply, reconcile, verify and publish.
5. Never combine legacy `--corpus` with any `--source-*` flag.
6. A changed endpoint, source, model, or ontology changes the plan ID and needs fresh approval.

New managed extraction plans bind requested page parallelism 64 (supported
range 1..64); `--extraction-parallelism` preserves an explicit override. Retain
the resolved `extraction_parallelism` in exact-spec MCP plans and through apply.
Historical stored omissions still mean 4 during exact-plan reconciliation:
never retune or replay an old approval. Generated packing and effective model
concurrency require service readback; 64 is not 64 documents or guaranteed 16x speed.

For new managed extraction plans, the CLI resolves an omitted output budget to
the documented model maximum before plan identity and approval (GPT-5-mini:
128,000). `--extraction-max-tokens <positive-int32>` supplies an explicit budget.
Unknown model limits block; omission is never interpreted as "maximum" when
reading a stored spec. Persist the resolved number as `extraction_max_tokens`
in a new BuildSpec before using the exact-spec MCP plan adapter, and retain it
through apply/reconciliation. Historical unset values/identities remain unchanged;
documents-only updates keep the published budget. A changed budget needs a rebuild.
Model/context, throughput and effective service limits still need verification:
the model maximum is not a proven Search limit or quality fix. Time and cost are
unmeasured without a matching trial. Never patch generated skills.

For Serverless, a model extraction estimate is not an all-in price. Compute Units,
indexed storage, Blob and model usage remain billable; total and ongoing costs are
unknown, not zero. Cost presentation alone does not change an approved plan or
authorize resubmission.

Graph planning checks the chat model against the pinned Search API's model-name
policy before staging or uploading. Deployment availability alone does not imply
Search support: `gpt-6-luna` is not admitted by the `2026-08-01-preview` policy;
`gpt-5.6-luna` is. Unknown models fail closed. A policy change requires a new
approval; admission is not proof of inference access, capacity or graph quality.

For canonical IDs, select `--grounding-index <name>` before planning. Give the independent
producer this plan's `grounding.graph_name`, index and Search endpoint. Initial missing-index
diagnostics are not approval. Once its readiness check passes, re-plan with unchanged build
inputs and review the new card; never copy a graph name from an ungrounded plan.

## Apply and publish

1. Retain the exact source manifest/digest, target binding, ontology file/hash, journal and returned `plan_id`. Show the card; after `approved <plan-id>`, replace only the `plan` verb with `apply`, retain its inputs, and add `--plan-id <id> --confirm-writes --wait`.
2. `APPLY_INCOMPLETE` or an uncertain result is not success: use `progress`, `reconcile`, then `verify` with the same build inputs, not the approval/wait flags. Never reapply around uncertainty. For local status read `run_id` from that journal; do not substitute the plan ID.
3. `ekg-build publish` with those same build inputs writes the descriptor under `~/.ekg/descriptors` (or `$EKG_HOME`) and marks it current. Retain its returned descriptor path. `--keep-current` preserves the old current pointer.
4. Pass the serving descriptor as `--descriptor` on later plans so reader grants carry forward.

## Return

Indexed ontology GETs may omit `endpoint`, `apiKey`, `authIdentity` or return null.
Other extra fields, non-null values, malformed objects or mismatched graph/index
names block verification. Inline JSON-LD comparison stays exact.

Report phase, exact plan ID, ontology mode, whether the result is offline planning or verified state, and one safe next action.
