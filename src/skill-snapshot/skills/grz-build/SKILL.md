---
name: grz-build
description: 'Build, verify, publish, and retire a GRZ community sidecar index in Azure AI Search from chunk vectors (preview; public or synthetic data only). WHEN: planning, applying, verifying, publishing, reconciling, or retiring a GRZ build. DO NOT USE FOR: browsing communities or answering corpus questions.'
license: MIT
compatibility: Azure sign-in, Copilot CLI, grz-skills MCP for doctor, and the grz-build CLI for every build step and approved write.
metadata:
  author: Microsoft
  version: "0.1.0-snapshot.0e44f94"
---

# GRZ build (preview)

Load one path only.

| Intent | Load |
|---|---|
| Check the machine, inspect a source index, plan, apply, or verify a build | [Plan and apply](references/plan-and-apply.md) |
| Publish a verified generation or manage reader access | [Publish and readers](references/publish-and-readers.md) |
| Recover from a failed write, list generations, or retire a superseded one | [Reconcile and retire](references/reconcile-and-retire.md) |

## Shared rules

Run `grz-skills-grz_doctor` or `grz-build doctor --json` first, and again after any blocked result. Add `--json` to every CLI command and follow the returned `next_step`. Name the exact tenant, subscription, resource group, and Search service before any sign-in. Entra only; never accept or print keys or tokens.

Every write gate (`plan`, `verify`, `plan-retire`) returns an `approval_card`. Show its `text` verbatim and wait for the exact `reply` line (`approved <plan-id>`). A plain "yes" is not approval, and an approval covers only the card shown. Never retry an uncertain write; reconcile first.

GRZ writes only `grz-` indexes and aliases and never changes the source index. Accept public or synthetic data only. The result is a candidate sidecar, not product `globalRetrieve` or a Knowledge Source binding.
