# API version policy

## Task-scoped parameters and defaults

Resolve only the planes needed by the current task. Management and data-plane versions are independent; a Search service does not have one service-wide API version.

| Task parameter | PowerShell variable | Default in the [operation catalog](operation-catalog.yaml) |
|---|---|---|
| `managementApiVersion` | `$managementApiVersion` | `managementPlaneApiVersion` |
| `dataApiVersion` | `$dataApiVersion` | `dataPlaneApiVersion` |

The catalog is the single source of default version values. These defaults describe the bundled recipe baselines, not a promise to use the latest release. In catalog schema `2.0`, each operation's `apiVersionParameter` names its task parameter instead of repeating a version value. Versioned reference links and example payloads describe the default baseline; they do not establish compatibility with other versions.

These parameters are instructions for the agent, not automatic skill arguments. Record the exact version, plane, target, selection source (`user`, `project`, `original-request`, or `catalog`), and compatibility evidence in the task context. When executing a PowerShell example, explicitly set its version variable to that resolved value in the same invocation. Do not infer task context from a leftover shell variable or an unrelated earlier task.

## Resolve before every entry point executes

1. **Reuse a resolved value:** if the current task already has a compatible version for this plane and target, use it unchanged. If a new user request, project setting, or required capability conflicts with it, stop and reconcile the plan before further requests; do not silently overwrite it.
2. **Resolve a missing value:** use the customer's explicit version first, then the relevant existing project configuration (or original request version when troubleshooting), then the catalog default for that plane. Clarify an ambiguous version when the task spans both planes. Do not interpret a version requested for one plane as an override for the other.
3. **Check compatibility:** verify that the selected version supports every required operation and feature, including region/tier constraints. For an override, consult authoritative documentation for that exact version and compare request bodies, response shapes, pagination, and SDK/tool support with the recipe. Do not merely replace the URL version. The agent's documentation check is not retained live-test evidence.
4. **Handle a conflict explicitly:** if the version is unsupported, retired, incompatible, or cannot be verified, stop before execution, explain the limitation, and ask whether to use a documented compatible alternative or change the requested scope. Never silently fall back to the catalog default or strip requested functionality. Disclose preview use before mutations; if the user requires GA-only behavior, do not choose a preview.
5. **Keep the task consistent:** pass the resolved context to each operation and use the appropriate plane's value in every constructed request. If a helper or SDK cannot honor it, use a compatible interface or explain the blocker. Follow service-returned continuation and status URLs as documented rather than rewriting their query parameters.

Hero scenarios gather requirements for the entire workflow and resolve all needed planes before the first request. Standalone operations perform the same resolution for their own plane if the value is absent; they must not require a hero to initialize it. Troubleshooting retains the original request version unless an explicit migration is agreed. Never change versions mid-workflow as a generic retry strategy.

## Discovery and maintenance

When the user asks for "latest" or an unfamiliar version, consult the official [data-plane versions](https://learn.microsoft.com/rest/api/searchservice/search-service-api-versions), [management-plane versions](https://learn.microsoft.com/rest/api/searchmanagement/management-api-versions), and [upgrade guidance](https://learn.microsoft.com/azure/search/search-api-migration). Resolve an exact version and perform the compatibility checks above; do not automatically select the newest date on every run or assume GA is a superset of preview.

Review new releases and retirements, then promote defaults only with matching recipe, reference, and validation updates. Prefer a validated GA contract when it supports the scenario; retain an explicit preview requirement when necessary. The repository's scripted live runner exercises the catalog's default recipes only, not arbitrary customer overrides.
