# Temporary skill distribution snapshot

This is a **testing-only snapshot**, not a published or assured release. It
packages the production skill and runtime files from
[Foundry-IQ-Skills PR 2344752](https://msdata.visualstudio.com/Azure%20Search/_git/Foundry-IQ-Skills/pullrequest/2344752),
at commit `0e44f9464deb180b13aea0fb4875d2cb2755e3aa`. Do not replace it with
the moving feature branch or a marketplace package when reproducing a run.

The pinned source defines one unified `foundry-iq-skills` plugin. This snapshot
ships all 14 skills, four Python runtimes and five MCP server registrations.
Source guidance sometimes calls runtime families companion plugins; here they
are bundled in this one plugin.

## Skills and entry points

| Family | Skills | Runtime commands |
|---|---|---|
| Foundry IQ and Search | [foundry-iq](skills/foundry-iq/SKILL.md) | Exact REST operation guidance; Azure MCP is an external dependency |
| Graph routing | [graph-choose](skills/graph-choose/SKILL.md), [graph-demo](skills/graph-demo/SKILL.md), [graph-guide](skills/graph-guide/SKILL.md) | Routing only |
| Enterprise knowledge graph | [ekg-provision](skills/ekg-provision/SKILL.md), [ekg-build](skills/ekg-build/SKILL.md), [ekg-consume](skills/ekg-consume/SKILL.md) | `ekg-provision`, `ekg-build`, `ekg-consume`, `ekg-mcp` |
| Grounding | [grounding-provision](skills/grounding-provision/SKILL.md), [grounding-build](skills/grounding-build/SKILL.md), [grounding-consume](skills/grounding-consume/SKILL.md) | `grounding-provision`, `grounding-build`, `grounding-consume`, `grounding-mcp` |
| Topic communities | [grz-build](skills/grz-build/SKILL.md), [grz-consume](skills/grz-consume/SKILL.md) | `grz-build`, `grz-consume`, `grz-mcp` |
| Ontology | [ontology-build](skills/ontology-build/SKILL.md), [ontology-consume](skills/ontology-consume/SKILL.md) | `ontology-build`, `ontology-consume`, `ontology-mcp` |

The Kusto graph route is external and is not included. Automated entity linking
and extraction through `entity-skills` is not implemented in this snapshot.
Native EKG graph extraction is a separate supported preview route.

## Install the local runtimes

Use an existing Python 3.12 installation and `uv`. From the repository root:

```powershell
$snapshot = (Resolve-Path 'src\skill-snapshot').Path
$env:UV_INDEX_URL = 'https://packagefeedproxy.microsoft.io/pypi/simple/'
$env:NPM_CONFIG_REGISTRY = 'https://packagefeedproxy.microsoft.io/npm/'

uv tool install --python 3.12 --index-url $env:UV_INDEX_URL "$snapshot\runtime\ekg-skills[build,consume,provision]"
uv tool install --python 3.12 --index-url $env:UV_INDEX_URL "$snapshot\runtime\grounding-skills[parquet]"
uv tool install --python 3.12 --index-url $env:UV_INDEX_URL "$snapshot\runtime\grz-skills[azure,embed]"
uv tool install --python 3.12 --index-url $env:UV_INDEX_URL "$snapshot\runtime\ontology-skills"
```

Keep runtimes in separate environments: GRZ pins `azure-search-documents==11.6.0`,
while ontology pins `azure-search-documents==12.0.0`. The Python manifests define
the direct production dependencies; there is no locked transitive dependency
set or offline wheelhouse in this snapshot. Installation resolves dependencies
through the Microsoft CFS feed and requires network access.

For one-off commands, use `uv tool run --isolated --python 3.12 --index-url
https://packagefeedproxy.microsoft.io/pypi/simple/ --from
"<absolute-snapshot-root>\runtime\<runtime>[<extras>]" <command> ...`.

Load this directory as a local plugin only through a host that supports the
included plugin manifests. `.mcp.json` uses `${CLAUDE_PLUGIN_ROOT}` for local
runtime paths; verify that your host expands it. Each subprocess is configured
with its approved CFS registry. Azure MCP uses the source's
`@azure/mcp@latest` registration and is therefore not pinned by this snapshot.
No dependencies or MCP server packages were installed to create this snapshot.

## GRZ native runtime prerequisite

The pinned Python source does not contain `GRZBuildPoc` binaries. This snapshot
includes five user-supplied `0.1.4-local` builds. Windows x64 remains at
`runtime\grz-skills\bin\GRZBuildPoc.exe`; Linux and macOS executables are at
`runtime\grz-skills\bin\<RID>\GRZBuildPoc`, each with its archive's
`checksums.sha256`. The byte-identical vendor README, example configuration
and packaging guidance are shared at the bin root. There is no fixture fallback.
Each original checksum file describes the vendor's flat archive layout; its
shared-document entries refer to the bin-root copies, not duplicate documents
inside each RID directory. Use the snapshot manifest for the shipped layout's
complete file verification.

Archive: `GRZBuildPoc-0.1.4-local-win-x64.zip`; SHA-256:
`24019d4f150a11a49d6fc7d59c100de8516fcddfb5013884ec014eaf8873fdc4`.
The executable is 76,907,282 bytes and is self-contained; no separate .NET
installation is required. It is **not Authenticode-signed**. Hash verification
establishes content identity, not signed-release approval. The archive has no
third-party notice or standalone license file. This remains an internal,
testing-only snapshot, not a customer or production release. The vendor's
[packaging and signing guidance](runtime/grz-skills/bin/PACKAGING-AND-SIGNING.md)
records the additional release, legal/IP and OSS requirements.

The pinned source supplies the Windows x64 and Linux x64 executable hashes.
The other three trusted hashes come from the verified user-supplied archives.
All archive origins and per-file hashes are recorded in
[snapshot-manifest.json](snapshot-manifest.json).

| Platform (RID) | Executable relative to `bin` | SHA-256 | Verification |
|---|---|---|---|
| Windows x64 (`win-x64`) | `GRZBuildPoc.exe` | `6AA6AC85ED84436CE9676178C252EEDE85891B9D1717ACA66CAE095830354579` | Checksum, PE64 header and live workflow |
| Linux x64 (`linux-x64`) | `linux-x64/GRZBuildPoc` | `7095407BC5B3499056E2F94401D6EED22B103F2DB947AAE114E96B17FCAAB66A` | Checksum and ELF64 CPU header only |
| Linux ARM64 (`linux-arm64`) | `linux-arm64/GRZBuildPoc` | `53B3282DAA20590CEBFC035843E8B675083F15E8924EA99C0C1B78890886C253` | Checksum and ELF64 CPU header only |
| macOS x64 (`osx-x64`) | `osx-x64/GRZBuildPoc` | `151C7FF70F0F43ECE1E20B789C229B9492E5442E11EB61FB837AC468D4D7C348` | Checksum and Mach-O64 CPU header only |
| macOS ARM64 (`osx-arm64`) | `osx-arm64/GRZBuildPoc` | `772FC9B3E3460EA5F12473BCD87E205B2BB33F48B66105273DA2F8EF6764DCBE` | Checksum and Mach-O64 CPU header only |

All five builds are included. Linux and macOS builds have **not been executed**
on this Windows host; checksum/header checks and simulated platform resolution
are not Linux/macOS end-to-end validation. No macOS signing/notarization or
production-release approval is established.

The resolver checks an explicit `--native-binary`, `GRZ_BUILD_BINARY` or
`GRZ_NATIVE_BINARY` first, then the host RID's snapshot path, installed wheel
data, the known Downloads locations, and PATH. It verifies the executable
checksum and rejects OS/CPU header mismatches, including for an explicit binary
with a custom trusted hash. Windows ARM64 and unsupported platforms are rejected.

The GRZ wheel retains the five original Windows package files at
`share\foundry-iq-skills\grz\bin` and the other four executable/checksum pairs
in RID subdirectories. The task-specific `config.json` is not wheel data.
On Unix, preserve executable bits when checking out the repository. If a wheel
installer does not preserve them, grant execute permission to the matching
installed executable with `chmod +x <environment>/share/foundry-iq-skills/grz/bin/<RID>/GRZBuildPoc`
(or the matching snapshot path). The runner verifies its trusted checksum
before checking execute permission and never silently changes permissions.
See the vendor's
[native runtime contract](runtime/grz-skills/bin/README.md) for authentication,
configuration and invocation. Keep API keys outside JSON and source control.

Native community labeling requires the documented `azureOpenAI.llmResourceUri`
chat-completions URL and an environment-variable reference for its Azure OpenAI
key. The Python build adapter's generated configuration does not supply those
labeling fields automatically. Read-only clustering does not establish that
model-backed labeling works; verify the selected execution mode separately.
Use the task's native configuration for direct CLI execution.
Do not enable insecure HTTP or invalid-certificate acceptance for this Azure
Search service. Task-specific configuration and run results are separate from
the immutable native package; `config.example.json` is the vendor template.

## Run against Azure AI Search

Use only the tenant, subscription, service, corpus and write scope authorized
for the run. The leaf skills retain their plan, approval and verification
boundaries. These installation instructions do not authorize resource creation,
permission changes, ingestion or model calls. Run Azure CLI and its child
processes with task-isolated auth/config state, not a shared default profile.

1. For document retrieval or KB binding, start with
   [Foundry IQ](skills/foundry-iq/SKILL.md). Exact leaves include
   [knowledge source creation](skills/foundry-iq/operations/data-plane/knowledge-sources/create-or-update.md),
   [knowledge base binding](skills/foundry-iq/operations/data-plane/knowledge-bases/create-or-update.md)
   and [retrieval](skills/foundry-iq/operations/data-plane/knowledge-retrieval/retrieve.md).
   Resolve and reuse the appropriate API versions and verify service responses.
2. For an EKG, run `ekg-provision` readiness checks, inspect the exact source,
   and plan with `ekg-build`. Apply only the approved plan, verify the managed
   generation, publish the descriptor, then use `ekg-consume query --graph`.
   The preview graph path uses Search `2026-08-01-preview` and Azure Blob
   knowledge sources. SharePoint graph builds and EKG-to-KB handoff are
   explicitly unsupported; use the Foundry IQ KB leaves instead.
3. For topic communities, use `grz-build --backend azure` with a source index
   containing retrievable chunk vectors and the required source attestations.
   Plan, apply, verify and publish are distinct stages. A native executable
   is required for apply. Browse the published descriptor with `grz-consume`.
4. For an ontology, use `ontology-build` on an existing published GRZ generation,
   follow its proposal/review/export sequence, and pass the exported OWL file
   to EKG. Ontology can consume an existing GRZ generation even when this
   machine cannot perform a new native GRZ build.
5. Grounding is optional: `grounding-build` loads an edgeList grounding index
   from CSV, JSONL or Wikidata; use `grounding-consume` to inspect readiness.

Typical read-only local checks after installation are `ekg-build --version`,
`grounding-build --version`, `grz-build --version` and `ontology-build --version`.
Version checks and imports are not proof of live service readiness.

## Snapshot boundary and provenance

[snapshot-manifest.json](snapshot-manifest.json) is the explicit file allowlist:
every payload file has a distribution SHA-256 and, where applicable, its
original source path and SHA-256. The manifest names its own path separately
to avoid a self-referential hash. Its payload digest covers the sorted file
paths and hashes. Preserve the [MIT license](LICENSE).

Snapshot-only adaptations remove Foundry IQ evaluation scripts, associated
guides and routing; GRZ's offline fixture backend, fixture artifact generator,
full-generation test reader and developer simulator; runtime development
dependencies and test configuration; and EKG sample fixture data.
Production GRZ Azure reads/writes and the native adapter remain. The CLI's
explicit native-binary argument is connected to the actual build runner.
Native clustering uses the approved source binding's vector field instead of
assuming the field is named `vector`.

No eval suites, test code, fixture backend, private evidence, session auth state,
source governance tooling or development environment is included. Provisional
skill/plugin versions identify this snapshot; they are not upstream release
versions. Live results and prerequisite failures belong to the separate run
record, not this distribution.
