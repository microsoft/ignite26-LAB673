---
name: grz-consume
description: 'Browse a published GRZ community sidecar read-only: status, communities by level, ranked members, and chunk evidence with citations (preview). WHEN: asking what topics a corpus covers or exploring GRZ communities. DO NOT USE FOR: building, publishing, or retiring a GRZ index.'
license: MIT
compatibility: Azure read access, Copilot CLI, grz-skills MCP, and a published GRZ descriptor or offline sidecar file.
metadata:
  author: Microsoft
  version: "0.1.0-snapshot.0e44f94"
---

# GRZ consume (preview)

Read-only only.

| Intent | Load |
|---|---|
| Check the environment, descriptor, sign-in, or reader access | [Health and access](references/health-and-access.md) |
| Answer what topics a corpus covers; list communities and members; fetch evidence | [Browse topics](references/browse-topics.md) |
| Rank members for a question or check a premise | [Rank and verify](references/rank-and-verify.md) |

## Shared rules

Use MCP tools first: `grz-skills-grz_doctor`, `grz-skills-grz_status`, `grz-skills-grz_list_communities`, `grz-skills-grz_get_community`, `grz-skills-grz_list_members`, and `grz-skills-grz_get_chunk`. Omit `descriptor_path` to browse the build this account published last; otherwise pass an absolute path. All tools are read-only. A 403 means the caller lacks Search Index Data Reader on that index; report the grant guidance instead of retrying.

Never build, publish, or modify indexes here. Cite a `chunk_id` and `source_id` for each claim. If community names are missing, say any label is your inference. Check a question's premise against the evidence first and say so when it is contradicted or unverified. Never print keys or tokens.
