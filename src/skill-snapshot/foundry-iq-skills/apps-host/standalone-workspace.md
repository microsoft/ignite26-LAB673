# Workspace and query modes

Wait for `Graph workspace ready: http://127.0.0.1:<port>` and open that exact
address, not a machine name or `localhost`. Startup initializes the real servers
and discovers their presentation resources and App-only reads before reporting
ready. This is metadata readiness, not an Azure read, model call or guarantee
that the configured corpus is available. `/health` reports current MCP connection
availability, not upstream Search health.

The **Connected Sources** header pill counts connected sources. On page load, configured but
disconnected servers reconnect automatically without submitting a graph query.
Opening **Connected Sources** checks current connection health and shows
an explicit **Connected** or **Disconnected** control per source. **Connected**
opens a compact **Reconnect server** menu; **Disconnected · Connect** connects
directly. A query
automatically reconnects a disconnected source; if it discovers a stale
connection, it reconnects and retries once. Other query failures remain visible
without automatic replay.
Source cards appear first; **Technical details** keeps operator metadata and
selected-evidence diagnostics out of the everyday connection flow.

The browser is one **Knowledge workspace**, not an App launcher or a catalog of
MCP tools. Its keyboard-accessible **Knowledge graph**, **Communities** and
**Ontology** tabs are three task-focused views. Each retains its inputs, results
and selected context when another tab is active. First activation of Communities
or Ontology loads its default presentation once; later switches reuse that result.
Knowledge graph never submits an initial query on its own.
**Why Graph** never queries on activation, reopening or reconnect. Starters fill
the question; only **Ask** submits. Comparison and **Synthesize (KB)** require
a nonempty KB endpoint and explicit document, graph and agentic retrieval in
the selected descriptor, not just a tool enum. Missing/invalid local metadata
disables comparison with a reason, without disabling ordinary graph queries.
The host checks metadata at connect/reconnect and before KB dispatch, without
Azure probes. Reconnect clears comparison results and discovered starters.
Results are not cached; descriptor changes require reconnect and explicit submit.
Configurations containing only Communities or Ontology start on their first
available tab. Cross-tab exploration is offered only when a discovered
`ekg_present` target exists. The host conveys that app-owned availability flag
through `hostContext.knowledgeWorkspace.knowledgeGraph`, with `queryModes`
controlling the returned-statement editor action; neither is an MCP protocol
capability. Unavailable-target requests fail visibly without switching
away from the current view.

In **Knowledge graph**, fill **Question or entity** and choose **Explore**.
The required query is not replaced by a demo/default query; blank and whitespace
inputs are rejected before a request is sent. **Query options** exposes typed
numeric bounds and enum choices from the real discovered schema. Unchanged
optional fields preserve server defaults. Server `InvalidParams` errors become
actionable, sanitized input errors without exposing raw validation details or
retiring a healthy connection. Sources advertising `query_mode` expose
**Traverse / Ask (NL→GQL) / GQL**. Older sources expose Traverse only.
Raw GQL accepts multiline statements; switching modes does not execute a query.
The server owns translation and execution. An **Executed GQL** ribbon appears
only for actual returned `executed_gql` statements. **Edit in GQL →** copies the
primary returned statement into the editor without executing it. Ontology
identifier insertion chips use explicitly loaded definitions as syntax helpers,
not evidence that the independently scoped graph shares that schema.

[Prerequisites and setup](standalone-setup.md) | [Launch](standalone-launch.md)
