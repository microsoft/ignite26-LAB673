---
name: ekg-provision
description: 'Prepare Azure resources for an Enterprise Knowledge Graph. WHEN: setting up, connecting, or resizing EKG infrastructure with approved changes. DO NOT USE FOR: building graphs or answering graph questions.'
license: MIT
compatibility: Azure access, Copilot CLI, ekg-skills MCP for read-only discovery, and the ekg-provision CLI for approved writes.
metadata:
  author: Microsoft
  version: "0.1.0-snapshot.0e44f94"
---

# EKG provision

Choose the smallest setup path.

| Intent | Load |
|---|---|
| Discover whether existing Search, Storage, OpenAI, deployments, and roles are ready | [Connect existing resources](references/connect-existing-resources.md) |
| Plan a new isolated public-test setup | [New public-test setup](references/new-public-test-setup.md) |
| Check quota, resize TPM, plan RBAC, smoke, or cleanup evidence | [Capacity, RBAC, smoke](references/capacity-rbac-smoke.md) |

## Shared rules

Start read-only with `ekg-skills-ekg_doctor` and, for existing resources, `ekg-skills-ekg_provision_connect`. All writes stay on the CLI surface only. Show the exact approval card, then wait for `approved <plan-id>` before `ekg-provision apply`, `ekg-provision connect-apply`, `ekg-provision rbac-grant`, or `ekg-provision capacity-update`. Default and private-network apply remain disabled; only the explicit public-test path can apply.

Never create or widen access implicitly. Confirm tenant and subscription before auth, keep secrets out of output, and treat `unverified` role checks as uncertainty rather than proof that access is missing.
