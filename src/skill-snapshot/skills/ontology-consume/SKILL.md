---
name: ontology-consume
description: 'Browse ontology versions, evidence, and diffs read-only, and check OWL files against the flat-owl profile. WHEN: asking what an ontology contains, why a class exists, what changed, or if an .owl is valid. DO NOT USE FOR: proposing, approving, or exporting ontologies.'
license: MIT
compatibility: Copilot CLI, ontology-skills MCP, and a local ontology state directory or .owl file. No Azure sign-in.
metadata:
  author: Microsoft
  version: "0.1.0-snapshot.0e44f94"
---

# Ontology consume

Read-only only.

| Intent | Load |
|---|---|
| Check setup, list versions, find the current approved ontology, show classes or a diagram | [Browse ontology](references/browse-ontology.md) |
| Explain a class from its evidence, or diff two versions | [Evidence and diff](references/evidence-and-diff.md) |
| Validate an OWL file, or price a proposal without saving a plan | [Check and estimate](references/check-and-estimate.md) |

## Shared rules

Use MCP tools first: `ontology-skills-ontology_doctor`, `ontology-skills-ontology_status`, `ontology-skills-ontology_current`, `ontology-skills-ontology_show`, `ontology-skills-ontology_evidence`, `ontology-skills-ontology_diff`, `ontology-skills-ontology_check`, and `ontology-skills-ontology_plan_estimate`. They never change the state directory and make no network calls. Pass an absolute `state_dir` when it is not `.ontology-state` in the working folder; otherwise use the `ontology-consume` CLI with `--json`.

Never propose, refine, approve, or export here. Answer in plain words with class and property names, descriptions, and cited passages; quote excerpts as returned and name their source. Mention schema IDs and version numbers only when asked. On a blocked result, relay `error` and do exactly `next_step`. Never guess.
