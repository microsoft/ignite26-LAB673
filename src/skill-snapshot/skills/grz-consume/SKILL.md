---
name: grz-consume
description: 'Browse a published GRZ community sidecar read-only: status, communities by level, members, and chunk evidence with citations (preview). WHEN: asking what topics a corpus covers or exploring GRZ communities. DO NOT USE FOR: building, publishing, or retiring a GRZ index.'
license: MIT
compatibility: Azure read access, Copilot CLI, the grz-consume CLI, and a published GRZ descriptor with an Azure Search endpoint.
metadata:
  author: Microsoft
  version: "0.0.0-snapshot"
---

# GRZ consume (preview)

Read-only only.

| Intent | Load |
|---|---|
| Check the environment, descriptor, sign-in, or reader access | [Health and access](references/health-and-access.md) |
| Answer what topics a corpus covers; list communities and members; fetch evidence | [Browse topics](references/browse-topics.md) |
| Test a question's premise against the published build | [Rank and verify](references/rank-and-verify.md) |

## Shared rules

Use the `grz-consume` CLI with `--json` on every command and require `schema_version: "grz-consume-v1"`; read the domain result from `result`. Blocked JSON goes to stderr with `error_code` and one `next_step`. Omit `--descriptor` to browse the build this account published last; otherwise pass an absolute path. A 403 means the caller lacks Search Index Data Reader on that index; report the grant guidance instead of retrying.

Never build, publish, or modify indexes here. Cite a `chunk_id` and `source_id` for each claim. If community names are missing, say any label is your inference. Check a question's premise against the evidence first and say so when it is contradicted or unverified. Never print keys or tokens.
