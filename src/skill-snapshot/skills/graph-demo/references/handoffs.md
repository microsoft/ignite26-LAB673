# Hand-offs

Leaf skills own execution and approvals. Check artifacts, not live access.
Agree public data and seven questions first.

## 1 to 2: Azure resources

`ekg-provision` creates resources or connects existing ones. After verification, `connect` must
report `ready`. Retain its `build_binding.build_args` array: observed endpoints, ARM IDs,
identity, deployments and models. Never synthesize an OpenAI endpoint.

GRZ/ontology may use that Search service and OpenAI account via their own explicit configuration.
Ontology needs a chat deployment and its per-1M input/output prices.

## 2 to 3: the Search index

`ekg-build plan --ontology schema_org --graph` also needs the binding, source manifest and absolute
journal. After exact approval: apply, verify, publish. `none` is document-only, not this graph route.
Keep the published descriptor for comparison. Do not update the source during the GRZ build.

In GRZ put global source/identity flags, `--backend azure` and absolute `--state-dir` **before**
the verb. Retain them through inspect, plan, apply, verify and publish.

| GRZ flag | Bound EKG value |
|---|---|
| `--source-index` | descriptor's content index |
| `--key-field` | `uid` |
| `--text-field` | `snippet` |
| `--vector-field` | `snippet_vector` |
| `--source-field` | `blob_url` |
| `--embedding-model-id` | Connect `build_args`' `--embedding-model`, not deployment |
| `--source-visibility` | `public-attested`, only after the user confirms the whole index public |

No security field is mapped here. `grz-build inspect` must confirm a sortable/filterable key
and retrievable vectors. A failed check blocks the chain; do not attest around it.

## 3 to 4: the GRZ generation

Inspect, plan, apply, verify, separately approve publish. Keep `generation_id` and the publish
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

Ask the seven agreed questions on both saved descriptors:
`ekg-consume query --graph --descriptor <saved-descriptor> --query "<question>" --json`.
Report paths, citations and gaps. Historical Q1-Q7 and n-of-19 scores are not a packaged runnable
benchmark. Check a probe such as "Oracle bought Red Hat"; do not predict its answer.

## Approval stops

Route agreement is not write approval. Leaf cards gate provisioning, builds, cutover, spend,
version approval and retirement. A generic yes never substitutes.
Entra sign-in and public attestation are separate checks, not authorization to run later steps.
