---
name: grounding-provision
description: 'Connect to or create the Azure AI Search service that hosts a grounding index. WHEN: choosing a Search service, checking its roles or preview API readiness, or creating one for grounding. DO NOT USE FOR: loading edges, checking an index, or deleting resources.'
license: MIT
compatibility: Azure sign-in (Entra), Copilot CLI, and the grounding-provision CLI for approved writes.
metadata:
  author: Microsoft
  version: "0.0.0-snapshot"
---

# Grounding provision

Load one path only.

| Intent | Load |
|---|---|
| Pick an existing Search service, or check roles and preview API readiness | [Connect and doctor](references/connect-and-doctor.md) |
| Create a resource group and Search service for grounding | [Create a service](references/create-service.md) |

## Shared rules

Run read-only `grounding-provision doctor` first. State the tenant and subscription before any Azure call; the CLI prints both to stderr, and `--tenant` aborts on mismatch. Entra auth only: never request, pass, or store keys.

Writes stay on the CLI. `grounding-provision create` is a dry run until the user replies `approved <plan_id>`; only then re-run it with `--plan-id`. Never delete anything. Report role gaps and who must grant them; do not work around them. When the service is ready, hand off to `grounding-build` with the saved endpoint.
