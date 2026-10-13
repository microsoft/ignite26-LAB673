# Decision guide

## Quick starts

- "Do I need a graph for vendor impact questions?"
- "When should I use EKG instead of plain retrieval?"

## What ships today

Use the published plugin that matches the answer shape:

| Need | Route |
|---|---|
| One passage or a small set of passages with citations | `foundry-iq-skills` |
| A path across entities and relationships, with cited hops | `ekg-skills` |
| Graph queries over data already in Kusto or Azure Data Explorer | `azure-kusto-graph-skills` |
| Topic communities across a corpus | `grz-skills` |
| A proposed OWL ontology from corpus structure | `ontology-skills` |
| Domain grounding or entity vocabularies from CSV, JSONL or Wikidata | `grounding-skills` |

## Choose by answer shape

- **Plain retrieval:** the answer is stated directly in one document or a few nearby passages. Prefer `foundry-iq-skills`.
- **Knowledge graph:** no single passage states the answer, and the user needs a relationship path such as vendor to project to customer. Prefer `ekg-skills`.
- **Kusto graph:** the source of truth is already in Kusto or Azure Data Explorer. Prefer `azure-kusto-graph-skills`.
- **Corpus coverage:** the user wants themes, clusters, or a browsable topic map. Prefer `grz-skills`.
- **Domain grounding:** the user has an entity vocabulary or wants one from Wikidata to ground an EKG build. Prefer `grounding-skills`.

## Ontology guidance for EKG

A knowledge graph needs an ontology. Route as follows:

| Situation | Guidance |
|---|---|
| The user already has an OWL file | Use that file with `ekg-skills`. |
| The user has no OWL file but can start with general business types | Use the built-in Schema.org option in `ekg-skills`. |
| The user needs a domain-specific ontology and does not have one | Use `ontology-skills` to propose and export one, then hand the OWL file to `ekg-skills`. |

## Safe wording

Only `entity-skills` (automated entity linking and extraction) is planned. Do not present it as installable; say it is future work and keep the actionable route on an available plugin.
