# Foundry Integration

Use when a Foundry agent cannot call a knowledge base or answers without grounding. Record the project, active agent version, connection/tool error, UTC time, and request ID; redact credentials and private content.
For Search calls, follow the [API version policy](../references/api-version-policy.md) with the original request version as input; do not silently change it. Apply the [HTTP contract](../references/http-contract.md).
Start read-only; require approval for connection, identity, network, agent, or billable changes. Resolve missing access through the [shared RBAC check](../references/authentication-rbac.md).

## Workflow

1. **Wrong connection or endpoint (400/404).** In the existing Foundry client/portal, inspect the project connection and active agent's MCP tool. Confirm the Search service URL and [knowledge-base name](../operations/data-plane/knowledge-bases/get.md).
   The tool's `server_url` and connection target must identify the same KB MCP endpoint and compatible Search API version, not an index or `/retrieve` URL. For managed-identity setup, check `RemoteTool`, `ProjectManagedIdentity`, and Search audience; hub-based projects are unsupported by this integration.
2. **Wrong principal (401/403).** The project's managed identity needs Search Index Data Reader on Search; a developer's successful local query does not prove project access.
   If creating the connection fails, check the caller's Foundry project permissions instead. For timeouts/private services, verify reachability from the agent's execution network using [network diagnosis](private-network-dns.md), not just the developer's machine.
3. **Tool not invoked.** Inspect the agent trace: `allowed_tools` must include `knowledge_base_retrieve`, and instructions should require the KB for grounding. Honor any pending tool approval; do not disable it to force a call.
   Try one approved known-answer request. If an MCP call occurs but retrieval fails, use [knowledge retrieval diagnosis](knowledge-retrieval.md); if no call occurs, return the connection/tool/instruction mismatch to the Foundry owner.

**Verify/stop:** Require a successful MCP call and a grounded answer with source references. Have the Foundry owner apply approved configuration corrections using the setup contract below; do not invent Foundry tool arguments or treat a direct Search query as end-to-end success.

**Sources:** [Connect Foundry agents to knowledge bases](https://learn.microsoft.com/azure/foundry/agents/how-to/foundry-iq-connect).
