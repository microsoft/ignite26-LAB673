# Data

The lab corpus is Cocoarynth Chocolate Works, a fictional bean-to-bar chocolate maker that buys cacao from farms in five countries and sells through several retailers. All documents are generated: no real company, person, or record is described.

- [Corpus manifest](cocoarynth/corpora.json): the PDFs in each of the four document groups, plus the label claims policy.
- `cocoarynth/documents/<index>/`: 55 PDFs, the indexed inputs.
  - `cocoarynth-origins`: farm and supplier records, partly in Spanish.
  - `cocoarynth-quality`: factory receiving, testing, tasting, and batch records.
  - `cocoarynth-logistics-retail`: shipping, carrier, retailer, and sales records.
  - `cocoarynth-policies`: company policies, guides, and reference material.
- [Mysteries](cocoarynth/questions.yaml): the lab questions with ground truth for measuring retrieval: the expected answer, and for each fact it needs, the documents that are valid citations.
- [Provenance](cocoarynth/provenance.json): how the corpus was generated, and the image, font, and logo sources.
- `index-data/`: the original four-domain ingestion captures, retained as maintainer source artifacts.
- `graph-data/`: the active three-index restore bundle, OWL files, and extraction provenance.

Provisioning restores `cocoarynth-chunks`, `cocoarynth-topics`, and `cocoarynth-graph` from the [active bundle](graph-data/README.md), without running Content Understanding or inference. The chunk index combines the 106 captured chunks from all 55 PDFs and adds a `domain` filter. Their text, IDs, citation fields, and embeddings are preserved. After changing the documents, [rebuild the snapshots](../infra/README.md#rebuild-the-index-snapshots).

## Graph index snapshots

The [graph index snapshots](graph-data/README.md) contain exactly three active indexes; setup also splits the chunk snapshot into three document-group indexes. The topic index stores eight named topics, their hierarchy and proportions, and six leaf centroids as edge-list facts. Roots are level 0; centroid queries retrieve similar chunks from the source index. The business graph contains 120 assertions for 91 distinct facts, with verbatim evidence excerpts resolving to the PDF-only chunk index.

[cocoarynth.owl](graph-data/cocoarynth.owl) records the compact PDF-derived business ontology; [cocoarynth-sitemap.owl](graph-data/cocoarynth-sitemap.owl) describes topic navigation. They are files, not indexes. Setup serializes their flat declarations as inline JSON-LD for the November ontology private preview.

`world/*.json` remains source material for generating the PDFs. It is **not** indexed as evidence and was not used to propose this ontology or extract the active business graph. The proposal and extraction are bounded model-generated artifacts, not a managed extraction run or a native ontology approval.

The hypothetical questions below remain future work; their placeholder entities and answers were not added to the graph.

## What's in each document group

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
| POL-03 Label and marketing claims policy | | M4 |
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
```

`validate.py` checks that the facts are consistent, that each mystery's answer follows from them, that every cited document exists, and that `corpora.json` lists every document. `render.py` builds the PDFs and rewrites `corpora.json`. New photos need MAI image credentials in `.env` and `images.py photos`.

The existing `scripts/cocoarynth/ask_mysteries.py` measures evidence recall against the original four-index ingestion captures, not the consolidated lab setup. Keep that maintainer evaluation in a separate capture environment. The lab notebooks instead create three knowledge sources over the document-group indexes that setup splits from `cocoarynth-chunks`.

### Authoring conventions

- `world/` is the source of truth for **document generation**, not graph extraction evidence. Charts and tables are generated from it, so they never disagree. Prose in `drafts/` is ordinary Markdown, free to vary in tone, layout, and length.
- Every mystery answer must come only from the corpus and cite at least one document that participants can open.
- Records from Ecuador, Peru, and the Dominican Republic farms are in Spanish; Madagascar and Ghana records are in English.
- Avoid heavy metals and other toxic contaminants, and mock recalls.
- Lot codes and label text are drawn onto images in code, because generated images garble text.
- Scanned forms: printed parts come from HTML. Handwriting is drawn per character by `scripts/cocoarynth/handwriting.py` with SIL OFL fonts in `assets/fonts/` (one hand per writer, random angle, baseline, size, and ink, slight warping), then composited onto paper with folds, stains, uneven light, perspective, and JPEG noise. Codes and weights use a print-style hand so they stay legible.
- House styles: the issuing organization sets the look (`HOUSE` in `render.py`). Cocoarynth documents use the brand from the `cocoarynth-trace` app: logo in `assets/brand/`, a cocoa band with a yellow rule, Georgia headings, Inter body text (static weights in `assets/fonts/Inter-*.ttf`), and the app palette. Cooperatives use a centered Times letterhead, the estate Palatino, the certifier Verdana, the lab Helvetica Neue, the freight forwarder boxed Arial Narrow forms, the carrier a Rockwell letterhead, and each retailer's email its own sender style. Rendering uses fonts installed on macOS.
- Embed photos as JPEG, not PNG, to keep PDFs small.
- MAI images: `MAI_IMAGE_ENDPOINT` holds only the resource name; the URL is `https://${MAI_IMAGE_ENDPOINT}.services.ai.azure.com/mai/v1/images/generations`, with `MAI_IMAGE_KEY` as the `api-key` header. Never print or commit the key. The model accepts at most 1,056,768 pixels: use 1248×832 for landscape photos and 1024×1024 for square ones. Prompts should ask for no people, text, or logos unless needed.

Use these for the kinds of records, fields, and practices to include. Don't copy their text, data, or layouts.

- [Rainforest Alliance farm-requirement checklists](https://knowledge.rainforest-alliance.org/docs/checklist-for-sustainable-agriculture-standard-farm-requirements) and [Management Annex v1.2](https://knowledge.rainforest-alliance.org/docs/management-annex-v12): internal farm inspections, findings, and follow-up.
- [CAOBISCO/ECA cocoa bean quality requirements](https://qm.cocoaquality.eu/) and [inspection, sampling and traceability](https://pm.cocoaquality.eu/good-warehouse-practices/inspection-sampling-documentation-and-traceability): cut-test categories, moisture around 7.5–8%, off-flavors.
- [Cacao of Excellence sensory evaluation form](https://www.cacaoofexcellence.org/resources/resource/sensory-evaluation-form-for-cacao-and-chocolate) and [assessment guide](https://www.cacaoofexcellence.org/resources/resource/guide-for-the-assessment-of-cacao-quality-and-flavour): sensory attributes and scoring.
- [Cargo Handbook: cocoa beans](https://cargohandbook.com/Cocoa_Beans) and [ICCO trading and shipping](https://www.icco.org/trading-shipping/): container preparation, condensation, custody handoffs.
- [Dandelion Chocolate origins page](https://www.dandelionchocolate.com/pages/origins) and sourcing reports: structure of a public origin report only. Their sourcing reports are copyrighted and must not be committed, ingested, or quoted.

## Open items

- With auto reasoning effort, M2 and M5 are sometimes only partly answered: each needs a second round of searches (lot code first, then the origin record). Medium effort finds everything. Revisit with newer knowledge base features.
- Optional: make some clues image-only, since Content Understanding reads the handwritten scans well.

## Future questions for new retrieval strategies

Not in the lab yet. These questions would demonstrate two new indexing and retrieval strategies. Phrase every question as a real employee would: who is asking, why, and what they type. When adding them, put the expected answers and citations in `questions.yaml`, and test each one against standard retrieval too, to confirm that the intended strategy is what makes it succeed. Names below (such as Harbor Foods or Loma Clara) are placeholders until the world data has them.

### Entity knowledge graph

These questions only succeed when facts from separate reports are connected through shared entities: farms, bean lots, batches, pallets, storage bays, trucks, carriers, inspectors, retailers.

| Who's asking | Question | Connection required | Answer |
| --- | --- | --- | --- |
| Quality lead handling a complaint | Harbor Foods says the Ghana bars they got last week look chalky. Has this happened with anything else that went through the same warehouse? | Complaint → shipment → storage bay → other incidents there | Yes; another pallet waited in the same unrefrigerated overflow bay in July and bloomed the same way. |
| Sourcing manager before a supplier call | I'm calling Loma Clara about the smoky beans. What did we ask them to fix last time, and did they do it? | Rejection → farm (named differently) → earlier inspection → follow-up | Move the drying racks away from the dryer chimney; the follow-up visit found it hadn't happened yet. |
| Customer service agent | A customer emailed a photo of their wrapper and wants to know which farm grew the beans. Can we tell them? | Lot code in image → batch → bean lot → farms | Two Esmeraldas farms, Las Brisas and El Cedro. |
| Account manager | Northstar is asking whether this month's bars use the same beans as the batch that went white in July. Do they? | Two batches → their bean lots → compare | No; different bean lots, harvested a month apart. |
| Quality lead | Our tasters loved the raspberry-like Madagascar lot. Were there any problems with it on arrival? | Tasting report → bean lot → arrival hold | Yes; it arrived too wet and was re-dried, which is also why the launch slipped. |
| Auditor preparing a visit | We're auditing the Peru cooperative next week. Which farms have open findings, and have any of their beans already gone into bars we sold? | Farms with open findings ∩ farms supplying shipped batches | La Quebrada; its beans went into the August batch sold to two retailers. |
| Logistics manager | Are the truck breakdown, the late Madagascar delivery, and the gap in QA's temperature logs all the same problem? | Three separate reports → one consignment | Yes; all from the same June consignment. |
| Logistics manager choosing a carrier | We're thinking of dropping our cold-chain carrier. Which retailers have had damaged deliveries while their goods were with that carrier? | Carrier → shipments → incidents → retailers | Northstar and the café group. |
| Marketing writer | What's different about this year's Ecuador bar compared with last year's? I'm updating the label story. | 2025 vs 2026 batches → contributing farms → difference | A second farm, El Cedro, joined in 2026. |

### Global, corpus-wide summaries

These questions need themes that recur across many documents in different words. No single document may summarize them.

| Who's asking | Question | Kind of answer |
| --- | --- | --- |
| Operations director preparing a quarterly review | What went wrong most often this year, from farm to shelf? | Heat in storage and transit, wet beans on arrival, drying problems; with examples. |
| Quality lead | What are the most common causes of quality problems across our origins? | Heat during transit and storage, wet beans on arrival, drying practices such as smoke exposure. |
| New customer-service hire | What do retailers usually complain about, and how have we handled it? Does it change by season? | Summer bloom and softness, broken bars from packaging, late holiday deliveries; usual fixes. |
| New sourcing associate | How do our origins differ in how they ferment and dry beans? | Short comparison by country. |
| Head of sourcing planning next year | What should we worry about for next harvest season? What are the biggest risks to next year's supply? | Rainy-season drying, dependence on one supplier, a pending organic renewal, summer warehouse space. |
| Marketing | What do our tasters keep saying about each origin? I need one line for each bar. | One flavor line per origin. |
| CEO | Are our farm inspections actually leading to improvements? Which findings come up most? | Most findings concern drying or record-keeping; most are fixed with cheap physical changes; one remains outstanding. |
| Sourcing director | How did our relationship with each origin change from 2025 to 2026? | Volumes, prices, new farms, a rejection, a renewal. |
| New employee | What does a typical bar's journey from farm to shelf look like, and where does it usually go wrong? | Summarized journey with common failure points. |

### What the world needs for these questions

- **Graph design in `world/`.**
  - Entity types: Farm, Supplier, BeanLot, Batch, Product, Consignment, Pallet, Truck, Port, StorageBay, Logger, Inspector, Inspection, Finding, Retailer, Complaint, Person.
  - Relationship types: SUPPLIED, CONTRIBUTED_TO, MADE_FROM, SHIPPED_ON, STORED_AT, INSPECTED, FOUND, RESOLVED_BY, COMPLAINED_ABOUT, RECEIVED.
- **Aliases.** Each entity has several names (ID, nickname, translation, description such as "the second pallet off the truck"). Briefs pick different names in different documents.
- **Lookalikes.** For example, two farms named La Esperanza in different countries, and two inspectors who share a surname, so the graph must tell entities apart.
- **Theme table.** Each corpus-wide theme lists the documents that carry it and the varied wording each uses.
- **More documents.** Expect about 70 rather than 55, because themes need repetition and entity questions need extra reports and lookalikes.
