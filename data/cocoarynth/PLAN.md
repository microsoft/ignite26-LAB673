# Cocoarynth sample-data rebuild plan

Rebuild the Cocoarynth lab corpus from scratch. Keep the company name and the shape of the business: a small bean-to-bar, single-origin chocolate maker that buys from several farms in several countries and sells through several retailers. No existing figures, IDs or prose need to survive, and the data no longer has to match the `cocoarynth-trace` app.

## Decisions

| Topic | Decision |
| --- | --- |
| Company | Keep the name Cocoarynth. |
| App consistency | Not required. |
| Lab focus | Fun mystery questions, not the Mapayca export. |
| Format | PDF only, with charts and images. |
| Engineering-practices corpus | Remove. |
| Images | MAI-Image-2.5 (`MAI_IMAGE_ENDPOINT`, `MAI_IMAGE_KEY` in `.env`) and Wikimedia Commons **CC0 only**. |
| Size | About 50 PDFs across four search indexes; may grow. |
| Excluded topics | Heavy metals and other toxic contaminants; mock recalls. |
| Languages | English, plus Spanish for farm records from Ecuador, Peru and the Dominican Republic. Madagascar and Ghana records are in English. |

## Lab story

Participants are Cocoarynth's new data analyst. Each notebook question is a short mystery. Participants run the notebook, follow the citations, and arrive at a one-sentence answer anyone can understand.

| # | Mystery | Expected answer | What it exercises |
| --- | --- | --- | --- |
| 1 | Why are the Ghana bars turning white at one retailer? | The pallet waited six hours in an unrefrigerated overflow bay at 34 °C during a heat wave, causing heat bloom. Retained bars from the same batch are fine. | Logger chart, retailer photos, quality records; several sources |
| 2 | Which farms are in the bar I'm holding? | From a photographed wrapper lot code: batch → bean lot → the two contributing farms. | Reading an image; tracing through several documents |
| 3 | Why do the Dominican beans taste smoky? | They dried beside a wood-fired dryer chimney. The lot was rejected and the farm moved its drying racks. | Spanish field notes, sensory report, corrective action |
| 4 | Can we print the Organic seal on the Peru bar? | No. The renewal is still pending after an inspection finding about spraying in a buffer zone. | Policy plus inspection report; Part A file source |
| 5 | Why did the Madagascar launch slip a month? | Beans arrived too wet and had to be re-dried before release. | Dates spread across several documents |
| 6 | Which origin won the tasting panel, and what did tasters notice? | Read from sensory radar charts and panel notes. | Reading a chart |
| 7 | Capstone: Which origin did we pay the most for, and was it worth it? | Combines purchase prices, sensory scores and sales charts. | All sources |

Each answer must be reachable only from the corpus, and must need at least one citation that participants can open and verify.

## Questions for the new Foundry IQ retrieval strategies

The lab also demonstrates two new indexing and retrieval strategies. Phrase every question as a real employee would: who is asking, why, and what they type. Graph paths and expected answers are hidden fields in `questions.yaml`. Test each question against standard retrieval as well, to confirm that the intended strategy is what makes it succeed.

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
- **More documents.** Expect about 70 rather than 50, because themes need repetition and entity questions need extra reports and lookalikes.

## Knowledge sources

| Search index | Contents | Approx. PDFs |
| --- | --- | --- |
| `cocoarynth-origins` | Origin profiles, farm inspection reports, scanned collection tickets, fermentation and drying logs (some in Spanish), purchase contracts, origin transparency report with maps and price charts | 14 |
| `cocoarynth-quality` | Bean receiving procedure, cut-test register, lab moisture and microbiology certificates, sensory panel reports with radar charts, batch records, nonconformance and corrective-action records | 14 |
| `cocoarynth-logistics-retail` | Bills of lading, temperature-logger reports with charts, warehouse receipts, retailer agreements, orders, complaint emails rendered as PDFs with photos, quarterly sales deck | 14 |
| `cocoarynth-policies` | Label-claims policy, data-sharing policy, glossary, organization chart, sourcing principles | 8 |

- **Part A** (file knowledge source) uploads the label-claims policy and asks mystery 4.
- **Part B** creates the four indexed knowledge sources and one combined knowledge base, then works through the remaining mysteries. Participants inspect the activity log to see which sources were searched.

## World

| Element | Plan |
| --- | --- |
| Company | Bean-to-bar factory and one flagship shop. Departments: Sourcing, Quality, Production, Sales, Data. |
| Origins | Five: Ecuador, Ghana, Peru, Madagascar, Dominican Republic. Supplier types: two cooperatives, one single estate, one producer association, one new trial origin. New region and supplier names that don't echo Dandelion Chocolate or other real makers. |
| Farms | Two to four per origin, about 14 in total. Some lots combine farms, keeping the single-origin versus single-farm distinction. |
| Seasons | 2025 and 2026 harvests. |
| Products | One single-origin bar per origin, a high-cocoa bar, a limited edition, a blend. |
| Retailers | Five: regional grocer, specialty shop, online marketplace, café group, overseas distributor. Each has different data-sharing terms. |
| Partners | Importer, freight forwarder, cold-chain carrier, independent lab, certification body, packaging supplier. |
| People | Fictional names with roles only; no real contact details. |

## Repository layout

```text
data/cocoarynth/
  world/*.json      structured facts: origins, farms, lots, tests, batches, shipments, readings, retailers, sales, prices, cases
  questions.yaml    the mysteries: question, expected answer, required documents, required visuals
  briefs/<index>.yaml  one file per search index listing its PDFs: type, language, date, author, entities, content, visuals, things to avoid
  briefs/assets.yaml   every chart, map, diagram, photo (MAI prompt) and derived image the briefs reference
  drafts/*.md       free prose with placeholders such as {{ lot.X.moisture_pct }}, {{ chart: name }}, {{ image: name }}
  assets/           MAI photos, charts, derived scans and labels, fonts/ (SIL OFL) and brand/ (Cocoarynth logos from cocoarynth-trace)
  documents/<index>/  rendered PDFs (the lab's indexed inputs)
scripts/cocoarynth/
  validate.py       ID references, mass balance, date order, units
  charts.py         charts drawn from world data
  images.py         MAI generation, Wikimedia download, text overlays, scanned-paper effect
  render.py         Markdown + Jinja → HTML with per-organization house styles → PDF (Playwright Chromium); writes corpora.json
  handwriting.py    handwriting and scanned-paper effects for scanned forms
  ask_mysteries.py  asks the mysteries against a live knowledge base and scores evidence recall
```

### Conventions

- `world/` is the single source of truth. Charts and tables are generated from it, so they never disagree.
- Prose in `drafts/` is ordinary Markdown, free to vary in tone, layout and length.
- Lot codes and label text are drawn onto images in code, because generated images garble text.
- Some logs and tickets are rasterized with skew and noise, so reading them requires the image, not a text layer.
- Scanned forms: printed parts come from HTML; handwriting is drawn per character by `scripts/cocoarynth/handwriting.py` with SIL OFL fonts in `assets/fonts/` (one hand per writer, random angle/baseline/size/ink, slight warping), then composited onto paper with folds, stains, uneven light, perspective and JPEG noise. Codes and weights use a print-style hand so they stay legible.
- House styles: the issuing organization sets the look (`HOUSE` in `render.py`). Cocoarynth documents use the brand from the `cocoarynth-trace` app: logo in `assets/brand/`, a cocoa band with a yellow rule, Georgia headings, Inter body text (OFL, static weights in `assets/fonts/Inter-*.ttf`) and the app palette. Cooperatives use a centered Times letterhead, the estate Palatino, the certifier and lab a formal Verdana layout, freight companies boxed Arial Narrow forms with typed values, and retailers a plain mail-client look.
- Every image records its origin in `assets/manifest.json`. Wikimedia files must be CC0; check each file's license page before use.
- If chart values turn out not to be retrievable, also state each clue value in a nearby table or caption.

### MAI image generation

- `MAI_IMAGE_ENDPOINT` holds only the resource name. Build the URL as `https://${MAI_IMAGE_ENDPOINT}.services.ai.azure.com/mai/v1/images/generations`.
- Pass `MAI_IMAGE_KEY` to the script as `AZURE_API_KEY`. Never print or commit the key.
- The model accepts at most 1,056,768 total pixels. Use 1248×832 for landscape photos and 1024×1024 for square ones.
- Prompts should ask for no people, text or logos unless needed.

## Realism references

Use these for the kinds of records, fields and practices to include. Don't copy their text, data or layouts.

- [Rainforest Alliance farm-requirement checklists](https://knowledge.rainforest-alliance.org/docs/checklist-for-sustainable-agriculture-standard-farm-requirements) and [Management Annex v1.2](https://knowledge.rainforest-alliance.org/docs/management-annex-v12): internal farm inspections, findings and follow-up.
- [CAOBISCO/ECA cocoa bean quality requirements](https://qm.cocoaquality.eu/) and [inspection, sampling and traceability](https://pm.cocoaquality.eu/good-warehouse-practices/inspection-sampling-documentation-and-traceability): cut test categories (mouldy, slaty, purple, insect-damaged, germinated, flat), moisture around 7.5–8%, off-flavours.
- [Cacao of Excellence sensory evaluation form](https://www.cacaoofexcellence.org/resources/resource/sensory-evaluation-form-for-cacao-and-chocolate) and [assessment guide](https://www.cacaoofexcellence.org/resources/resource/guide-for-the-assessment-of-cacao-quality-and-flavour): sensory attributes and scoring.
- [Cargo Handbook: cocoa beans](https://cargohandbook.com/Cocoa_Beans) and [ICCO trading and shipping](https://www.icco.org/trading-shipping/): container preparation, condensation, custody handoffs.
- [Dandelion Chocolate origins page](https://www.dandelionchocolate.com/pages/origins) and sourcing reports: structure of a public origin report only. The downloaded 2025 report is copyrighted and must not be committed, ingested or quoted.

## Phases

1. **Spike.** *Rendering done* (the throwaway spike script has since been removed). Use JPEG, not PNG, for embedded photos to keep PDFs small. *Content Understanding check deferred* until a lab environment exists; until then every clue also appears in text, and phase 5 decides which clues become image-only.
2. **World and mysteries.** *Done:* `world/` (company, origins, beans, production, retail, sensory, commercial), `questions.yaml` with each mystery's answer and evidence chain, and `scripts/cocoarynth/validate.py`, which checks references, cut-test totals, date order, mass balance, bar counts, shipments against sell-in, organic claims and the facts behind every mystery answer.
3. **Briefs.** *Done:* 55 briefs (origins 16, quality 15, logistics-retail 16, policies 8). `validate.py` checks that every brief's entities, authors and assets resolve, and that every evidence item in `questions.yaml` cites existing documents.
4. **Assets, templates and rendering.** *Done:* 16 MAI photos, 13 charts and diagrams (`charts.py`), wrapper labels and 5 scanned forms (`images.py derived`), 55 drafts in `drafts/`, rendered by `render.py` into `documents/<index>/` (55 PDFs, 91 pages, about 11 MB). To rebuild: `validate.py`, `charts.py`, `images.py derived`, `render.py` (and `images.py photos` only for new photos).
5. **Testing.** *Done (13 October 2026):* ingested into a live environment, ran notebook 1 end to end, and scored the mysteries with `ask_mysteries.py`. With auto reasoning effort, M1, M3, M4, M6 and M7 cite all their evidence; M2 and M5 need a second round of searches (lot code first, then the origin record) and sometimes stop after one round. Medium effort finds everything. Snapshots exported to `data/index-data/` and restore verified.
6. **Lab integration.** *Done:* `corpora.json` generated from the briefs by `render.py` and checked by `validate.py`; ingestion, restore, export and snapshot-validation scripts use the four indexes and the label-claims policy as the file source; the notebook tells the Cocoarynth story and asks the mysteries; READMEs and `deploy_yourself.md` updated.
7. **Removal.** *Done:* engineering-practices corpus, the original Cocoarynth documents, the 40 old PDFs, `authoring/`, the old generator, Caldova data and script, all old index snapshots, and the spike. The copyrighted Dandelion report was moved out of the repository.

## Open items

- M2 and M5 are only partly answered at auto reasoning effort; revisit with newer knowledge base features.
- Optional: make some clues image-only now that Content Understanding reads the handwritten scans.
