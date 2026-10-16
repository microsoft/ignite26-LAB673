# Decision guide

## Quick starts

- "Do I need a graph for vendor impact questions?"
- "What does the policy say about per diems?"

## Techniques

| Technique | Domain | What it gives you | Leaf skills |
|---|---|---|---|
| Knowledge graph | ekg-skills | Entities and relationships from documents; multi-hop answers with a path and a cited source per hop | `ekg-provision`, `ekg-build`, `ekg-consume` |
| GraphRAG | grz-skills | A hierarchy of topics built from chunk vectors in a Search index, written to a separate `grz-*` index. Preview; public or synthetic data only | `grz-build`, `grz-consume` |
| Candidate ontology | ontology-skills | An OWL ontology proposed from a GRZ generation, refined, approved by you and exported as `.owl`. Preview | `ontology-build`, `ontology-consume` |
| Grounding index (optional) | grounding-skills | An index of known entities and edges (CSV, JSONL, Parquet or a bounded Wikidata seed) so a knowledge graph build resolves names to canonical IDs. Independent of GRZ | `grounding-provision`, `grounding-build`, `grounding-consume` |
| Entity workflow | entity-skills | Its own document-to-entity workflow: canonical resolution, relationships and a source quote per fact. Not a mandatory EKG stage | `entity-get-started`, `entity-provision`, `entity-build`, `entity-consume` (CLI `ents`) |
| Kusto graph | azure-kusto-graph-skills | Graph analysis of data already in Kusto or Azure Data Explorer | its own skills |

## Which retrieval

- **Plain retrieval:** the answer sits in one or two passages. Prefer the `foundry-iq` skill in `foundry-iq-skills`. EKG with ontology `none` is document retrieval only.
- **Knowledge graph:** no passage links vendor to customer, so vector search finds the vendor and stops. The graph walks vendor, project, customer and cites each hop.
- **GraphRAG:** themes across the corpus. It needs an index that already holds chunk vectors, no ontology, and never changes that index.

GraphRAG gives coverage and a knowledge graph gives precision; GraphRAG communities also feed a candidate ontology.

## Ontology for EKG

| Option | Pick it when |
|---|---|
| `none` | Document retrieval only; no graph is built |
| `schema_org` | No supplied OWL: use the built-in business ontology; not measured |
| `owl_file` | You bring or generate an OWL file. Measured: 17/17 on the Contoso demo |

## Hand-offs between domains

The runtimes are independent; these are artifact hand-offs only:

1. GRZ reads any Search index with chunk vectors, including EKG's. EKG's has no security field, so GRZ asks you to confirm the whole index is public.
2. ontology-skills reads a published GRZ generation.
3. ontology-skills exports an approved `.owl`, which EKG takes as `--ontology owl_file --ontology-path <file.owl>`. Add `--graph` at planning for multi-hop retrieval; preserve it through apply, verify and publish.
4. grounding-skills builds an index EKG takes as `--grounding-index <name>`. Its `graph_name` must match the EKG graph name and it needs label rows; `grounding-build` handles both.

Each domain owns its approvals. Nothing in Azure changes until you approve the exact change shown.

## Presentation

Optional Apps (ontology, EKG, GRZ; entity and grounding have none) render in a compatible host. A standalone viewer
(graph-presentation) calls the domain CLIs directly. Neither replaces the CLI route.

## Wrong premises

Both consume skills check a question's premise. Both corrected the one wrong-premise question in the
chain run: one question on one corpus, not a guarantee.
