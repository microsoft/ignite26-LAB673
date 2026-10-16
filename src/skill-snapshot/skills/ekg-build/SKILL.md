---
name: ekg-build
description: 'Build, refresh, and publish an Enterprise Knowledge Graph. WHEN: planning, applying, updating, retiring, or checking one EKG build. DO NOT USE FOR: provisioning Azure infrastructure or answering graph questions.'
license: MIT
compatibility: Azure sign-in (Entra), Copilot CLI, and the ekg-build CLI for every step and approved write.
metadata:
  author: Microsoft
  version: "0.0.0-snapshot"
---

# EKG build

Load one path only.

| Intent | Load |
|---|---|
| Install, doctor, inventory, plan, apply, reconcile, or publish a build; choose `none`, `schema_org`, or `owl_file` | [Plan and publish](references/plan-and-publish.md) |
| Run an OWL trial, update a published generation, or retire old generations | [Trial, update, retire](references/trial-update-retire.md) |
| Check status, progress, telemetry, attribution, or protected generations | [Status and telemetry](references/status-and-telemetry.md) |

## Shared rules

Run `ekg-build doctor --json` first, and again after any blocked result; follow its one `next_step`. Name the tenant before any sign-in. Add `--json` to every command. Use absolute paths.

Every write gate (`plan`, `plan-update`, `plan-retire`) returns an approval card starting `APPROVAL:`. Show it verbatim and wait for the exact reply `approved <plan-id>`; a plain "yes" is not approval, and approval covers only the card shown. Only then run `ekg-build apply`, `update`, or `retire` with `--plan-id <id> --confirm-writes`. Never retry an uncertain write; reconcile first. Publish only a verified generation.

Never invent source inventory, reader grants, or live serving health. A verified journal is history, not proof of serving. Keep secrets, tenant details, and document text out of output.
