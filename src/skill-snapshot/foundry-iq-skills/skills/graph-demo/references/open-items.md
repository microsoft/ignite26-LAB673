# Open items

Say these before starting. Do not work around them here; each needs a change owned by a leaf domain.
The `foundry-iq-skills` runs below predate the CLI-first migration and do not requalify current adapters or hosts.

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

The index has no security field; confirm documents are already publicly available.
This does not make indexes public or change authentication/access permissions.

| GRZ requirement | EKG content index | Status |
|---|---|---|
| Every document public | Whole-index attestation by the user | Fits |
| Native sortable/filterable key | `uid` | Inspect direct support or explicit snapshot eligibility |
| Vector stored and retrievable | `snippet_vector` | Verify live with `grz-build inspect` |
| Text and source fields | `snippet`, `blob_url` | Verify actual generated schema |
| Embedding model ID | Recorded in the EKG descriptor | Fits |
| Frozen source | `plan-update` changes an index in place | Fits if no update runs during the GRZ build |

Search owns the generated schema; EKG's `schema_org` request does not set these field flags.
Compatibility is unknown until actual inspection, not promised by EKG publish.
Surface this before EKG work and inspect as soon as the physical index appears.
New GRZ plans default to temporary `--source-compatibility auto`: direct when supported,
otherwise an eligible original requires an explicitly planned faithful compatibility snapshot.
`off` fails closed on unsupported originals. Eligibility is not native direct readiness.
Use the leaf's approved copy/schema/storage/native-input plan and parity verification;
do not copy silently, mutate the original or change the executable/pins.
Historical plans/approvals do not acquire a copy by default. See [hand-offs](handoffs.md).
Compatibility qualification and an explicit reviewed wheel update remain required;
the legacy pinned runtime is strict/direct-only, not proof this new path works end to end.

The separate GRZ native binary's trusted distribution location is still unresolved.
Whole-route preflight must resolve and verify a trusted operator-provided pinned build
before starting EKG; a prepared Python runtime alone is insufficient.

## 5. Ontology quality scores are noisy

A single-sample judge scores the same ontology 2 to 4 points apart on a 30-point rubric, so the refine
loop's "no improvement" stop can discard a real fix. Read version scores and question coverage
together before approving.
