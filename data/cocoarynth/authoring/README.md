# Cocoarynth document generation

This directory holds editable prose and structured evidence for the 40 generated operational PDFs in `..\documents`. The shipment-quality story extends existing events; it does not change application behavior, historical shipment quantities or original controlled documents.

## Reproduce

From the repository root, use Python 3.10 or later and a task-local virtual environment. PowerShell example:

```powershell
python -m venv .venv-cocoarynth
.\.venv-cocoarynth\Scripts\python.exe -m pip install -r scripts\requirements-cocoarynth.txt
.\.venv-cocoarynth\Scripts\python.exe scripts\generate-cocoarynth.py --output .\cocoarynth-preview
```

On macOS/Linux use the environment's `bin/python` and forward-slash path separators. The requirements file explicitly selects the approved Microsoft CFS PyPI feed and pins direct dependencies. No cloud account, application checkout, Windows font or external generation service is required.

Review the preview before using `--output data\cocoarynth\documents`. The renderer has a fixed 40-filename allowlist: it cannot write the eight original PDFs. It validates sources, renders into a temporary directory and checks every PDF's text, glyphs, bounds and pagination before copying any output. Existing unrelated files are left alone. A filesystem failure during the final copy can leave a partial *generated* set; rerun after resolving it. Source-validation or rendering failure writes no destination PDFs.

Identical source, Python and pinned dependency versions produce byte-identical PDFs on the verified environment. Compare output hashes when changing runtime or library versions; cross-platform byte identity is not a guarantee. Sources use UTF-8. Bundled Bitstream Vera fonts cover Spanish accents; the open font license and copyright notice remain in the installed ReportLab package (`fonts/bitstream-vera-license.txt`). No font binaries are copied into this repository. Letter and field-notebook paragraphs use PDF standard Times; tables use embedded Vera.

## Files and schema

`documents.json` defines titles, departments, dates, identities, language, genre and ordered content blocks. Blocks are `h`, `p`, `note`, `table`, `page`, `refs`, `link`, `evidence` and `science_sources`. An `evidence` block selects rows by exact fields and renders specified columns directly from `evidence.json`; do not copy those readings into prose tables. Column widths are positive fractions totaling one. `refs` resolve against generated or original companion PDFs for authoring validation only; they are not rendered in participant PDFs. Participants must discover connections through the records themselves.

`evidence.json` is the common chartable factual source. Collections contain natural `id` values and actual companion `document` filenames. Shipments join to batches and pallet groups; movements join pallets to staging positions and timestamps; readings join sensor and position to the relevant dwell window. Observations join sample cohorts to batches and, for retail stock, shipments. Packaging and ingredient issues join by batch and material-lot IDs. These are authoring inputs, not application fixtures or new app capabilities.

Decimal measurements and masses are strings to preserve precision. Use decimal arithmetic for mass accounts. Mass fields ending `_kg` are net kilograms; nominal bars are 70 g. Temperatures use `degC`; relative humidity uses `percent_RH`. Every time-bearing event has an ISO 8601 timestamp with an explicit UTC offset. Date-only historical anchors deliberately remain date-only: they do not establish a time of day. Convert timestamps to UTC before joining different locations.

Evidence `basis` distinguishes `observed`, `calculated` and `provisional` within the scenario; it is not a claim of real-world measurement or approval. Coverage includes instrument placement, sampling interval, declared temperature uncertainty and explicit missing timestamps. Logger values measure air, not chocolate-core temperature. Recipient and factory room checks are isolated points, not continuous coverage. No calibration certificate or RH uncertainty is supplied.

Observations are repeated non-destructive checks of the **same cohort**. Use `sample_id` and `n` for a dated proportion; never sum dates or extrapolate sample counts to a whole shipment. Clear inner film permits inspection with the paper sleeve displaced and the film seal unopened. No specimen is consumed, so these checks do not change retention or factory balances. Northstar's historical 40-bar arrival damage remains separate from its later accepted-stock surface cohort.

## Canonical source and additions

The other repository is [`pamelas-organization/cocoarynth-trace`](https://github.com/pamelas-organization/cocoarynth-trace/tree/a0b02a0579a8667c3d1bac7d1f5001ab0a0b0f77), pinned at `a0b02a0579a8667c3d1bac7d1f5001ab0a0b0f77`. Relevant source files are `server/data/{origins,products,batches,shipments}.ts`, `server/services/originPassport.ts`, `server/routes/passports.ts` and `shared/types.ts`. Product/producer names, stage operators, batch IDs, production and packing dates, shipment IDs, recipients and application statuses are established anchors, not newly authored outcomes.

The local document baseline is `50e33f72404ebd3768bcefe08ba0f5c9e27bed14`. Its 40 additions establish the expanded mass accounts, fixed receipts, unresolved arrival damage and separate support/integration cases. The eight original Cocoarynth PDFs establish controlled requirements. They take precedence over the additions. The 37 Caldova PDFs concern a separate company and are not connected.

Newly authored gaps are Oceanbridge routes and depot positions, pallet groups, air/RH readings and coverage, later surface complaints, selected control specimens, transparent-wrapper-lot relationships and purchased-ingredient lot identities. Ingredient issue times are new booked-record timestamps on established start dates; they do not change stage completion. These additions are not evidence that the app implements ingredients, transport sensors, QA sampling, quarantine, persisted replacements or CSV export.

Canonical distinctions remain intact: Río Verde is not a single farm for the two-farm June intake; Mapayça's completion-date CSV requirement is not the app's start-date JSON output; Peru Piura Blanco 70% remains in quality review; Sambirano grinding is still underway; SUH-2026-031 is ready but unshipped. No new return, credit, customer dispatch, certification or safety clearance is created.

## Languages and corpus selection

The 80/20 convention is **generated PDF document count**, excluding immutable originals: exactly **32 English and 8 Spanish**. The Spanish operational records are `field-log`, `collection-notebook`, `drying-notebook`, `custody-statement`, `routing-card`, `stock-card`, `dispatch-receipt` and `order-note`. They are distinct evidence, not translations. IDs and company/product names retain their canonical spelling; both languages carry information needed for shipment, route, production and specimen joins.

Existing `corpora.json`, loader and original 4+4 corpus selection are unchanged. These additions are **not automatically ingested** by the lab. Select participant PDFs deliberately in any future ingestion change. Do not ingest this directory or instructor notes. No loader or lab redesign is included here.

## Technical limits

General mechanism sources are [Purdue / Universidad Nacional Agraria La Molina, *Cocoa Processing: Tempering*, FS-153-W](https://extension.purdue.edu/extmedia/FS/FS-153-W.pdf) and [Callebaut, *What is Chocolate Bloom?*](https://www.callebaut.com/en-US/node/4457). They support the plausibility of physical bloom mechanisms, not a Cocoarynth diagnosis, universal temperature limit or permission to consume complaint stock. The records supply no crystal-form, deposit-composition, water-activity or microbial result.

Instructor reasoning is deliberately separated in `INSTRUCTOR.md`. Participant PDFs end with evidence limits and open review questions, not an answer-giving causal report.
