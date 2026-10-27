# Offline ontology and graph

This bundle projects the existing fictional Cocoarynth world records into an ontology and graph. It contains **39 classes, 255 properties, 503 entities, and 3,938 graph assertions**, including 1,539 entity relationships. No data was uploaded, no model was called, and no vectors were regenerated.

The current Foundry-IQ-Skills PR binaries were verified at commit `7389ee18f277f24e9f6578975c3e5dfdd80e1a61`. The ontology passed their offline import, review, explicit user approval, export, and consume workflow. The index definitions and ontology-index rows use the EKG wheel's native helpers. The upstream PR describes these binaries as not release/demo-ready; this bundle does not establish live service compatibility.

## Files

| File | Purpose |
| --- | --- |
| [cocoarynth-ontology.json](cocoarynth-ontology.json) | Complete classes, properties, domains, ranges, and descriptions; accepted by `ontology-build import`. |
| [cocoarynth-ontology.owl](cocoarynth-ontology.owl) | Approved flat-OWL schema, in RDF/XML, with namespace `urn:ontology:cocoarynth#` and no external imports. |
| [cocoarynth-graph.jsonld](cocoarynth-graph.jsonld) | General RDF instance graph: 4,227 distinct triples. Its context is embedded; it is not the restricted inline ontology input for managed EKG extraction. |
| [cocoarynth-entities.jsonl](cocoarynth-entities.jsonl) | Entity identities, labels, types, and unchanged structured source records. |
| [cocoarynth-graph-provenance.jsonl](cocoarynth-graph-provenance.jsonl) | Each assertion ID joined to its source file, JSON pointer or captured JSONL line, and source chunk. |
| [cocoarynth-query-checks.json](cocoarynth-query-checks.json) | Fifteen offline traversal fixtures and 32 typed-value assertions covering M1-M7 and source-specific edge cases; not executable Search GQL or complete natural-language answers. |
| [manifest.json](manifest.json) | Source and artifact hashes, exact wheel provenance, approval identity, counts, limitations, and the restoration contract. |
| [validation.json](validation.json) | Recorded offline artifact checks; not a live retrieval-quality evaluation. |

Three Search snapshots each pair an index definition with document rows:

| Index | Definition | Records |
| --- | --- | --- |
| `cocoarynth-graph-sources` | [Definition](cocoarynth-graph-sources-index.json) | [609 source chunks](cocoarynth-graph-sources-exported.jsonl) |
| `cocoarynth-ontology` | [Definition](cocoarynth-ontology-index.json) | [288 native ontology rows](cocoarynth-ontology-exported.jsonl) |
| `cocoarynth-graph` | [Definition](cocoarynth-graph-index.json) | [3,938 assertion rows](cocoarynth-graph-exported.jsonl) |

The ontology and assertion indexes use the native `edgeList` graph profile and `graph_name=cocoarynth`. The native ontology-index projection contains class and object-relationship metadata; the full subclass hierarchy and datatype declarations remain in the JSON/OWL schema.

## Meaning and evidence

**A batch is one production run; a bean lot is an incoming quantity of beans.** The wrapper's lot code identifies a batch. For example, `EC26-0811` is `madeFrom` bean lot `EC26-L07`; incoming `contributedTo` relationships identify only Finca Las Brisas and Finca El Cedro, not every farm at the same origin. Measured joins retain their own farm-contribution, batch-input, and shipment-line records.

Entity URNs include their class. Nested records use deterministic source-position keys, not new business identifiers; changing source order can change those keys. Numeric and Boolean values remain typed. Date-only values remain strings rather than acquiring invented timestamps. Logger timestamps combine only the recorded date, time, and explicit offset; the device measures **air beside a pallet**, not chocolate temperature.

The evidence index combines 503 structured record chunks with all 106 captured text chunks from the existing 55 PDFs. Original PDF chunk IDs, parent IDs, page bounds, text, and portable blob paths are preserved, without copying their vectors. World-data chunks point to local JSON records, not invented PDF citations. Input-file checksums are in the manifest.

Bundle text files are pinned to LF by the local `.gitattributes`, so artifact hashes survive Windows and Linux checkouts. Source-input hashes describe the Git blob bytes at the recorded source commit: normalize working-tree CRLF to LF for UTF-8 text before comparison; PDF hashes use exact binary bytes.

`mentionsEntity` means an existing PDF chunk contains an explicit entity name or identifier. It is a lexical navigation aid, not exhaustive entity resolution and not proof of every attribute or relationship about that entity. Source facts come from `world/`; hypothetical examples in `data/README.md` were not added.

No certificate is inferred from a certification-status record. Pending findings stay pending even when a scheduled follow-up date has passed. The sensory sample's literal `DR26-T03 bench batch` is preserved without inventing a twelfth production batch. Confidence `1.0` denotes deterministic source projection, not independent verification. Nulls remain in source records but do not become graph assertions.

The graph includes the corpus's fictional people. Its presence does not override the [data-sharing policy](../cocoarynth/documents/cocoarynth-policies/data-sharing-policy.pdf): customer-facing farm tracing must not disclose farmer personal details. Sell-in remains manufacturer-to-retailer volume, including replacement and pre-launch stock; it is not consumer sell-through.

## Import later

For generic RDF tooling, import `cocoarynth-ontology.owl` as the schema and `cocoarynth-graph.jsonld` as instances.

For a compatible Search service, follow `manifest.json` under `restore`: create and load the source, ontology, then assertion index. Use each definition unchanged and wrap JSONL rows as `docs/index` upload batches with `@search.action=upload`; respect both the 1,000-document and 16-MB request limits and inspect every result. Preserve URNs, chunk IDs, and `graph_name` across all three indexes. The pinned native helper uses API version `2026-08-01-preview`; confirm the destination supports its preview graph profile before importing.

These are **offline snapshots, not a published managed EKG**. They do not include a serving descriptor, live graph registration, or knowledge-base source bindings. Do not run managed extraction into these indexes or assume graph queries work merely because an index upload succeeds. A later managed build can consume the OWL separately and will need its own approved plan and graph identity.

The existing [lab provisioning](../../infra/README.md) restores only the four original document/vector snapshots; it does **not** load this bundle automatically.
