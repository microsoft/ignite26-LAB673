---
name: foundry-iq
description: 'Foundry IQ/Search. WHEN: REST, services, "create a knowledge source", setup, failures, incomplete answers, irrelevant passages, citations, retrieval/extraction/cost, reduce Knowledge Base or Search cost, debug Search. DO NOT USE FOR: unrelated Azure work or evaluation.'
license: MIT
compatibility: Azure/Entra; CLI/REST/SDK.
metadata:
  author: Microsoft
  version: "1.0.0-snapshot.0e44f94"
---

# Foundry IQ

## Intent routing

Failures first; load only selected guides. Ask if unclear. Hero rows cover cleanup.

| Intent | Load |
|---|---|
| Set up simple search | [Simple](hero-scenarios/simple-search/simple-search.md) |
| Set up Blob knowledge source | [Blob](hero-scenarios/agentic-search-blob-knowledge-source/agentic-search-blob-knowledge-source.md) |
| Set up vector search | [Vector](hero-scenarios/integrated-vector-search/integrated-vector-search.md) |

Other operations/troubleshooting: [other routes](references/intent-routing.md); [service](references/service-provisioning.md); [types](operations/data-plane/knowledge-sources/create.md).

## Shared rules

Read [HTTP/user-agent](references/http-contract.md), [API versions](references/api-version-policy.md), [RBAC](references/authentication-rbac.md), [safety](references/safety-and-idempotency.md), [output](references/output-contract.md). Before any API request, reuse or resolve `managementApiVersion`/`dataApiVersion` for every route.

Prefer Entra ID, least privilege and reuse; verify outcomes. Require approval before billable, permission, network, production, destructive, credential or data-movement changes. Never expose secrets/private content.
