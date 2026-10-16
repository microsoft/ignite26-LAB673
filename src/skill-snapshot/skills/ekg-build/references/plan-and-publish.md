# Plan and publish

## Quick starts

- "Build an EKG from the documents in `<folder>`."
- "Plan the build with my OWL file and show the approval card."
- "Publish the verified generation."

## Use this path

Use this path to go from a document source and an existing Azure target to an approved plan, a verified generation, and a published descriptor.

## Preflight

1. Run `ekg-build --version`. If missing, show `uv tool install --python 3.12 "<plugin-root>/runtime/ekg-skills[build,consume,provision]"` and wait for the operator; never self-install. If uv is missing, point to https://docs.astral.sh/uv/getting-started/installation/. Use the approved feed when required.
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

Report phase, exact plan ID, ontology mode, whether the result is offline planning or verified state, and one safe next action.
