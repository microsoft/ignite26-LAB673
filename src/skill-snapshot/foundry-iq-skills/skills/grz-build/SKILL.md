---
name: grz-build
description: 'Build, verify, publish, and retire a GRZ community sidecar index in Azure AI Search from chunk vectors (preview; public or synthetic data only). WHEN: planning, applying, verifying, publishing, reconciling, or retiring a GRZ build. DO NOT USE FOR: browsing communities or answering corpus questions.'
license: MIT
compatibility: Python 3.12, Azure sign-in (Entra), and grz-build for approved writes.
metadata:
  author: Microsoft
  version: "0.0.0-placeholder"
---

# GRZ build (preview)

First read [runtime setup](../graph-guide/references/install-and-checks.md#plugin-and-clis); use its launcher prefix.

Load one path only.

| Intent | Load |
|---|---|
| Check the machine, inspect a source index, plan, apply, or verify a build | [Plan and apply](references/plan-and-apply.md) |
| Publish a verified generation or manage reader access | [Publish and readers](references/publish-and-readers.md) |
| Recover a failed write or retire owned incomplete staging | [Reconcile and retire](references/reconcile-and-retire.md) |

## Shared rules

Run `grz-build doctor --json` first, and again after any blocked result. Add `--json` to every command and follow the returned `next_step`. Name the exact tenant, subscription, resource group, and Search service before any sign-in. Entra only; never accept or print keys or tokens.

Every write gate (`plan`, `verify`, `plan-retire`) returns an `approval_card`. Show its `text` verbatim and wait for the exact `reply` line (`approved <plan-id>`). A plain "yes" is not approval, and an approval covers only the card shown. Never retry an uncertain write; reconcile first.

GRZ writes only `grz-` indexes, never aliases or the source. Publish selects a local physical descriptor; other consumers need explicit rollout. Retain completed generations. Accept public or synthetic data only. This is not product `globalRetrieve` or a Knowledge Source binding.
