# Plan and publish

## Quick starts

- "Plan an EKG build for the BuildSpec at `<absolute-spec-path>`."
- "Plan the build with my OWL file as the ontology and show the exact approval card."
- "Publish the verified generation from this build."

## Use this path

Use this path when the user already has an EKG target and needs an exact Build plan, a new generation, or a verified publish step.

## Discovery

1. Confirm the tenant and that the task is about one specific BuildSpec.
2. Run `ekg-skills-ekg_doctor` first when the environment or sign-in state is unknown. It is read-only and reports one `next_step`.
3. Run `ekg-skills-ekg_ks_capabilities` for route uncertainty and `ekg-skills-ekg_source_inspect` on the exact BuildSpec before discussing writes.
4. Run `ekg-skills-ekg_build_plan` with the absolute `spec_path`. The tool validates the local version-1 BuildSpec offline, returns the exact plan ID, redacted scope, blocker or warning evidence, and `plan.estimates`.

## Ontology and source rules

- `ontology_mode: none` keeps a document-only build and never creates graph resources.
- `schema_org` uses the built-in ontology and needs no ontology file.
- `owl_file` uses the caller's OWL file and should normally offer a trial first.
- SharePoint graph routes and KB handoff stay unsupported; return the blocker instead of inventing a route.
- A source manifest changes the exact plan. Do not reuse a plan ID after source, target, identity, ontology, model, or journal changes.

## Approved write surface

If `ekg_build_plan` returns a plan without blockers and the user wants the change:

1. Show the CLI approval card exactly as reviewed.
2. Wait for `approved <plan-id>`.
3. Run the matching CLI command only after that exact reply:
   - `ekg-build apply` for a new build.
   - `ekg-build publish` after verification succeeds.
4. If publish is requested, confirm the build is verified first. Publish updates the current descriptor unless the operator explicitly keeps the previous current pointer.

If `ekg-build` is missing on PATH, read the [local runtime installation instructions](../../../README.md#install-the-local-runtimes) first. Install or run the shipped `runtime/ekg-skills[build,consume,provision]` package through the Microsoft CFS feed, then check `ekg-build --version`.

## Return

Report phase, exact plan ID, selected ontology mode, whether the result is offline planning or verified serving state, and the single safe next action. Never claim that planning alone proves entitlement, synchronization, or publish readiness.
