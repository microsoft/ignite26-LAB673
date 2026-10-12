# Cocoarynth dataset reconciliation

The Cocoarynth documents now include 40 additional finished PDFs in the existing
[`data/cocoarynth/documents/`](../data/cocoarynth/documents/) directory. They tell
a fictional harvest-to-passport story alongside the lab's existing product and
engineering references. There is no separate supplemental directory.

Only finished documents, structured records, provenance metadata, and read-only
validation tooling are included. New editable document sources, generator
templates, HTML readers, and extraction sidecars are not checked in. The
previously committed HTML sources are untouched; Git ignores future additions
to that source directory.

## Coverage and placement

| Content | Coverage | Repository location |
| --- | --- | --- |
| Existing Cocoarynth references | Four product/traceability PDFs and four engineering-practice PDFs | `data/cocoarynth/documents/`, including `engineering-practices/` |
| Operational document set | 34 documents, 46 pages: field logs, custody, quality, production, stock, dispatch, support, issuance, and governance | `data/cocoarynth/documents/d01-*.pdf` through `d34-*.pdf` |
| Prose-rich working records | Five three-page records: collection notebook, receipt case, WIP handoff, integration brief, and sharing decision | The same documents directory |
| Production close-out | One two-page Esmeraldas manufacturing review and reconciliation | `data/cocoarynth/documents/production-closeout.pdf` |
| Structured scenario | 267 records: eight lots, seven batches, three shipments, eight cases, and their linked actors, farms, approvals, inventories, and passports | [`records.json`](../data/cocoarynth/records.json) |
| Document inventory | 40 unique PDF hashes, 63 pages, record/source references, and quantitative bindings | [`document-manifest.json`](../data/cocoarynth/document-manifest.json) |
| Derivation and transfer evidence | Public-source limits, original-file hashes, exclusions, and recorded rendering dependencies/font identities | [`sample-sources.json`](../data/cocoarynth/sample-sources.json) and [`sample-data-import.json`](../data/cocoarynth/sample-data-import.json) |

The imported material comprises 42 unchanged source files: 40 PDFs, one records
ledger, and one source manifest, totaling 3,346,722 bytes. The document manifest
and import inventory are reconciliation metadata, not additional samples.

The source was the local `cocarynth-graph-data` directory. Its Git repository had
no commit, and the sample content was untracked. The inventory records SHA-256
identities rather than fabricating a source revision. Its inspected inventory
contained 488 files after excluding Git internals, environments, and caches.
The transfer did not modify that source checkout.

## Canonical data and ingestion

The existing [`corpora.json`](../data/cocoarynth/corpora.json) still selects four
product PDFs, four engineering PDFs, and the data-sharing policy for the
file-source exercise. The new PDFs sit alongside those files but do not silently
expand those selections. The existing loader enforces those counts; adding a
file to the directory does not ingest it.

The notebook, Azure ingestion/restoration/export scripts, existing index
snapshots, all Caldova files, and original Cocoarynth PDFs and HTML sources are
unchanged. The original [`provenance.json`](../data/cocoarynth/provenance.json)
continues to describe the lab references; the new source manifest describes the
fictional operational records. Neither replaces the other.

For local consumers, read `document-manifest.json` and resolve each `path`
relative to `data/cocoarynth`. It selects finished PDFs only. Join `record_ids`
and binding `record_id` values to `records.json` using exact IDs, not product
names. Join `source_refs` to `sources` or `capability_sources` in
`sample-sources.json`. Existing lab index preparation remains unchanged; a
wider live ingestion selection would be a separate, explicit change.

## Overlaps and conflicts

There were no byte-identical files between the source's inspected content and
the canonical lab data. There is substantial *subject* overlap: the synthetic
documents model the same passport, sharing-policy, and Mapayca requirements.
That is not a reason to replace the canonical references.

| Overlap or conflict | Reconciliation |
| --- | --- |
| Earlier story corpus versus the newer v2 scenario | Keep the newer finished v2 documents and ledger. Do not merge the earlier corpus, questions, passports, or ledger into this set. |
| Earlier Esmeraldas accounting retained 50 kg after a 250 kg issue from 300 kg received | V2 separately deducts 3.867 kg of re-dry water and a 1 kg destructive sample. It then issues 250 kg to the original run and 20 kg to a blend, leaving 25.133 kg. The earlier simplified ledger is incompatible, not an extra allocation. |
| Six prose-rich PDFs revisit scenarios already covered by the 34-document edition | Retain them as distinct working documents, not new transactions. They refer to the same records; their quantities must not be counted twice. |
| Four extracted workshop references repeat the canonical lab's reference material | Do not import those extracted copies. Retain the existing lab PDFs. |
| Collected folio, Markdown/HTML readers, text extraction, and page previews repeat document content | Exclude them. Select only the 40 individual PDFs. |
| Three identical public-source manifests accompanied the source editions | Import one shared `sample-sources.json`; do not copy the duplicate provenance files. |
| App `productionDate` and partner `production_date` mean different things | Preserve start (`2026-08-18`) and completion (`2026-08-22`) separately. Mapayca remains unallocated and unshipped; Northstar's shipment is not assigned to it. |
| App behavior versus workshop requirements | The pinned app constructs allowlisted shipped-batch JSON on demand. Stored immutable passport versions, replacement lineage, and the CSV pilot are local requirement models, not implemented app features. |

The PDFs and structured records retain their original bytes. Only the document
inventory's locations and provenance representation are adapted. Authoring
source paths and hashes in `authoring_source` are historical provenance, not
repository links: `included` is always `false`.

## Exclusions and sharing limits

The transfer excludes the earlier graph experiment's embeddings, cloud service
and account identities, live receipts/state, logs, query results, proposed OWL
schemas, RDF handoff, and cloud workflow tools. No ontology approval or graph
publication is claimed. It also excludes `.git`, installed environments and
packages, caches, standalone font files, authoring sources, duplicate reading
forms, and unrelated tooling.

The imported provenance identifies the names, events, measurements, permissions,
and certificates as fictional. Public cacao, certification, and traceability
pages provide factual inspiration and original paraphrases, not reproduced
source text, images, logos, bulk datasets, or real personal records. References
to methodology in another docs checkout do not include that checkout's content.

No standalone license was found in the local graph-data source repository.
This task authorizes the local transfer, not publication, relicensing, or a
blanket sharing approval. The public-source manifest explicitly records reuse
limits, including sources without an established open license. Retain those
limits and confirm rights before external distribution. The PDFs contain
recorded embedded font subsets; font files are not bundled. Do not treat
embedding flags or local validation as a complete redistribution license review.

The data is not evidence of actual manufacturing, certification, consent, legal
compliance, or measured retrieval quality. The five prose-rich records and
production close-out intentionally lack visible fiction banners; their dataset
metadata identifies them as synthetic. Keep that context with any selected PDF.
Chosen yields, moisture rules, and recipes are sample accounting assumptions,
not validated operational or food-safety instructions.

## Use and develop the samples

Open the PDFs directly, or use the manifest and records in a local reader or
ingestion experiment. No credentials, Azure deployment, embedding calls, or
remote service are needed for the checks below.

From the repository root:

```powershell
python .\scripts\validate-cocoarynth-data.py --frozen
python .\scripts\test-cocoarynth-data.py
```

Those checks use Python's standard library. For actual PDF parsing, use an
isolated local environment and the pinned approved package feed:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --index-url https://packagefeedproxy.microsoft.io/pypi/simple/ -r .\scripts\requirements-sample-validation.txt
.\.venv\Scripts\python.exe .\scripts\validate-cocoarynth-data.py --pdf --frozen
```

The validator checks IDs and typed record references, integer-gram balances,
chronology, quality/release distinctions, approval scopes, sharing periods,
shipment eligibility, passport allowlists, snapshot hashes, and replacement
lineage. It checks document/record links, canonical binding values, PDF hashes,
and baseline file preservation. `--pdf` additionally parses selectable text,
page counts, A4 geometry, embedded fonts, quantitative text retention, and
external/internal hyperlinks without fetching the destinations. It exercises
the real existing `load_corpora` function in isolation, without importing Azure
clients or reading `.env`.

Develop document authoring files outside this repository. Copy only reviewed
finished PDFs into `data/cocoarynth/documents/`; do not add Markdown/HTML sources,
templates, previews, extraction text, environments, or credentials. Keep IDs,
units, and events consistent with `records.json`, then update the document
manifest's paths, PDF hashes, page counts, record links, and bound facts.
Authoring-source provenance can retain a hash without retaining its content.
Do not invent records merely to make a document look complete.

Run validation before each local commit. `--frozen` compares the original
imported bytes and is expected to fail after an intentional sample revision;
omit that flag when validating developed data. Keep the import inventory as
historical provenance, rather than relabeling modified files as unchanged
imports. Existing canonical lab file checks still apply. Selecting new PDFs
for live lab indexing requires a deliberate manifest/loader change and separate
authorization for the cloud effects.

Initial checks also reproduced the original PDFs byte-for-byte and checked full
source-text retention on isolated copies before the authoring inputs were
excluded. Those generators are not shipped. The finished-data validator does
not claim to reproduce missing authoring inputs, verify remote URL availability,
certify PDF accessibility, or prove real-world manufacturing validity.
