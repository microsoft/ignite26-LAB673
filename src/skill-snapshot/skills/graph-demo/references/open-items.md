# Open items

Say these before starting. Do not work around them here; each needs a change owned by a leaf domain.
The runs below predate the CLI-first migration and do not requalify current adapters or hosts.

Entity (entity-skills) is a separate workflow, outside this chain.

## 1. The full EKG build takes hours

Search extracts one document at a time, so a 1,000-article `owl_file` build spans several 2-hour
indexer runs: 9 h 45 min over 5 runs, about $8, in the measured run. `ekg-build` flags a multi-run
build and recommends `--ingestion-interval PT5M`; if the user passes it the runs chain unattended.
Set expectations before step 6.

## 2. Graph-mode answers are still improving

The derived-OWL graph scored 16 of 19 on Q1 to Q7, but through chunk retrieval: graph queries hit
Search's round-trip cap. After the fix one graph query finds 13 of 19. Q3 to Q5 have several valid
values and answers tend to give one. `schema_org` is unscored. Report what happens this time.

## 3. Wrong-premise recovery: one question

Both consume skills corrected Q7 once on one corpus. Do not promise it.

## 4. GRZ over the EKG content index: two live checks

The index has no security field, so the user confirms it is public when `grz-build` asks.

| GRZ requirement | EKG content index | Status |
|---|---|---|
| Every document public | Whole-index attestation by the user | Fits |
| Sortable, filterable key | `uid` | Verify live with `grz-build inspect` |
| Vector stored and retrievable | `snippet_vector` | Verify live with `grz-build inspect` |
| Text and source fields | `snippet`, `blob_url` | Fits |
| Embedding model ID | Recorded in the EKG descriptor | Fits |
| Frozen source | `plan-update` changes an index in place | Fits if no update runs during the GRZ build |

If a live check fails, build GRZ over a separate index of the same articles that meets the contract.

## 5. Ontology quality scores are noisy

A single-sample judge scores the same ontology 2 to 4 points apart on a 30-point rubric, so the refine
loop's "no improvement" stop can discard a real fix. Read version scores and question coverage
together before approving.
