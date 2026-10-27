# Offline ontology, topics, and graph

This bundle contains the Cocoarynth business ontology and fact graph, native GRZ topic communities, **all 106 captured source vectors**, and a document/topic/chunk sitemap. The business layer is unchanged: **39 classes, 255 properties, 503 entities, and 3,938 graph assertions**, including 1,539 entity relationships.

Topic preparation used only task-owned indexes on the authorized service `magottei-s1m-os`; pre-existing indexes, source files, and access settings were not changed. No model was called and no source embeddings were regenerated. The resulting files can be read offline or uploaded later without re-embedding the captured text.

The Foundry-IQ-Skills binaries match **iteration 47** of [ADO PR 2344752](https://msdata.visualstudio.com/Azure%20Search/_git/Foundry-IQ-Skills/pullrequest/2344752), commit `7389ee18f277f24e9f6578975c3e5dfdd80e1a61`. GRZ used the matching checksum-pinned **0.1.4-local** native executable, not the incompatible 0.1.5 package. The business ontology retains its offline import, review, explicit user approval, export, and consume history. The upstream PR describes its package as not release/demo-ready.

## Business graph files

| File | Purpose |
| --- | --- |
| [cocoarynth-ontology.json](cocoarynth-ontology.json) | Complete classes, properties, domains, ranges, and descriptions; accepted by `ontology-build import`. |
| [cocoarynth-ontology.owl](cocoarynth-ontology.owl) | Approved flat-OWL schema, in RDF/XML, with namespace `urn:ontology:cocoarynth#` and no external imports. |
| [cocoarynth-graph.jsonld](cocoarynth-graph.jsonld) | General RDF instance graph: 4,227 distinct triples. Its context is embedded; it is not the restricted inline ontology input for managed EKG extraction. |
| [cocoarynth-entities.jsonl](cocoarynth-entities.jsonl) | Entity identities, labels, types, and unchanged structured source records. |
| [cocoarynth-graph-provenance.jsonl](cocoarynth-graph-provenance.jsonl) | Each assertion ID joined to its source file, JSON pointer or captured JSONL line, and source chunk. |
| [cocoarynth-query-checks.json](cocoarynth-query-checks.json) | Fifteen offline traversal fixtures and 32 typed-value assertions covering M1-M7 and source-specific edge cases; not executable Search GQL or complete natural-language answers. |
| [manifest.json](manifest.json) | Source and artifact hashes, exact runtime provenance, approval identity, counts, limitations, and the restoration contract for the whole bundle. |
| [validation.json](validation.json) | Business, topic, vector, and navigation checks, with the scope of service checks kept explicit. |

Three Search snapshots each pair an index definition with document rows:

| Index | Definition | Records |
| --- | --- | --- |
| `cocoarynth-graph-sources` | [Definition](cocoarynth-graph-sources-index.json) | [609 source chunks](cocoarynth-graph-sources-exported.jsonl) |
| `cocoarynth-ontology` | [Definition](cocoarynth-ontology-index.json) | [288 native ontology rows](cocoarynth-ontology-exported.jsonl) |
| `cocoarynth-graph` | [Definition](cocoarynth-graph-index.json) | [3,938 assertion rows](cocoarynth-graph-exported.jsonl) |

The ontology and assertion indexes use the native `edgeList` graph profile and `graph_name=cocoarynth`. The native ontology-index projection contains class and object-relationship metadata; the full subclass hierarchy and datatype declarations remain in the JSON/OWL schema.

## Topic and vector snapshots

| Snapshot | Definition | Records |
| --- | --- | --- |
| Original source chunks and vectors | [Source definition](cocoarynth-topic-sources-index.json) | [106 complete captured rows](cocoarynth-topic-sources-exported.jsonl), including every `text_vector` |
| Native GRZ sidecar | [Sidecar definition](cocoarynth-topics-index.json) | [273 rows](cocoarynth-topics-exported.jsonl): 8 representatives, 158 memberships, 106 evidence records, and 1 manifest |
| Vectors for all topics | [Topic-vector definition](cocoarynth-topic-vectors-index.json) | [8 vectors](cocoarynth-topic-vectors-exported.jsonl), each labeled with its calculation method |

All source and topic vectors have **3,072 dimensions**, in the captured `text-embedding-3-large` space. Source rows retain all eight original fields: `chunk_id`, `parent_id`, `title`, `blob_path`, `chunk`, page bounds, and `text_vector`. Their stored float32 values survive the Search round trip unchanged. The index definitions store vectors without a vectorizer; new text queries still need a compatible query vector or embedding deployment.

The native run produced a ragged forest of **8 communities across 2 levels**, with 4 roots. It supplied vectors for **6 terminal communities**, including 2 terminal roots. The native sidecar preserves that output: its other 2 representatives have no native vector. The separate topic-vector snapshot adds **2 normalized parent centroids**, calculated from their member chunks' normalized source vectors. These are explicitly marked `derived-parent-...`, never presented as native artifacts.

Native probing assigned **97 of 106 chunks (91.51%)**. The remaining **9 chunks retain their text, vectors, document links, and explicit unassigned status**; no community membership was invented for them. The GRZ consumer reports `CHUNK_UNASSIGNED` for those chunk lookups. Read their text and vectors from the source snapshot; use the sitemap for their document/chunk links. GRZ's `source_document_count=106` counts Search chunk documents, not the 55 PDF files.

GRZ's `visibility=public` marks this synthetic corpus's eligibility; it does not make the Search indexes anonymously accessible.

Communities are intentionally unnamed: display labels identify native community IDs, not generated topic names or summaries. The [build record](cocoarynth-topics-build.json) records parameters, coverage, vector methods, and provenance. The [native receipt](native/receipt.json) and its companion files preserve the genuine hierarchy and raw representative vectors, including [representatives.f32](native/representatives.f32). The receipt's `FullCorpusExported=false` describes the native probe output; the separate source snapshot contains all 106 original vectors.

The [restore record](cocoarynth-topics-restore-check.json) records complete source/sidecar/vector readback and vector queries on `magottei-s1m-os`. It does not establish EKG, GQL, grounding, or knowledge-base compatibility.

## Sitemap

The [sitemap JSON](cocoarynth-sitemap.json) contains **169 nodes and 379 edges**. Its 55 `Document` nodes reuse the exact document URNs in the business graph; its other nodes are 106 `TextChunk` records and 8 `Topic` communities.

| Relation | Count | Meaning |
| --- | --- | --- |
| `hasTextChunk` | 106 | Original PDF-to-chunk membership, including unassigned chunks |
| `hasTopicMember` | 158 | Actual native memberships at each represented level |
| `hasNarrowerTopic` | 4 | Direct native parent-to-child topic edges |
| `hasMemberDocument` | 111 | A topic contains at least one captured chunk of the PDF, not necessarily the whole document |

These are topic-navigation relations, not physical `Site` links or lexical `mentionsEntity` edges. The navigation vocabulary is additive, under `urn:ontology:cocoarynth-navigation#`, and is defined in the sitemap JSON. It does not change the approved business OWL or register a managed EKG ontology.

Use the [JSON-LD projection](cocoarynth-sitemap.jsonld) for RDF tooling. A separate [native `edgeList` definition](cocoarynth-sitemap-graph-index.json) and [379 assertion rows](cocoarynth-sitemap-graph-exported.jsonl) use `graph_name=cocoarynth-sitemap`. Each edge has [provenance](cocoarynth-sitemap-provenance.jsonl) linking it to unchanged captured chunk IDs and, where applicable, the native hierarchy.

## Meaning and evidence

**A batch is one production run; a bean lot is an incoming quantity of beans.** The wrapper's lot code identifies a batch. For example, `EC26-0811` is `madeFrom` bean lot `EC26-L07`; incoming `contributedTo` relationships identify only Finca Las Brisas and Finca El Cedro, not every farm at the same origin. Measured joins retain their own farm-contribution, batch-input, and shipment-line records.

Entity URNs include their class. Nested records use deterministic source-position keys, not new business identifiers; changing source order can change those keys. Numeric and Boolean values remain typed. Date-only values remain strings rather than acquiring invented timestamps. Logger timestamps combine only the recorded date, time, and explicit offset; the device measures **air beside a pallet**, not chocolate temperature.

The business evidence index combines 503 structured record chunks with all 106 captured text chunks from the existing 55 PDFs. That index remains text-only; the separate topic source snapshot includes all original PDF vectors. Original chunk IDs, parent IDs, page bounds, text, and portable blob paths are preserved. World-data chunks point to local JSON records, not invented PDF citations. Input-file checksums are in the manifest.

Bundle text files are pinned to LF by the local `.gitattributes`, except `native/`, whose producer bytes are preserved exactly, including CRLF JSON and binary files. Source-input hashes describe the Git blob bytes at the recorded source commit: normalize working-tree CRLF to LF for UTF-8 text before comparison; PDFs and native artifacts use exact bytes.

`mentionsEntity` means an existing PDF chunk contains an explicit entity name or identifier. It is a lexical navigation aid, not exhaustive entity resolution and not proof of every attribute or relationship about that entity. Source facts come from `world/`; hypothetical examples in `data/README.md` were not added.

No certificate is inferred from a certification-status record. Pending findings stay pending even when a scheduled follow-up date has passed. The sensory sample's literal `DR26-T03 bench batch` is preserved without inventing a twelfth production batch. Confidence `1.0` denotes deterministic source projection, not independent verification. Nulls remain in source records but do not become graph assertions.

The graph includes the corpus's fictional people. Its presence does not override the [data-sharing policy](../cocoarynth/documents/cocoarynth-policies/data-sharing-policy.pdf): customer-facing farm tracing must not disclose farmer personal details. Sell-in remains manufacturer-to-retailer volume, including replacement and pre-launch stock; it is not consumer sell-through.

## Import later

For generic RDF tooling, import `cocoarynth-ontology.owl` as the business schema, `cocoarynth-graph.jsonld` as business instances, and `cocoarynth-sitemap.jsonld` as additional navigation instances. The latter uses the separate vocabulary defined above.

For Search, explicitly select the destination, confirm its preview `edgeList` support before loading graph indexes, and ensure the listed names will not overwrite unrelated indexes. Follow `manifest.json` under `restore` for all seven definition/record pairs. Create each index from its JSON definition and wrap its JSONL rows as `docs/index` upload batches with `@search.action=upload`. Respect both the 1,000-document and 16-MB request limits, including the request envelope, and inspect every result. Preserve index names, generation IDs, URNs, chunk IDs, and both `graph_name` values. The native helpers use API version `2026-08-01-preview`.

The GRZ runtime can browse the delivered files without Azure access. From the repository root, with the verified runtime already available:

```powershell
grz-consume --descriptor .\data\graph-data\cocoarynth-topics-descriptor.json `
  --documents .\data\graph-data\cocoarynth-topics-documents.json status --json
```

The consumer's [document array](cocoarynth-topics-documents.json) keeps the manifest payload as an object; the upload JSONL encodes it as the Search string field. Do not interchange those formats. The [GRZ descriptor](cocoarynth-topics-descriptor.json) records the preparation service as source provenance. For live reads after restoring elsewhere, pass the chosen destination with `--endpoint` and appropriate read credentials rather than inferring the preparation endpoint. Preserve the generation's provenance and check GRZ status on that destination.

The existing [lab provisioning](../../infra/README.md) restores only the four original document/vector snapshots. It does **not** load these seven additional snapshots automatically.

## EKG compatibility and possible local re-ingestion

**Snapshot restoration is separate from preparing a managed EKG.** This bundle includes a GRZ snapshot descriptor, not an EKG serving descriptor, live graph registration, grounding index, or knowledge-base source bindings. Successful document/vector uploads do not establish GQL or managed EKG readiness.

Later lab setup may require local re-ingestion or an explicit compatibility mapping for EKG's source-field and key requirements, document/chunk identity alignment, ontology and graph registration, and grounding/knowledge-source bindings. The sitemap's `Topic`/`TextChunk` vocabulary and relations also need an intentional mapping or ontology registration if the EKG path will consume them; they are not additions to the approved business OWL.

Keep the captured `chunk_id`/`parent_id` values and PDF URNs when possible. If re-ingestion changes chunk IDs or boundaries, rebuild the dependent topic generation, memberships, sitemap, and evidence joins rather than silently editing an existing generation. Do not run managed extraction into these restored snapshots. A separate managed build can consume the business OWL and will need its own graph identity and serving checks.
