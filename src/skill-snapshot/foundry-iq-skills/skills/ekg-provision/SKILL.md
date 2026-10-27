---
name: ekg-provision
description: 'Prepare Azure resources for an Enterprise Knowledge Graph. WHEN: setting up, connecting, or resizing EKG infrastructure with approved changes. DO NOT USE FOR: building graphs or answering graph questions.'
license: MIT
compatibility: Python 3.12, Azure sign-in (Entra), and ekg-provision for approved writes.
metadata:
  author: Microsoft
  version: "0.0.0-placeholder"
---

# EKG provision

First read [runtime setup](../graph-guide/references/install-and-checks.md#plugin-and-clis); use its launcher prefix.

Load one path only.

| Intent | Load |
|---|---|
| Check whether existing Search, Storage, and OpenAI resources are ready | [Connect existing resources](references/connect-existing-resources.md) |
| Create new public-test/public-data resources (default `westus3`) | [New public-test setup](references/new-public-test-setup.md) |
| Review model quota, TPM capacity, RBAC, the smoke test, or cleanup evidence | [Capacity, RBAC, smoke](references/capacity-rbac-smoke.md) |

## Shared rules

Run `ekg-provision doctor --json` first, and again after any blocked result; follow its one `next_step`. Name the tenant before any sign-in, and add `--json` to every command. Blocked results carry an `error_code` and one `next_step`.

Every write gate (`plan`, `connect` setup, `plan-capacity`, `plan-rbac`) returns an approval card starting `APPROVAL:`. Show it verbatim and wait for the exact reply `approved <plan-id>`. Then run the matching write (`ekg-provision apply`, `ekg-provision connect-apply`, `ekg-provision rbac-grant`, `ekg-provision capacity-update`) with `--plan-id <id> --confirm-writes`. A plain "yes" is not approval. Never retry or clean up on your own.

Default and private-network apply remain disabled; only bounded public-test or public-data apply and connect setup write. Never put secrets in plans or output. Do not build graphs, ingest documents or answer queries.
