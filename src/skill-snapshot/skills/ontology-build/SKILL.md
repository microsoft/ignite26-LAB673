---
name: ontology-build
description: 'Propose, refine, approve, and export an ontology from a published GRZ community generation, as OWL or opt-in inline-compatible JSON-LD. WHEN: building or revising an ontology for a corpus, or exporting an approved ontology. DO NOT USE FOR: building GRZ generations, read-only browsing, or role assignment.'
license: MIT
compatibility: Azure access, an Azure OpenAI deployment, Copilot CLI, and the ontology-build CLI for approved model calls.
metadata:
  author: Microsoft
  version: "0.0.0-snapshot"
---

# Ontology build

Load one path only.

| Intent | Load |
|---|---|
| Set up, connect, inspect the generation, or plan and run a proposal | [Connect, plan, propose](references/connect-plan-propose.md) |
| Refine a draft, run one critique, or apply a critique | [Refine, critique, revise](references/refine-critique-revise.md) |
| Review, approve, import, export, or hand off the current ontology | [Review, approve, export](references/review-approve-export.md) |

## Shared rules

Run `ontology-build doctor --json` first. Add `--json` to every verb; read `next_step` and `error_code`. Input is a read-only GRZ sidecar index in Azure AI Search plus an Azure OpenAI deployment.

Show each `approval` card exactly, then wait for `approved <plan-id>` before `propose`, `refine`, or `critique`, and for `approved <schema-id>` before `approve`. Pass the exact IDs from that card. A bare yes is not approval. Never use `--force` on export unless the user asked to overwrite that file. Never assign roles; show the printed command for an owner. Do not self-install tooling. Name the tenant before any sign-in; use Entra only. Keep secrets, tenant details, and passage text out of output.
