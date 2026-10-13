---
name: graph-demo
description: 'Coordinate an approval-first demo route across the graph companion plugins (grounding, grz, ontology, ekg). WHEN: "demo the graph workflow", "walk me through the graph chain", "show the safe order of graph steps". DO NOT USE FOR: making Azure changes directly or skipping owning-skill approvals.'
license: MIT
compatibility: Advisory only. Requires a public or synthetic corpus and the user's approval before each leaf-skill change.
metadata:
  author: Microsoft
  version: "0.1.0-snapshot.0e44f94"
---

# Graph demo

Coordinate the sequence, check handoff readiness, and let each owning skill do
its own work.

| Need | Load |
|---|---|
| Step order, artifact checks, and fallback path | [Demo flow](references/demo-flow.md) |
| Published plugin install or readiness checks | [Install and checks](references/install-and-checks.md) |

## Shared rules

- This skill never performs Azure writes, never passes approval flags, and never installs anything.
- Available stages: `grounding-skills`, `grz-skills`, `ontology-skills` and `ekg-skills`, each run by its own skill. Planned only: `entity-skills`; keep it descriptive and give no install or command lines.
- Before every handoff, verify readiness with read-only checks, name the expected approval, and wait for explicit user approval.
- If the user only needs explanation, route to `graph-guide`. If the user only needs route selection, route to `graph-choose`.
