---
name: ontology-consume
description: 'Browse ontology versions, evidence, and diffs read-only, and check OWL files against the flat-owl profile. WHEN: asking what an ontology contains, why a class exists, what changed, or if an .owl is valid. DO NOT USE FOR: proposing, approving, or exporting ontologies.'
license: MIT
compatibility: Copilot CLI, the ontology-consume CLI, and a local ontology state directory or .owl file. No Azure sign-in.
metadata:
  author: Microsoft
  version: "0.0.0-snapshot"
---

# Ontology consume

Read-only only.

| Intent | Load |
|---|---|
| Check setup, list versions, find the current approved ontology, show classes or a diagram | [Browse ontology](references/browse-ontology.md) |
| Explain a class from its evidence, or diff two versions | [Evidence and diff](references/evidence-and-diff.md) |
| Validate an OWL file, or price a proposal | [Check and estimate](references/check-and-estimate.md) |

## Shared rules

Use the `ontology-consume` CLI with `--json` for every read. It never changes the state directory and makes no network calls. Pass `--state-dir` when the state directory is not `.ontology-state` in the working folder. The optional Apps adapter only adds packaged ontology and evidence views; it does not replace the CLI.

Never propose, refine, approve, or export here. Answer in plain words with class and property names, descriptions, and cited passages; quote excerpts as returned and name their source. Mention schema IDs and version numbers only when asked. On a blocked result, relay `error` and do exactly `next_step`. Never guess.
