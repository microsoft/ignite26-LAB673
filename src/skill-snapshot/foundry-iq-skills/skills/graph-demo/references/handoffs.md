# Hand-offs

Preflight before stage 1; agree public data/questions. Leaves own approvals.

## 1 to 2: Azure resources

`ekg-provision connect` must verify `ready`. Retain `build_binding.build_args`: endpoints, ARM IDs,
identity, deployments and models. Never synthesize an OpenAI endpoint.

Configure GRZ/ontology explicitly for that Search/OpenAI pair.
Ontology needs a chat deployment and per-1M input/output prices.

## 2 to 3: the Search index

`ekg-build plan --ontology schema_org --graph` also needs the binding, source manifest and absolute
journal. After exact approval: apply, verify, publish. `none` is document-only.
Keep the published descriptor; freeze the source during GRZ.
As soon as the physical content index exists, have GRZ inspect its actual schema before
advancing the demo. Managed ingestion may already be running; inspection does not pause
or cancel it. Until inspection, compatibility is unknown, not guaranteed by `schema_org`.

Keep GRZ global source/identity flags and absolute `--state-dir` **before** every verb.

| GRZ flag | Bound EKG value |
|---|---|
| `--source-index` | descriptor's content index |
| `--key-field` | `uid` |
| `--text-field` | `snippet` |
| `--vector-field` | `snippet_vector` |
| `--source-field` | `blob_url` |
| `--embedding-model-id` | Connect `build_args`' `--embedding-model`, not deployment |
| `--source-visibility` | `public-attested`, after confirmation source documents are already publicly available |

Before any GRZ plan, `grz-build inspect --json` with these global flags must pass:
retain `--source-compatibility auto` (new-plan default), or explicit `off` to require direct use.
`source_compatibility.resolved_mode=direct` requires native-compatible original fields.
`snapshot-copy` is eligibility only: sortable nonfilterable key, bounded-offset export at most
100,000 documents, admitted stored/retrievable vectors. Failed/unknown inspection blocks.
Doctor-ready and EKG publish are not this gate. No security field is mapped.
Content confirmation changes no index permissions or authentication; per-document access rules
cannot be preserved by this preview. Reader grants remain separately approved changes.

## 3 to 4: the GRZ generation

New plans bind compatibility policy. A snapshot-copy plan must show original source/schema
fingerprint/field mapping, frozen `snapshot_digest`/`source_documents_sha256`,
`snapshot_manifest`/`snapshot_manifest_digest`, `copy_index`, `copy_schema`,
document count/dimension/model identity, `estimated_copy_bytes`,
`estimated_copy_storage_bytes` and `native_input`.
Review combined upload `estimated_bytes`; apply reserves copy bytes from the community budget.
It preserves original physical IDs, all retrievable fields and raw stored vectors: no reembedding
or normalization. The original EKG descriptor remains authoritative; copy provenance is retained.
`direct_handoff=false` identifies snapshot use; never describe it as native direct interoperability.

Planning performs bounded read-only export; it is not copy-write permission. After exact plan
approval, apply reexports and checks digests before creating/uploading the planned
`grz-{dataset}-compat-...` index. Verify content/schema parity before the unchanged native executable
reads the plan's endpoint/index/vector field. Retain the separately journaled copy for reconciliation;
`lifecycle.automatic_cleanup=false` and `original_source_unchanged=true` must remain true.
`generations` classifies the copy as `compatibility-source`, protected from generation retirement.
No automatic cleanup/refresh or reader changes; any supported cleanup needs separate explicit
lifecycle approval, never a hidden fallback or deletion.
Legacy plans lacking `source_compatibility` stay strict/direct; apply uses saved policy, not new defaults.

Inspect, plan, apply, verify; separately approve publish. Keep `generation_id` and the publish
result's `browse.env.GRZ_DESCRIPTOR` path; confirm `grz-consume status` shows communities.
`ontology-build connect --grz-descriptor <descriptor.json>` needs this GRZ descriptor, not EKG's,
and reader access. Retain one absolute ontology `--state-dir` on every build/consume command.

## 4 to 5: the approved `.owl`

Connect, inspect, plan, propose, refine, review, approve, export (`--output <path>.owl`).
`ontology-consume check <path>.owl` must pass. Keep `ontology-consume current --json` path,
SHA-256 and source generation matching that export. EKG needs object-property domain/range
and rejects remote imports. Pass `--ontology owl_file --ontology-path <path>.owl`.

## 5: trial (go or no-go)

Inventory with the owning skill. `ekg-build plan` needs the binding, explicit source,
`--source-manifest <manifest.json> --sample 50 --graph --json`, ontology and a new journal;
the corpus must exceed 50 documents. Apply requires the exact approved plan ID.
`trial-report` takes those same build inputs including the sample. A trial cannot be published.
Save the report; no-go returns zero-hit classes/relationships to ontology refine. Trial resources
remain until separately approved retirement.

## 5 to 6: full graph

Same approved `.owl` hash, binding and full manifest; a new journal,
`--trial-report <GO-report.json> --graph`, no `--sample`. Preserve exact inputs and returned
plan ID through apply/verify/publish. Status uses `run_id` read from that durable journal.
Follow leaf slot/retirement guidance; never change ingestion settings silently.

## 6 to 7: questions

Ask seven agreed questions on both descriptors:
`ekg-consume query --graph --descriptor <saved-descriptor> --query "<question>" --json`.
Report paths, citations and gaps. Q1-Q7/n-of-19 scores are not a packaged runnable benchmark.
Probe "Oracle bought Red Hat"; do not predict its answer.

## Approval stops

Route agreement is not write approval. Leaf cards gate provisioning, builds, cutover, spend,
version approval and retirement. A generic yes never substitutes.
Entra sign-in and public attestation are separate checks, not authorization to run later steps.
