# Create a Foundry KB project connection

Read only when the [agent hero](../hero-scenarios/knowledge-base-foundry-prompt-agent/knowledge-base-foundry-prompt-agent.md)
cannot reuse a matching connection, or connection diagnosis needs its contract.
The hero owns corpus selection, approvals, agent preservation and verification.
This branch creates a project connection, not a KB, agent, identity or network.

## Inputs and approval

Confirm the modern Cognitive Services project ARM ID/endpoint, project managed
identity, exact KB MCP URL with inherited `dataApiVersion`, approved connection
name and sharing. Hub-based projects are unsupported. Missing identity or
caller Foundry Project Manager permissions blocks the write; use the
[RBAC contract](authentication-rbac.md) for separate grant/enablement authority.
Project identity needs Search Index Data Reader; Search's outbound identity and
the caller's token are distinct.

`connectionApiVersion = 2025-10-01-preview` is the documented ARM contract,
independent of Search `managementApiVersion` and the agent API `v1`.
Disclose preview use; verify overrides rather than replacing only the URL date.
Use an ARM-audience Entra token, never a Search token or keys.

Set `$url` to the resolved connection URI; on Windows PowerShell with `az.cmd`, replace `--url $url` with `--url ('"' + $url + '"')` per [Windows quoting](http-contract.md#windows-quoting).

GET this URI with `az rest --method get --url $url` before PUT:

```text
https://management.azure.com<project-resource-id>/connections/<connection-name>?api-version=<connectionApiVersion>
```

Reuse exact matching auth/category/target/audience/sharing. A 404 confirms absence;
401/403 is not absence. Never overwrite a connection with different settings.
Only create after the hero's approval covers the exact corpus and project-wide
sharing. The documented `isSharedToAll: true` is not an invisible default;
if sharing is unacceptable, stop for a supported narrower design.

## Create and read back

Save this substituted, credential-free JSON at the approved local path:

```json
{
  "name": "<connection-name>",
  "type": "Microsoft.MachineLearningServices/workspaces/connections",
  "properties": {
    "authType": "ProjectManagedIdentity",
    "category": "RemoteTool",
    "target": "<exact-kb-mcp-url>",
    "isSharedToAll": true,
    "audience": "https://search.azure.com/",
    "metadata": {"ApiType": "Azure"}
  }
}
```

Use `az rest --method put --url $url --body "@<approved-json-path>"`
with shared HTTP/request-ID handling. Recheck absence and coordinate name
ownership immediately before writing. The published recipe has no confirmed
atomic create-only/ETag guarantee; do not claim concurrency safety or blindly
retry a PUT that might overwrite another creator's connection.

Read back and compare the six properties above, name and resource ID without
printing credentials. A mismatch is incomplete. Record created/reused ownership
and request IDs, then return to agent binding; PUT success is not grounding.
After a lost response, GET/reconcile before retrying. Treat existing different
state as a conflict, not permission to overwrite it.

## Cleanup

Only after approved consumer detachment and verified owned inventory, DELETE
the same URI with `az rest --method delete --url $url`.
Check retained agent versions (including drafts) and other clients first.
Verify GET/404 and retained resources. Never delete reused connections, the
existing agent, sources or the project; follow
[scenario cleanup](safety-and-idempotency.md#scenario-cleanup).

**Source:** [Official Foundry IQ connection contract](https://learn.microsoft.com/azure/foundry/agents/how-to/foundry-iq-connect).
