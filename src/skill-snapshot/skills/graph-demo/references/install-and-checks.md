# Install and checks

Check only the chosen route. Show installation commands to the operator; never install, authenticate,
change global configuration or start an Apps server from these meta skills.

## Read-only checks

Run `copilot plugin list`, then root `--help` for the executables on the route:

| Route | Executables |
|---|---|
| EKG | `ekg-provision --help`, `ekg-build --help`, `ekg-consume --help` |
| GRZ | `grz-build --help`, `grz-consume --help` |
| Ontology | `ontology-build --help`, `ontology-consume --help` |
| Grounding | `grounding-provision --help`, `grounding-build --help`, `grounding-consume --help` |

Help proves the entrypoint exists, not Azure readiness. Use the owning skill's checks for readiness.
Do not assume a universal `--json` flag or an offline doctor: a doctor (`ents doctor` too) can read Azure and call models.

## Plugin and CLIs

This testing-only `graph-skills-snapshot` bundles 13 graph skills and four runtimes.
Use the [local snapshot instructions](../../../README.md#install-the-local-runtimes), not a marketplace
package or moving branch. Reload the agent after installation. Foundry IQ, entity (`ents`), Kusto
and standalone presentation are external routes, not bundled tools.

Each domain CLI lives under the plugin's `runtime` folder. Python 3.12 and `uv` are required. Install
only the CLIs on the chosen route:

```text
uv tool install --python 3.12 "<plugin-root>/runtime/ekg-skills[build,consume,provision]"
uv tool install --python 3.12 "<plugin-root>/runtime/grz-skills[azure,embed]"
uv tool install --python 3.12 "<plugin-root>/runtime/ontology-skills"
uv tool install --python 3.12 "<plugin-root>/runtime/grounding-skills"
```

Grounding reads Parquet only with the `[parquet]` extra. GRZ and ontology are previews: use public or
synthetic data only. Ontology consumes a published GRZ descriptor; installing it builds nothing.

Where an approved package feed is required, pass `--index-url <approved-python-index>` to that
invocation. Do not add a second index, disable TLS or persist global pip or uv settings. If
resolution fails, report the exact error; do not drop extras or substitute versions. If a tool is not
on PATH, run `uv tool update-shell` and open a new shell.

This snapshot's install examples use public PyPI. GRZ builds require the shipped
[native runtime](../../../README.md#grz-native-runtime-prerequisite); never substitute a fixture or simulator.

## Optional Apps

Apps are optional presentation adapters on the official MCP SDK; the CLI route never needs them.
The plugin registers EKG and GRZ Apps adapters. Ontology requires the explicit state-bound launch
below and is not registered automatically. Entity and grounding have none.

| Adapter | Extra and launch |
|---|---|
| Ontology | `[apps]`; `ontology-apps --state-dir <absolute-state-directory>` |
| EKG | `[apps,consume]`; `ekg-apps --descriptor <absolute-descriptor-path>` |
| GRZ | `[azure,embed,apps]`; `grz-mcp --descriptor <absolute-descriptor-path> --endpoint <search-endpoint> --auth entra` |

A passing SDK stdio test does not prove a product host renders the UI.

## Standalone presentation

graph-presentation is a separate release archive for a standalone viewer. It calls independently
installed one-shot domain CLIs directly, within an operator-configured scope; it is not an MCP client.
Never copy another operator's private config or broaden its scope.

## Tenant and approvals

Before any Azure sign-in, the owning skill names the tenant by display name. Never print or commit
tenant or subscription IDs, keys or tokens. Plain-language wording never bypasses exact-plan approval.
