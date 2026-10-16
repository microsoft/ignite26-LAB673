---
name: graph-demo
description: 'Conduct the end-to-end graph chain on one public dataset: EKG indexes documents, GRZ builds communities, ontology proposes an OWL file, a 50-document trial gates the full EKG build, then multi-hop questions. WHEN: "demo the graph workflow", "walk me through the graph chain", "run EKG, GRZ and ontology together". DO NOT USE FOR: Azure changes, passing approval flags, skipping leaf approvals, or route selection (graph-choose).'
license: MIT
compatibility: Advisory only. Requires a public or synthetic corpus and the user's approval before each leaf-skill change.
metadata:
  author: Microsoft
  version: "0.0.0-snapshot"
---

# Graph demo

Conductor only: say what is next, check the hand-off artifact exists, hand off to the leaf skill.
Never run Azure writes, pass approval flags or install anything.

| Need | Load |
|---|---|
| Each hand-off, GRZ mapping, trial and full build, approval stops | [Hand-offs](references/handoffs.md) |
| Hours-long build and other caveats to say first | [Open items](references/open-items.md) |
| Read-only checks, install and Apps | [Install and checks](references/install-and-checks.md) |

## Chain

1. `ekg-provision`: Azure resources. 2. `ekg-build` with `schema_org`: the Search index.
3. `grz-build`: communities. 4. `ontology-build`: approved `.owl`.
5. `ekg-build` 50-document trial: go or no-go (no-go returns to step 4).
6. `ekg-build` full `owl_file` build. 7. `ekg-consume`: seven agreed questions on both graphs.

## Rules

- Public data only: GRZ and ontology are previews. The user, not you, confirms the index is public.
- Confirm each artifact; wait for the user's exact approval card/reply, never generic yes.
- Pass the exported `.owl` path explicitly to EKG.
- Relay a blocked result plainly with its one next step; never retry around a gate.
- Name the tenant before any sign-in. Apps and graph-presentation are optional.
- Explanation only: `graph-guide`. Route selection only: `graph-choose`.
