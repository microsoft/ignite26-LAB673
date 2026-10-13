---
name: ekg-consume
description: 'Answer questions from a published Enterprise Knowledge Graph with citations. WHEN: published EKG retrieval or graph traversal questions. DO NOT USE FOR: provisioning, building, or mutating Azure resources.'
license: MIT
compatibility: Azure read access, Copilot CLI, ekg-skills MCP, and a published EKG descriptor outside the repo.
metadata:
  author: Microsoft
  version: "0.1.0-snapshot.0e44f94"
---

# EKG consume

Read-only only.

| Intent | Load |
|---|---|
| Check descriptor health, environment, or advertised capabilities | [Health and capabilities](references/health-and-capabilities.md) |
| Retrieve cited passages; choose lexical or hybrid search | [Document retrieval](references/document-retrieval.md) |
| Traverse relationships, test a premise, or explain graph limits | [Graph traversal](references/graph-traversal.md) |

## Shared rules

Use MCP tools first: `ekg-skills-ekg_doctor`, `ekg-skills-ekg_consume_capabilities`, `ekg-skills-ekg_consume_health`, `ekg-skills-ekg_consume_query`, `ekg-skills-ekg_consume_retrieve`, and `ekg-skills-ekg_consume_graph_query`. Omit `descriptor_path` only when the current published descriptor is intended; otherwise pass an absolute descriptor path. These tools are read-only. A 403 means the caller lacks Search reader access; report the grant guidance instead of retrying.

Never provision, upload, repair, or mutate indexes here. Do not fall back from disabled graph retrieval to document retrieval without saying so. Verify premises against evidence before repeating them. Cite the returned provenance and never expose secrets or private content beyond the requested evidence.
