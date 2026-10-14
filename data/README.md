# Data

The lab corpus is Cocoarynth Chocolate Works, a fictional bean-to-bar chocolate maker that buys cacao from farms in five countries and sells through several retailers. All documents are generated: no real company, person, or record is described.

- [Corpus manifest](cocoarynth/corpora.json): the PDFs in each of the four indexes, plus the label claims policy used for the file-source exercise.
- `cocoarynth/documents/<index>/`: 55 PDFs, the indexed inputs.
  - `cocoarynth-origins`: farm and supplier records, partly in Spanish.
  - `cocoarynth-quality`: factory receiving, testing, tasting, and batch records.
  - `cocoarynth-logistics-retail`: shipping, carrier, retailer, and sales records.
  - `cocoarynth-policies`: company policies, guides, and reference material.
- [Mysteries](cocoarynth/questions.yaml): the lab questions with ground truth for measuring retrieval: the expected answer, and for each fact it needs, the documents that are valid citations.
- [Provenance](cocoarynth/provenance.json): how the corpus was generated, and the image, font, and logo sources.
- `index-data/`: the destination for portable index definitions and document/vector snapshots after the maintainer capture step.

Snapshots of the four indexes, captured from a live ingestion run, are in `index-data/`. Provisioning restores them by default, without running Content Understanding. After changing the documents, follow [index preparation](../deploy_yourself.md#prepare-the-cocoarynth-indexes) to rebuild and re-export them.

## What's in each index

Five documents are in Spanish, and 15 come from organizations other than Cocoarynth. Each organization's documents have their own look. The **Clues** column lists the [mysteries](cocoarynth/questions.yaml) (M1–M7) for which the document is a ground-truth citation. Documents without clues give the indexes realistic background and plausible wrong turns.

### `cocoarynth-origins`: farm and supplier records (16)

| Document | Issued by | Language | Visuals | Clues |
|---|---|---|---|---|
| Origin profiles: Ecuador, Ghana, Peru, Madagascar (4) | Cocoarynth | en | photo | |
| New origin trial: Loma Verde, Dominican Republic | Cocoarynth | en | | |
| Boletas de acopio (handwritten collection tickets) | Río Claro cooperative | es | scan | M2 |
| Registro de fermentación y secado, lot EC26-L07 | Río Claro cooperative | es | | M2 |
| Inspección interna de fincas | Río Claro cooperative | es | | |
| Akwapim Ridge internal inspection | Akwapim Ridge association | en | | |
| Informe de inspección orgánica (organic inspection) | CertiOrgánica Andina | es | photo | M4 |
| Organic certificate status: Nuevo Horizonte | Cocoarynth | en | photo | M4 |
| Trip report: Tsaravola Estate | Cocoarynth | en | photo | |
| Harvest and drying report | Tsaravola Estate | en | photo | M5 |
| Informe de visita de campo (field visit) | Loma Verde association | es | photo, scan | M3 |
| Sourcing price review 2026 | Cocoarynth | en | chart | M7 |
| Cocoarynth Origin Report 2026 (public) | Cocoarynth | en | chart, map, photo | M7 |

### `cocoarynth-quality`: factory receiving, testing, and production records (15)

All from Cocoarynth except the lab certificate.

| Document | Visuals | Clues |
|---|---|---|
| QP-04 Bean receiving and release procedure | | |
| Bean receiving register 2026 | chart | M5 |
| Hold notice: lot MG26-L02 | photo | M5 |
| Conditioning room log: re-drying MG26-L02 | chart, photo | M5 |
| Certificate of analysis (Cascadia Food Labs) | | M5 |
| Lot release record: MG26-L02 | | M5 |
| Sensory evaluation: trial lot DR26-T02 | | M3 |
| Nonconformance report NCR-2607-03 | photo | M3 |
| Sample approval: DR26-T03 | | M3 |
| Sensory panel report 2026 | chart, photo | M6, M7 |
| Batch records: GH26-0706, EC26-0811, PE26-0902, MG26-0826 (4) | | M2, M4 |
| Retention sample check: GH26-0706 | photo | M1 |

### `cocoarynth-logistics-retail`: shipping, carriers, retailers, and sales (16)

| Document | Issued by | Visuals | Clues |
|---|---|---|---|
| Bills of lading: Madagascar and Ecuador (2) | Bluefin Forwarding | | |
| Warehouse receiving note: CN-MG-2606 | Cocoarynth | photo | |
| Dispatch note: SHP-2607-031 to Larkspur Market | Cocoarynth | | |
| Riverbend depot handling log (handwritten scan) | Northwind Cold Freight | photo, scan | M1 |
| Temperature logger report: LOGGER-04 | Cocoarynth | chart | M1 |
| Incident response letter | Northwind Cold Freight | | M1 |
| Email: grey Ghana bars complaint | Larkspur Market | photo | M1 |
| Credit memo: Larkspur Market | Cocoarynth | | |
| Email: "Which farms grew my chocolate?" | Pantry Lane | photo | M2 |
| Email thread: July reorder | Steeple & Saucer | | |
| Supply agreements: Larkspur Market, The Cacao Cabinet (2) | Cocoarynth | | |
| Launch plan update: Madagascar nibs bar | Cocoarynth | | M5 |
| Wholesale price list 2026 | Cocoarynth | | M7 |
| Sales review Q3 2026 (slide deck) | Cocoarynth | chart | M5, M7 |

### `cocoarynth-policies`: company-wide rules and reference (8)

All from Cocoarynth.

| Document | Visuals | Clues |
|---|---|---|
| POL-03 Label and marketing claims policy (also the Part A file source) | | M4 |
| POL-05 Traceability data-sharing policy | | M2 |
| Chocolate storage and handling guide | photo | M1 |
| Sourcing principles | | |
| SPEC-01 Cocoa bean quality specification | | |
| Product launch process | | |
| Glossary | | |
| Organization chart | diagram | |

The [briefs](cocoarynth/briefs/) are the source for these tables. Update both when adding, moving, or retiring a document.

## Regenerating the documents

The PDFs are built from structured facts, so every document agrees with every other. To change them, edit the sources and rebuild:

- `cocoarynth/world/*.json`: the facts (farms, bean lots, batches, shipments, sales, prices).
- `cocoarynth/briefs/`: one plan per document, listing its index, type, author, facts, and visuals.
- `cocoarynth/drafts/*.md`: the document text, with placeholders filled from the facts.
- `cocoarynth/assets/`: photos, fonts, and the Cocoarynth logo. Charts, scans, and labels are drawn by the scripts.

The generator uses its own environment, separate from the lab's `.venv`:

```shell
uv venv .venv-cocoarynth --python 3.12
uv pip install --python .venv-cocoarynth -r scripts/cocoarynth/requirements.txt
.venv-cocoarynth/bin/python -m playwright install chromium
.venv-cocoarynth/bin/python scripts/cocoarynth/validate.py
.venv-cocoarynth/bin/python scripts/cocoarynth/charts.py
.venv-cocoarynth/bin/python scripts/cocoarynth/images.py derived
.venv-cocoarynth/bin/python scripts/cocoarynth/render.py
.venv-cocoarynth/bin/python scripts/cocoarynth/check.py
```

`validate.py` checks that the facts are consistent, that each mystery's answer follows from them, and that every cited document exists. `check.py` confirms that every PDF is fresh and that `corpora.json` matches the briefs (run it with `--write-corpora` after adding or moving a document). New photos need MAI image credentials in `.env` and `images.py photos`.

To measure retrieval quality against a provisioned environment, run `.venv/bin/python scripts/cocoarynth/ask_mysteries.py` from the lab's `.venv`. It builds the notebook's knowledge base, asks each mystery, and reports evidence recall: how many of the mystery's facts have at least one valid document among the answer's references.

Documents use the house style of the organization that issued them, so Cocoarynth's own documents look different from those of farms, labs, carriers, and retailers. Rendering uses fonts installed on macOS.
