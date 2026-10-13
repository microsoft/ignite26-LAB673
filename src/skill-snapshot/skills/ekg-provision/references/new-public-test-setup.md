# New public-test setup

## Use this path

Use this path when the operator wants EKG infrastructure created in a new isolated public-test environment.

## Planning rules

1. Gather tenant, subscription, region, resource names, expiry within seventy-two hours, and the chosen public-test mode.
2. The mutable plan belongs to `ekg-provision plan` and later `ekg-provision apply`.
3. Build-access setup is one combined decision: the search identity, private container, operator object ID, embedding deployment, and chat deployment must be planned together.
4. `plan` and `render` are offline. Only the explicit public-test apply path writes.

## Hard boundaries

- Default and private-network apply stay disabled.
- Never infer `entra_only` from missing IP data or silently switch modes.
- The approval card must cover every resource, deployment, and role assignment that will be created.
- If the CLI is missing, read the [local runtime installation instructions](../../../README.md#install-the-local-runtimes) first. Install or run the shipped `runtime/ekg-skills[build,consume,provision]` package through the Microsoft CFS feed, then rerun `ekg-provision --version` and `ekg-provision doctor`.

## Return

Summarize the reviewed public-test plan, the exact plan ID, and whether the next step is offline artifact review or an approved CLI apply. Never claim that render, inspect, or verify created anything.
