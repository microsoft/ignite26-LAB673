# Immutable captured input

Use this explicitly selected alternative only when the operator accepts that
the managed producer remains active. It is not a producer freeze or an atomic
Azure snapshot. Matching repeated reads detect observed changes but cannot
exclude undetected mixed-time reads.

## Plan

1. Complete doctor, source inspection and public/security approval from
   [plan and apply](plan-and-apply.md). Identify the exact source and authorize
   the bounded read scope and retained local capture before capturing anything.
2. With the normal launcher and global source flags, select
   `plan --capture-source --capture-coverage <absolute-coverage-json> --json`.
   Compatibility must be `auto`; do not combine this with `--frozen-evidence`.
   Coverage must bind the approved original-document inventory to every unique
   chunk and its actual document field, with input-evidence hashes. Missing or
   foreign mappings block; do not pad the corpus or import answer expectations.
3. Keep the complete capture and its plan-bound identity, file hashes, source
   provenance, observation interval and non-atomicity limitation. Report a
   stopped capture honestly; never silently retry, truncate or replace it.
4. Present the returned approval card verbatim. Planning/capture does not
   authorize cloud copying, native execution, model calls or publication.

## Apply, evidence and retention

Use the existing exact-plan apply, verify and separate publish gates. Apply
loads the approved retained artifact, never a fresh original-source export.
Missing or corrupt files stop execution even when the live source is available.
The native binary and its checksum policy remain unchanged; native input is
the separately approved faithful private compatibility copy.

Captured evidence is historical original content, not a guarantee of current
live-source content. Consume must keep that provenance and may not substitute
the mutable original. Preserve the artifact while any generation depends on
it. No automatic recapture, source/schedule modification, cleanup or retirement
is implied. Partial or ambiguous writes follow the existing journal/reconcile
path, not a new capture.

Bind captured status, generation listing and retirement planning to the exact
saved Build authority: on `status`, `generations` or `plan-retire`, pass
`--plan-id <saved-build-plan-id>` or `--plan-file <saved-build-plan-json>`.
Never infer the latest capture or reconstruct the
original source to run a lifecycle command. A retirement plan must retain the
owning generation's capture and compatibility provenance; retirement and
reconcile use that saved authority and the existing exact approval/ownership
checks. Retirement does not authorize deleting the retained capture or its
protected compatibility copy.

Strict producer-frozen plans and historical identities keep their original
requirements. Omitting the capture option never selects captured semantics.
The distribution's demo preflight only inspects prerequisites; it cannot
capture, copy, execute native work or publish.
