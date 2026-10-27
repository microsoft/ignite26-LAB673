# Route table

## Quick starts

- "I have contract documents and need to know which vendors an outage affects."
- "My data is already in Kusto and I need graph paths."

## Pick one row

| You have | You want | Route | Ontology |
|---|---|---|---|
| Documents | One passage, with citations | `foundry-iq` skill in `foundry-iq-skills` | none |
| Documents | Facts from single passages through EKG | `ekg-provision` then `ekg-build` then `ekg-consume` | `none` |
| Documents, no OWL file | Multi-hop answers across people, organizations, projects, products | `ekg-provision` then `ekg-build` then `ekg-consume` | `schema_org` |
| Documents and an OWL file | Multi-hop answers in your domain | same EKG route | `owl_file --ontology-path <file.owl>` |
| A Search index with chunk vectors | Themes; what the corpus covers | `grz-build` then `grz-consume` | none needed |
| A published GRZ generation | A candidate ontology | `ontology-build` then `ontology-consume` | produces `.owl` |
| An existing ontology file | Re-review it, or extend it against a public corpus | `ontology-build`: offline import/review; extension needs a published GRZ generation and a priced proposal | n/a |
| An approved `.owl` | Multi-hop answers with it | `ekg-build`: 50-document trial first (go or no-go), then the full corpus with the trial report; see `graph-demo` | `owl_file` with the explicit exported path |
| Documents, no ontology, domain does not fit Schema.org | Multi-hop answers in your domain | full chain: `graph-demo` | derived `owl_file` |
| Only an Azure subscription | A new workflow | Pick the intended outcome first; use its owning provision skill, not EKG by default | route-specific |
| Known entities with canonical IDs, and a knowledge graph build | One ID per entity in answers | `grounding-provision`, `grounding-build`, `grounding-consume`, then EKG's grounding-index input | any except `none` |
| Data already in Kusto or Azure Data Explorer | Graph traversal there | `azure-kusto-graph-skills` | n/a |

A knowledge graph always needs an ontology: bring an OWL file, generate one with ontology-skills, or
use the built-in `schema_org`. GraphRAG needs none.

Reuse ready deployments: published EKG -> `ekg-consume`, published GRZ -> `grz-consume`;
an ontology to inspect -> `ontology-consume`. Do not route a read back through provisioning.
For EKG multi-hop answers, plan with `--graph`; ontology selection alone does not enable retrieval.

## Rules of thumb

- Two hops and no single document states the link: knowledge graph.
- Prefer `owl_file` when you have one; it is the measured option. `schema_org` is a reasonable start but is not measured.
- A question that starts from a wrong fact: `ekg-consume` and `grz-consume` check the premise first. That was measured on one question, so do not promise it.
- A full `owl_file` build of 1,000 documents took 9 h 45 min unattended. Say so before routing a large corpus to it.
- GRZ and ontology-skills are previews: public or synthetic data only. Ontology needs a published GRZ generation.
- Grounding is optional, independent of GRZ. Name the index before EKG planning; pass
  `--grounding-index <name>` and hand `grounding.graph_name`, endpoint and index to its producer.
  After `ready`, re-plan EKG and approve that exact plan. Never reuse an ungrounded name.

## Handoff

1. Run only the read-only checks in [Install and checks](install-and-checks.md) for the chosen route.
2. Show the install lines from that file only if something is missing; wait for the user.
3. Hand off in plain language to the first owning skill.
