---
name: ekg-build
description: 'Build, refresh, and publish an Enterprise Knowledge Graph. WHEN: planning, applying, updating, retiring, or checking one EKG build. DO NOT USE FOR: provisioning Azure infrastructure or answering graph questions.'
license: MIT
compatibility: Azure access, Copilot CLI, ekg-skills MCP, local BuildSpec JSON, and the ekg-build CLI for approved writes.
metadata:
  author: Microsoft
  version: "0.1.0-snapshot.0e44f94"
---

# EKG build

Load one path only.

| Intent | Load |
|---|---|
| Preflight or plan a BuildSpec; choose `none`, `schema_org`, or `owl_file` | [Plan and publish](references/plan-and-publish.md) |
| Run an OWL trial, update a published generation, or retire old generations | [Trial, update, retire](references/trial-update-retire.md) |
| Check tools, doctor, journal status, telemetry, progress, or protected generations | [Status and telemetry](references/status-and-telemetry.md) |

## Shared rules

Use read-only MCP first: `ekg-skills-ekg_doctor`, `ekg-skills-ekg_ks_capabilities`, `ekg-skills-ekg_source_inspect`, `ekg-skills-ekg_build_plan`, `ekg-skills-ekg_build_status`, `ekg-skills-ekg_build_telemetry`, and `ekg-skills-ekg_build_generations`. `spec_path`, descriptor paths, journal paths, and `working_directory` must be absolute. `ekg_build_plan` never writes; `ekg_build_status` reports only the matching local journal; `ekg_build_generations` never deletes.

Any write stays on the CLI surface only. Show the exact approval card, then wait for `approved <plan-id>` before `ekg-build apply`, `ekg-build update`, or `ekg-build retire`. Publish only after verified state. Never invent source inventory, preview entitlement, reader grants, or live serving health. Keep secrets, tenant details, and document content out of output.
