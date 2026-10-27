# Install and checks

Use the shared [runtime setup](../../graph-guide/references/install-and-checks.md).
Before provisioning or any EKG write, run with the same absolute Python 3.12 used by
the leaf launchers and MCP configuration:

```text
python -I "<package-root>\runtime\preflight.py"
```

This offline, read-only check validates the prepared `ekg`, `grz` and `ontology` wheels,
locks, dependencies and route CLI entrypoints through `bootstrap.py run ... --help`.
Apps are optional and are not launched; grounding is not on this route.
It never runs doctor, signs in, calls Azure/models,
installs/repairs, downloads, executes native code or changes global configuration.
It resolves and hash-checks GRZ using the installed wheel's pinned native policy.

If blocked, show the structured runtime/native results and next steps. Have the operator
explicitly run `bootstrap.py setup ekg`, `setup grz`, and `setup ontology` as needed;
never set up on their behalf. A different caller Python does not reuse this baseline's
bound cache: use the same absolute 3.12 throughout, not a new interpreter/global default.
Re-run preflight after setup or any wheel, dependency, interpreter or binary change.

GRZBuildPoc `0.1.4-local` is not in the wheel. Its trusted distribution location remains
an unresolved release blocker. Do not invent a download source. If the operator already
has a trusted pinned host build, select it explicitly:

```text
python -I "<package-root>\runtime\preflight.py" --native-binary "<absolute-binary-path>"
```

Retain that returned path as GRZ's `--native-binary`; no alternate checksum is accepted.
Only Windows/Linux x64 have packaged native pins, regardless of Python wheel support.

## Results and source gate

Exit `1` / `blocked` stops the demo. Exit `2` / `conditional` is not native readiness:
the actual source may be unknown, or inspection may require a compatibility snapshot.
Search creates EKG's schema; managed `uid` can be nonfilterable. Explain this before ingestion.
The temporary compatibility layer defaults to `auto` for new plans: use the original directly
when supported, otherwise plan a faithful snapshot only when eligible. The executable stays unchanged.
Route agreement never authorizes that copy or any leaf write.

As soon as the physical index exists, delegate actual schema inspection to `grz-build`
before advancing the demo. Inspection does not pause or cancel managed ingestion already
running; do not silently change its schedule or freeze evidence. GRZ planning requires the
completed, frozen source. For an explicitly selected existing source,
inspect before any new EKG work. This helper optionally performs the same read-only adapter
inspection, bypassing CLI state-directory creation:

```text
python -I "<package-root>\runtime\preflight.py" --native-binary "<absolute-binary-path>" --inspect-source <GRZ-source-flag/value-pairs>
```

Select the original EKG content index from its descriptor; retain its authority/provenance.
Use all explicit tenant, subscription, resource-group, search-service, source-index,
key/text/source/vector-field, embedding-model-id, dataset, owner-approval, frozen-evidence
and security-inspection flags from the leaf skill. No state, verbs, naming or write flags.
Add `--security-field` per ACL field or `--source-visibility public-attested` only after
confirmation that the source documents are already publicly available. This does not make
Search/GRZ indexes public, enable anonymous access or change permissions; authentication and
access controls still apply. This preview cannot preserve different per-document access rules.
All source flags go after `--inspect-source`.
Name the tenant before this explicit live/authentication opt-in; never print identifiers/tokens.

Set `--source-compatibility auto|off` before `--inspect-source`; retain the selected policy
as a GRZ global flag before `inspect`/`plan`. `off` rejects an unsupported original before writes.
Inspection returns `source_compatibility`: `requested_mode`, `resolved_mode`, `native_direct_supported`,
`export_strategy`, `max_export_documents`. `snapshot-copy` eligibility is not native-original readiness.
Only a sortable, nonfilterable original within the 100,000-document bound and admitted stored,
retrievable vectors qualifies for bounded-offset export. Unsupported/malformed sources still block.

Exit `0` / `ready` requires local checks and verified `direct` inspection.
Exit `2` with `snapshot-copy` requires the explicit plan/approval/parity steps in [hand-offs](handoffs.md).
Preflight never exports a snapshot, creates/uploads a copy or runs native/model code.
Legacy runtimes remain strict/direct-only; this distribution's pinned wheel must be explicitly
updated to a qualified compatibility implementation before snapshot eligibility can be reported.
Re-inspect at handoff; readiness is neither model/build readiness nor write approval.
Never mutate the original, change native pins, fake metadata, hide a copy or rewrite old plans.
