---
name: graph-choose
description: 'Triage "I have X, I want to answer Y" to one graph or retrieval route (foundry-iq-skills, ekg-skills, grz-skills, ontology-skills, grounding-skills, azure-kusto-graph-skills) and name the first handoff. WHEN: "which graph skill should I use", "I have documents and need multi-hop answers", "which ontology option", "should this stay in Kusto". DO NOT USE FOR: running Azure commands, installs, writing graph queries or explaining the techniques (graph-guide).'
license: MIT
compatibility: Advisory only. Requires the user's current data shape and desired answer shape.
metadata:
  author: Microsoft
  version: "0.0.0-placeholder"
---

# Graph choose

Ask only what is missing, pick one row, say why in one sentence, then route.

| Need | Load |
|---|---|
| Route table, ontology option and rules of thumb | [Route table](references/route-table.md) |
| Read-only checks, install and optional Apps | [Install and checks](references/install-and-checks.md) |

## Two questions

- What do you have: documents, an OWL file, a Search index with chunk vectors, a published GRZ generation, or Kusto data?
- What answer do you need: one passage, a multi-hop path, or corpus-wide themes?

## Rules

- Take a position; do not list every option.
- Choose the CLI route first. Add optional Apps only when presentation is requested in a compatible host.
- Never run installs, sign-ins or Azure commands. Run only read-only checks for the chosen route.
- Name the tenant before any sign-in. Keep plan IDs and journal paths out unless asked.
- After the user approves the route, hand off to its owning skill. Route agreement is not write approval: the leaf shows the exact card and waits for `approved <plan-id>`.
