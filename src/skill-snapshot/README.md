# Testing-only Foundry IQ skills snapshot

This snapshot imports the consolidated `foundry-iq-skills` plugin from
[Foundry-IQ-Skills PR 2344752](https://msdata.visualstudio.com/Azure%20Search/_git/Foundry-IQ-Skills/pullrequest/2344752)
at commit `7389ee18f277f24e9f6578975c3e5dfdd80e1a61`. It is an optional skills
distribution, not a prerequisite for the Part 1 notebook.

**Testing only:** the source PR is a draft whose release status is blocked:
not release-candidate or demo-ready. Its open work includes retrieval quality,
software-suite failures, KB workflows, Apps integration, and complete live
acceptance. Importing the package does not resolve those issues or certify this
lab's scenarios.

## Package contents

The unchanged generated plugin is in [foundry-iq-skills](foundry-iq-skills/README.md).
Unlike the earlier graph-only snapshot proposed in
[#4](https://github.com/microsoft/ignite26-LAB673/pull/4), this package includes
the Foundry IQ search skill and uses wheels instead of copied runtime source trees.

| Family | Included skills |
|---|---|
| Foundry IQ and search | `foundry-iq` |
| Graph routing | `graph-choose`, `graph-demo`, `graph-guide` |
| Enterprise knowledge graph | `ekg-provision`, `ekg-build`, `ekg-consume` |
| Grounding | `grounding-provision`, `grounding-build`, `grounding-consume` |
| Topic communities | `grz-build`, `grz-consume` |
| Ontology | `ontology-build`, `ontology-consume` |

The package also contains four runtime wheels, complete hashed Python 3.12
dependency locks for Windows x64, Linux x64/ARM64, and macOS Intel/Apple Silicon,
and the prebuilt localhost MCP Apps host. Platform locks are not proof of
execution on each platform.

## Set up the chosen runtime

Use an existing Python 3.12 executable with standard `venv` and `pip`. From
the lab repository root, prepare only the domain needed for your chosen skill.
This example prepares EKG:

```powershell
$plugin = (Resolve-Path 'src\skill-snapshot\foundry-iq-skills').Path
$env:PIP_INDEX_URL = 'https://packagefeedproxy.microsoft.io/pypi/simple/'
$env:NPM_CONFIG_REGISTRY = 'https://packagefeedproxy.microsoft.io/npm/'

python -I "$plugin\runtime\bootstrap.py" setup ekg
python -I "$plugin\runtime\bootstrap.py" status ekg
python -I "$plugin\runtime\bootstrap.py" run ekg ekg-build --help
```

Use `grounding`, `grz`, or `ontology` in place of `ekg` for another domain,
with that domain's entry point. If `python` is not Python 3.12, invoke an
existing 3.12 executable by absolute path or set `FOUNDRY_IQ_PYTHON` to that
executable. No interpreter is downloaded or selected automatically.

Setup installs the pinned dependencies into a plugin-owned cache outside the
repository, not the lab's `.venv` or global tools. Later `run` and `status`
commands reuse that environment without installing or repairing it. Do not
change dependency pins or add fallback package indexes to work around an error.

For an agent host that supports local plugins, configure its plugin root as
`src\skill-snapshot\foundry-iq-skills`, not this parent directory. Preserve the
generated manifests and verify that the host expands `${CLAUDE_PLUGIN_ROOT}`.
The [runtime and route guide](foundry-iq-skills/skills/graph-guide/references/install-and-checks.md)
describes CLI invocation and the explicit scope flags needed for optional Apps
servers. Azure MCP retains upstream's `@azure/mcp@latest` registration; that
external package is not pinned by this snapshot.

The optional [localhost MCP Apps host](foundry-iq-skills/apps-host/README.md)
requires existing Node 22.13+ and private operator configuration outside the
plugin. Its frontend is already built; no consumer npm install is required.

## Limits and Azure scope

GRZ native builds require a separately supplied, trusted `GRZBuildPoc 0.1.4-local`
executable for the host platform. Native executables are not included here;
runtime setup alone does not make a GRZ build ready.

This snapshot does not provision resources, grant permissions, ingest lab data,
or run models. Setup and help output do not establish Azure readiness. Follow
the owning skill's planning, approval, and verification boundaries before any
live operation, and keep credentials and operator state outside source control.

## Snapshot identity

[snapshot-manifest.json](snapshot-manifest.json) records the source commit and
testing-only status. [package-digest.json](package-digest.json) is the upstream
generator's complete 307-file inventory, with a SHA-256 for every plugin file.
The package digest is
`sha256:c3c1c4cd56dafd1c1e07c021e20b37405907658462c52f7a04b445e31edc354f`.

The plugin and skill version fields retain upstream's `0.0.0-placeholder`;
they are not published release versions. Identify this snapshot by its source
commit and package digest, not by the moving feature branch or a marketplace
package. Preserve the generated plugin bytes, its [license](foundry-iq-skills/LICENSE),
and bundled notices when updating it. Private benchmark evidence, approvals,
repository development tooling, and source test suites are not imported.
