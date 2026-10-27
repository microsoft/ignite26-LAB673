# Install and checks

Check only the chosen route. Setup makes no Azure/model calls.
Meta skills never authenticate, change global configuration or start Apps.

## Plugin and CLIs

Resolve the plugin root from your harness. Setup requires existing Python 3.12
with standard `venv`/`pip`. Use its absolute executable, or set `FOUNDRY_IQ_PYTHON`
to it. Without an override/binding, setup uses its 3.12 caller, not interpreter discovery.
No global install, PATH or system/project environment changes.

Set up only the chosen domain: `ekg`, `grz`, `ontology` or `grounding`.
For example:

```text
python -I "<package-root>\runtime\bootstrap.py" setup ekg
```

Setup verifies wheel/lock hashes and installs into a plugin-owned external cache using
configured package sources. Locks cover Windows x64, Linux x64/ARM64 and macOS Intel/Apple
Silicon; other targets fail explicitly. Resolution is not native execution acceptance.

Use the owning skill's entrypoint after `run DOMAIN`, for example:

```text
python -I "<package-root>\runtime\bootstrap.py" run ekg ekg-build --help
python -I "<package-root>\runtime\bootstrap.py" status ekg
```

Bare CLI names mean this prefix, not global commands. Use native path separators.
Warm run/status never install, resolve or repair; missing/changed files fail explicitly.
Demo: `python -I "<package-root>\runtime\preflight.py"` checks runtimes/native offline.
Exit 1 blocks; 2: source-unknown. See [demo checks](../../graph-demo/references/install-and-checks.md)
for the live source gate.

Successful setup binds that domain/artifact to its exact interpreter in the external cache.
Later bootstrap callers may differ; run/status re-enter the bound 3.12, never discover/install.
`FOUNDRY_IQ_PYTHON` explicitly overrides selection; re-run setup after changing it.
Cache identity binds wheel, lock and interpreter/platform; updates leave older sessions alone.
Optional `FOUNDRY_IQ_RUNTIME_CACHE` must be absolute, outside plugin/project.
Concurrent/incomplete setup fails: never stop another session to clear a lock.
`PLUGIN_ROOT` enables doctor artifact-version checks.

## Read-only checks

Help proves entrypoint availability, not Azure readiness; use the owning skill's checks.
No universal `--json` or offline doctor: domain checks can read Azure/call models.
GRZ/ontology previews allow public or synthetic data only.
Grounding includes Parquet; ontology setup builds nothing.

## Optional Apps

Apps use the official MCP SDK. EKG/GRZ are registered; ontology needs an explicit state-bound
launch. Grounding has no Apps. Set up first, then use the same prefix.

If the harness cannot find `python`, replace generated `command: "python"` in per-server
overrides with an absolute Python executable. Keep `args`: `-I`, absolute bootstrap path,
`run`, domain, entrypoint, scope flags:

| Domain | Entry point and scope |
|---|---|
| Ontology | `run ontology ontology-apps --state-dir <absolute-state-directory>` |
| EKG | `run ekg ekg-apps --descriptor <absolute-descriptor-path>` |
| GRZ | `run grz grz-mcp --descriptor <absolute-descriptor-path> --endpoint <search-endpoint> --auth entra` |

Before relying on MCP, require `initialize`, `notifications/initialized` and nonempty
`tools/list`. Missing tools or a startup exit is blocked, including in autopilot: report
stderr and the setup recovery, never silently pass. This does not prove host UI rendering.

## Local MCP Apps host

Packaged `apps-host/launch.mjs` needs no checkout, npm install or frontend build.
It verifies ontology/EKG/GRZ MCP resources before selecting matching packaged renderers;
no direct-CLI browser fallback. Embedded hosts retain self-contained HTML.
See [host README](../../../apps-host/README.md) for prerequisites/lifecycle.
Keep private JSON outside the plugin; never copy another operator's config or broaden scope.

```powershell
node "<installed-plugin>\apps-host\launch.mjs" --config "<operator-config.json>"
```

Open the exact ready loopback URL; `quit` or Ctrl+C stops owned servers.
Context is not a model conversation; historical CLI receipts are not host acceptance.

## Restricted-network setup

Honor operator/environment package source/proxy configuration. Report access errors; never
change feeds, add fallback indexes, drop dependencies, substitute versions or disable TLS.
Enterprise authentication belongs in environment setup guidance, not the normal workflow.

## Tenant and approvals

Name the tenant by display name before Azure sign-in. Never print/commit tenant/subscription IDs, keys or tokens.
Plain language never bypasses exact-plan approval.
