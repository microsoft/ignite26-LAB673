# Bind a classic Search index to a Foundry agent

Read only for a **classic Search** architecture and an existing Foundry
prompt agent. Use the native Azure AI Search tool, never the
[KB MCP helper](../hero-scenarios/knowledge-base-foundry-prompt-agent/knowledge-base-foundry-prompt-agent.md).
No new agent, toolbox, KS or KB is needed. Unsupported harness/definition,
identity propagation or citation-field compatibility blocks before provisioning.

## Inputs and RBAC

Discover project endpoint/resource ID, existing agent and active version,
connection/index, fields, query mode and runtime audience. Require searchable
text and retrievable original-document URLs; vector/semantic modes require
their own proven index/model configuration. Never silently rebuild for them.
Carry the [selected retrieval mode](context-resolution.md#retrieval-setup-decisions)
into `query_type`.
Verify the Foundry account's actual system-assigned identity has documented
Search Index Data Contributor and Search Service Contributor, reusing
equivalent grants under [RBAC](authentication-rbac.md). Missing access needs
exact-scope approval/owner authority, never keys. Same tenant; private Search
requires standard agent deployment with VNet injection and managed identity.
The connection authenticates the tool, not each end user. An unverified
per-user ACL flow blocks protected attachment, not an unfiltered service identity.

## Preflight

Resolve Search versions under [policy](api-version-policy.md). Independently
resolve the connection ARM API (documented `2025-06-01`) and agent API `v1`;
never reuse a Search date for either. Verify SDK 2.4+ native tool, draft and
endpoint-selector contracts at the selected version. Disclose preview use.
GET agent details (`project.agents.get`) and the selected full version
(`get_version`); retain instructions, model, tools/resources, metadata,
description/blueprint and endpoint protocols/auth/card/selector privately.
Record the original stable-runtime canary before mutation. Consolidate
connection, grants, draft/model costs and eventual production cutover approval.

## Connect: reuse first

List/get project connections, then `project.connections.get(name)`.
Reuse only matching Search target, `CognitiveSearch` category and `AAD`
authentication; never repoint an existing connection. If missing and approved:

```http
PUT https://management.azure.com<project-resource-id>/connections/<connection-name>?api-version=<connectionApiVersion>
Content-Type: application/json

{"properties":{"category":"CognitiveSearch","target":"<search-endpoint>","authType":"AAD"}}
```

Use verified Foundry connection-write authority and an ARM-audience Entra
token; read back target/category/auth and resolve its actual ID through the SDK.
Guard create races with supported conditional semantics or re-read/stop;
never overwrite an incompatible concurrently created connection. Readback
failure is a blocker, not permission to downgrade to `ApiKey`.

## Preserve and create a candidate

With `AIProjectClient` authenticated by `DefaultAzureCredential`, preserve the
full existing prompt definition, changing only the approved tool binding:

```python
from copy import deepcopy
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from azure.ai.projects.models import (
    PromptAgentDefinition, AzureAISearchTool, AzureAISearchToolResource,
    AISearchIndexResource,
)

project = AIProjectClient(endpoint=project_endpoint,
                         credential=DefaultAzureCredential(),
                         api_version=agent_api_version, allow_preview=True)
baseline = project.agents.get_version(agent_name, baseline_version)
if not isinstance(baseline.definition, PromptAgentDefinition):
    raise ValueError("unsupported-agent-definition")
definition = deepcopy(baseline.definition)
tool = AzureAISearchTool(azure_ai_search=AzureAISearchToolResource(indexes=[
    AISearchIndexResource(project_connection_id=connection.id,
                          index_name=index_name, query_type=query_type, top_k=5)
]))
definition.tools = [*deepcopy(baseline.definition.tools or []), tool]
draft = project.agents.create_version(
    agent_name, definition=definition, metadata=deepcopy(baseline.metadata),
    description=baseline.description,
    blueprint_reference=deepcopy(baseline.blueprint_reference), draft=True,
)
```

Resolve all variables from discovery. An already matching native tool is
reuse, not duplication; an incompatible binding needs an explicit diff.
Read back the entire candidate and compare every preserved field, not only
the Search tool. `draft=True` records a candidate excluded from default latest
resolution by the supported SDK contract; verify that contract, never infer
draft safety from a name. If unavailable, pin the approved baseline first or
block. Reconcile uncertain creates by listing versions, never blind retries.

Invoke the candidate through `project.get_openai_client().responses.create`:

```python
response = client.responses.create(
    input=known_fact_question, max_output_tokens=512,
    extra_body={"agent_reference": {
        "type": "agent_reference", "name": agent_name, "version": draft.version
    }},
)
```

Require the known fact and `url_citation` to its actual document field, plus
no-answer and permitted/denied-user checks where applicable. Run from the
intended network/runtime; no citation or unavailable identity flow is unverified.

## Production and cleanup

A verified draft is not production. Only if cutover is requested, use
[preserved-agent cutover](foundry-agent-cutover.md); it applies to either
classic or KB bindings without changing the retrieval architecture.
Delete only owned unused versions via `project.agents.delete_version`, then
owned unreferenced connections through their management DELETE. Never delete
the existing agent, baseline or shared tools/connections. Return version IDs,
preserved fields, endpoint, ownership, costs and blockers under
[output](output-contract.md); never log raw tokens/definitions.

**Sources:** [Connect an Azure AI Search index to Foundry agents](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/ai-search),
[Configure and share your Foundry agent](https://learn.microsoft.com/azure/foundry/agents/how-to/configure-agent),
[SDK 2.4 contracts](https://github.com/Azure/azure-sdk-for-python/tree/azure-ai-projects_2.4.0/sdk/ai/azure-ai-projects).
