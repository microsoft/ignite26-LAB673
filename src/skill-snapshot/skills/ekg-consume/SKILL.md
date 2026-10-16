---
name: ekg-consume
description: 'Answer questions from a published Enterprise Knowledge Graph with citations. WHEN: published EKG retrieval or graph traversal questions. DO NOT USE FOR: provisioning, building, or mutating Azure resources.'
license: MIT
compatibility: Azure read access (Entra), Copilot CLI, the ekg-consume CLI, and a published EKG descriptor outside the repo.
metadata:
  author: Microsoft
  version: "0.0.0-snapshot"
---

# EKG consume

Read-only only.

| Intent | Load |
|---|---|
| Install the CLI, check the descriptor, environment, or advertised capabilities | [Health and capabilities](references/health-and-capabilities.md) |
| Retrieve cited passages; choose lexical or hybrid search | [Document retrieval](references/document-retrieval.md) |
| Traverse relationships, test a premise, or explain graph limits | [Graph traversal](references/graph-traversal.md) |

## Shared rules

Use the `ekg-consume` CLI with `--json`. Run `ekg-consume doctor` before a live query and follow its one `next_step`. `--descriptor` defaults to `EKG_DESCRIPTOR`, then the current published descriptor; pass an absolute path when another is intended. A 403 means the caller lacks Search reader access; report the grant guidance instead of retrying.

Never provision, upload, repair, or mutate indexes here. Do not fall back from disabled graph retrieval to document retrieval without saying so. Answer only from returned evidence, check the question's premise first, and cite the returned provenance. Never expose secrets or private content beyond the requested evidence.
