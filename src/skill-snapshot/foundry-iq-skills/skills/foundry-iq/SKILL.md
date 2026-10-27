---
name: foundry-iq
description: 'WHEN: REST, "create a knowledge source", assistants/failures/quality/cost. DO NOT USE FOR: other Azure work or continuous evaluation.'
license: MIT
metadata:
  author: Microsoft
  version: "0.0.0-placeholder"
---

## Intent routing

Failures first; one route. Ask if unclear. Heroes cover cleanup.
Heroes: `hero-scenarios/<id>/<id>.md`.
Evaluation: read first; finish its gate, including baselines.
Diagnose before setup or quality; relevance needs proven freshness.

| Intent | Load |
|---|---|
| Denied access or connectivity | `diagnose-access-issues` |
| Missing files or stale answers | `diagnose-ingestion-issues` |
| Quality | `hill-climb-retrieval-quality` |
| Local files | `agentic-search-file-knowledge-source` |
| Cloud files | `agentic-search-blob-knowledge-source` |
| Document assistant | `knowledge-base-foundry-prompt-agent` |
| Keyword search | `simple-search` |
| Vector search | `integrated-vector-search` |
| SharePoint | `sharepoint-knowledge-source` |
| Multiple sources | `multi-source-knowledge-base` |
| Existing index | `search-index-knowledge-source` |
| OneLake files | `indexed-onelake-knowledge-source` |
| Private production | `network-isolated-production-workflow` |
| Autonomous | `instruction-to-production-agent` |
| Failure | `troubleshooting/`, then original operation |
| REST operation | `references/operation-catalog.yaml` -> leaf |
| Service setup | [service](references/service-provisioning.md) |
| Other KS -> KB | `operations/data-plane/knowledge-sources/create.md` |

## Shared rules

Read [HTTP](references/http-contract.md), [versions](references/api-version-policy.md), [RBAC](references/authentication-rbac.md), [safety](references/safety-and-idempotency.md); return [handoff](references/output-contract.md). Resolve/reuse `managementApiVersion`/`dataApiVersion` before requests.

Entra/least privilege/reuse; approve billable/permission/network/production/destructive/credential/data-movement. No data/secrets.
