---
name: grounding-build
description: 'Build or fix a grounding index in Azure AI Search from your own edges, an entity list, or a bounded Wikidata seed. WHEN: planning, applying, resuming, or aligning a grounding index. DO NOT USE FOR: creating the Search service, checking an index, or deleting anything.'
license: MIT
compatibility: Azure sign-in (Entra), Copilot CLI, grounding-skills MCP, local CSV/JSONL/Parquet files, and the grounding-build CLI for approved writes.
metadata:
  author: Microsoft
  version: "0.1.0-snapshot.0e44f94"
---

# Grounding build

Load one path only.

| Intent | Load |
|---|---|
| Load own edges (CSV, JSONL, Parquet) or an entity list; make names resolve | [Own data](references/own-data.md) |
| Bootstrap from a bounded Wikidata seed; licensing | [Wikidata](references/wikidata.md) |
| Fix the graph name of an existing index, or resume an interrupted load | [Align and resume](references/align-and-resume.md) |

## Shared rules

Get the graph name from the plan of the graph-extraction build that will use the index; never guess it. Use read-only `grounding-skills-grounding_build_plan` first; it never persists. State tenant and subscription before any Azure call.

Writes stay on the CLI. `grounding-build plan` is a dry run; show the plan card and wait for the user's approval, then run `grounding-build apply --plan-id <id>` with the exact approved ID. Index names start with `grounding-`. Never delete or overwrite an index this plan did not create. Edge caps: 200,000 own data, 50,000 Wikidata. Verify with `grounding-consume` before handing back.
