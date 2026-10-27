---
name: graph-demo
description: 'Conduct the end-to-end graph chain on one public dataset: EKG indexes documents, GRZ builds communities, ontology proposes an OWL file, a 50-document trial gates the full EKG build, then multi-hop questions. WHEN: "demo the graph workflow", "walk me through the graph chain", "run EKG, GRZ and ontology together". DO NOT USE FOR: Azure changes, passing approval flags, skipping leaf approvals, or route selection (graph-choose).'
license: MIT
compatibility: Advisory only. Requires a public or synthetic corpus and the user's approval before each leaf-skill change.
metadata:
  author: Microsoft
  version: "0.0.0-placeholder"
---

# Graph demo

Conductor: preflight before writes, check hand-offs, then delegate.
Never run Azure writes, pass approval flags or install anything.

| Need | Load |
|---|---|
| Mapping, trial, approvals | [Hand-offs](references/handoffs.md) |
| Caveats to say first | [Open items](references/open-items.md) |
| Preflight | [Checks](references/install-and-checks.md) |

## Chain

0. Preflight runtimes/native; stop on local blockers. User accepts source-unknown before EKG;
   inspect actual schema as soon as available.
1. `ekg-provision`: Azure resources. 2. `ekg-build` with `schema_org`: the Search index.
3. `grz-build`: communities. 4. `ontology-build`: approved `.owl`.
5. `ekg-build` 50-document trial: go or no-go (no-go returns to step 4).
6. `ekg-build` full `owl_file` build. 7. `ekg-consume`: seven agreed questions on both graphs.

## Rules

- User confirms all data public; GRZ/ontology are previews.
- Confirm artifacts; wait for the user's exact approval card/reply, never generic yes.
- Pass the exported `.owl` path explicitly to EKG.
- Report blockers and next steps; never bypass a gate.
- Name the tenant before any sign-in. Apps and graph-presentation are optional.
- Explanation only: `graph-guide`. Route selection only: `graph-choose`.
