# Health and capabilities

## Use this path

Use this path when the operator needs to confirm descriptor validity, default descriptor selection, tenant alignment, reader access, or which retrieval modes are actually advertised.

## Discovery

1. Start with `ekg-skills-ekg_doctor` when tenant, descriptor, or local tooling might be wrong. The check is read-only, skips missing inputs, and returns one `next_step`.
2. Run `ekg-skills-ekg_consume_health` to validate a published descriptor offline. Health does not probe Azure connectivity or serving state.
3. Run `ekg-skills-ekg_consume_capabilities` to see whether `document_retrieval` or `graph_retrieval` is enabled before choosing a retrieval method.

## Interpretation

- If no descriptor path is supplied, the runtime uses the current published descriptor. Say that choice out loud when it matters.
- If the descriptor is invalid, stop and correct it; do not guess missing fields.
- If a capability is absent, return that it is not enabled. Do not route around it silently.
- If the CLI fallback is needed, check `ekg-consume --version`. If missing, read the [local runtime installation instructions](../../../README.md#install-the-local-runtimes) first. Install or run the shipped `runtime/ekg-skills[consume]` package through the Microsoft CFS feed.

## Return

State whether the result is offline descriptor validation, environment diagnosis, or live-read readiness. Keep tenant details and raw credential material out of output.
