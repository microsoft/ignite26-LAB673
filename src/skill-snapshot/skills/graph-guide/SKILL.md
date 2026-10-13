---
name: graph-guide
description: 'Explain whether to use foundry-iq-skills, ekg-skills, azure-kusto-graph-skills, or the grounding, grz and ontology companions, and what stays planned. WHEN: "do I need a graph", "which Azure retrieval route fits", "when is an ontology needed". DO NOT USE FOR: writing graph queries or changing Azure.'
license: MIT
compatibility: Advisory only. Requires the user's question and any stated current plugin availability.
metadata:
  author: Microsoft
  version: "0.1.0-snapshot.0e44f94"
---

# Graph guide

Explain only. Ask about data shape and answer shape before routing. Load one
reference at a time.

This graph-only snapshot does not bundle `foundry-iq-skills` or
`azure-kusto-graph-skills`; references to them describe external routes.

| Need | Load |
|---|---|
| Plain-language choice between retrieval, knowledge graph, and Kusto graph | [Decision guide](references/decision-guide.md) |
| Published plugin install or readiness checks | [Install and checks](references/install-and-checks.md) |
| Companion plugins and the planned entity stage | [Decision guide](references/decision-guide.md) |

## Shared rules

- Available routes: `foundry-iq-skills`, `ekg-skills`, `grounding-skills`, `grz-skills`, `ontology-skills`, and `azure-kusto-graph-skills`.
- Planned only: `entity-skills` (automated entity linking and extraction). Describe it as future work; give no install or command lines.
- If one or a few passages answer the question, route to `foundry-iq-skills`.
- If the answer needs multi-hop entity links over Azure AI Search, route to `ekg-skills`.
- If the data already lives in Kusto or Azure Data Explorer, route to `azure-kusto-graph-skills`.
- Never install anything, sign in, or mutate Azure from this skill. Run only read-only checks, then hand off after the user approves the route.
