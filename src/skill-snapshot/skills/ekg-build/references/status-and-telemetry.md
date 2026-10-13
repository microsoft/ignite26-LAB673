# Status and telemetry

## Use this path

Use this path for environment checks, local journal status, progress interpretation, timings, and generation protection.

## Read-only surfaces

- `ekg-skills-ekg_doctor`: environment, tenant match, descriptor, reader probe, models-list probe, and deployment metadata checks. Missing inputs show `skip`.
- `ekg-skills-ekg_build_status`: reads only the exact local journal for the supplied BuildSpec. If the BuildSpec used relative paths, also supply the original absolute `working_directory`.
- `ekg-skills-ekg_build_telemetry`: summarizes local build timings and optional consume telemetry from local files only.
- `ekg-skills-ekg_build_generations`: lists live generations and which descriptor paths protect them.

## Interpretation rules

- A verified journal is historical evidence, not a fresh statement that the service is still serving.
- If service-side synchronization is missing from telemetry, say so and direct the operator to reconcile or read progress before interpreting timings.
- `ekg_build_generations` protects only the descriptor paths you pass. If the serving descriptor set is incomplete, say that cleanup advice is incomplete too.
- When the CLI surface is needed for deeper diagnosis, use `ekg-build progress`, `ekg-build attribution`, or `ekg-build reconcile`; these remain read-only until a later approved write path is chosen.

## Return

Report exact phase, what source of truth you used, any uncertainty the tool returned, and one safe next action. Never expose journal contents, secrets, or raw document text unless the user explicitly asks.
