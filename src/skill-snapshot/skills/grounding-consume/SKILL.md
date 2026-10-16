---
name: grounding-consume
description: 'Check, inspect, and sample an existing grounding index in Azure AI Search, read-only. WHEN: validating an index, listing its predicates or graph names, sampling edges, or testing readiness for a graph-extraction build. DO NOT USE FOR: loading or fixing an index, or creating a service.'
license: MIT
compatibility: Azure sign-in (Entra), Copilot CLI, and the read-only grounding-consume CLI.
metadata:
  author: Microsoft
  version: "0.0.0-snapshot"
---

# Grounding consume

Load one path only.

| Intent | Load |
|---|---|
| Validate the index, inspect its contents, or sample edges | [Check, inspect, sample](references/check-inspect-sample.md) |
| Decide whether a graph-extraction build can resolve names against it | [Readiness](references/readiness.md) |
| Understand the required edgeList profile and field roles | [Index schema](references/index-schema.md) |

## Shared rules

Everything is read-only; never write or delete. Use the `grounding-consume` commands. State tenant and subscription first (the CLI prints them to stderr). Report `problems` and `next_step` verbatim; for fixes hand off to `grounding-build`. Do not present edge contents as verified facts: Wikidata edges are unreviewed, and own-data edges keep the owner's licence. Referencing the index from another system is outside this skill; give the index name and endpoint.
