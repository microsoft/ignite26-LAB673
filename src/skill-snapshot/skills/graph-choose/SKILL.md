---
name: graph-choose
description: 'Choose the right published graph or retrieval plugin for a question and its data shape, then state the first safe handoff. WHEN: "which graph plugin should I use", "I have documents and need multi-hop answers", "should this stay in Kusto". DO NOT USE FOR: writing graph queries or performing Azure changes.'
license: MIT
compatibility: Advisory only. Requires the user's current data shape and desired answer shape.
metadata:
  author: Microsoft
  version: "0.1.0-snapshot.0e44f94"
---

# Graph choose

Ask only what is missing, decide once, then route. Load one reference at a time.

| Need | Load |
|---|---|
| Route table, ontology choice, and the planned entity stage | [Route table](references/route-table.md) |
| Published plugin install or readiness checks | [Install and checks](references/install-and-checks.md) |

## Questions to settle

- What do you have: documents, an OWL file, a Search index with chunk vectors, or data in Kusto or Azure Data Explorer?
- What answer do you need: one passage, a multi-hop entity path, or corpus-wide themes?

## Shared rules

- Pick one route and explain why in one sentence.
- Available routes: `foundry-iq-skills`, `ekg-skills`, `grounding-skills`, `grz-skills`, `ontology-skills`, and `azure-kusto-graph-skills`.
- Planned only: `entity-skills` (automated entity linking and extraction). Mention it as future work; give no install or command lines.
- Never run installs, sign-ins, or Azure changes from this skill.
- After the user approves the route, hand off to the first owning skill or published plugin.
