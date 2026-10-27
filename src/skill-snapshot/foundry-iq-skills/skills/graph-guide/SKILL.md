---
name: graph-guide
description: 'Explain plain retrieval, knowledge graphs (ekg-skills), GraphRAG communities (grz-skills), candidate ontologies (ontology-skills), optional grounding (grounding-skills) and Kusto graph (azure-kusto-graph-skills), and how CLI, optional Apps and standalone presentation fit. WHEN: "do I need a graph", "how do the graph skills fit together", "when is an ontology needed". DO NOT USE FOR: picking a route for specific data (graph-choose), running the chain (graph-demo), writing queries or changing Azure.'
license: MIT
compatibility: Advisory only. Requires the user's question and any stated current plugin availability.
metadata:
  author: Microsoft
  version: "0.0.0-placeholder"
---

# Graph guide

Explain only. Say the technique with the domain alongside, for example "GraphRAG (grz-skills)". Pick one
retrieval kind and say why. Never run Azure commands, sign in or install anything.

| Need | Load |
|---|---|
| Techniques, ontology options, hand-offs, wrong premises | [Decision guide](references/decision-guide.md) |
| Historical measured numbers and what is not measured | [Measured results](references/measured-results.md) |
| Read-only checks, install and optional Apps | [Install and checks](references/install-and-checks.md) |

## Rules

- One or two passages answer it: `foundry-iq` skill, no graph.
- A chain across documents: knowledge graph (ekg-skills). Themes across the corpus: GraphRAG (grz-skills).
- Data already in Kusto or Azure Data Explorer: `azure-kusto-graph-skills`.
- Execution is skills, then domain CLI, then domain services. Apps are optional presentation, never required. Never invent a universal graph command.
- Unsure which route fits specific data: `graph-choose`. Whole chain on one dataset: `graph-demo`.
- Quote measured numbers; never extrapolate them to other corpora.
- If a CLI is missing, show the install lines and wait; never install it.
