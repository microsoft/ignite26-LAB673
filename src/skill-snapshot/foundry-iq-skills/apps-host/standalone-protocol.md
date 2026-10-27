# Protocol, tool policy and resource bounds

Pinned client/core are 2.3.1 and Apps SDK is 2.0.3. The public client option is
`versionNegotiation: {mode: {pin: "2026-07-28"}}`. Initialization checks both
the negotiated MCP revision and the server-returned supported versions; legacy
fallback is disabled. The Apps extension protocol is separately `2026-01-26`.
The SDK supplies MCP negotiation, per-request client context, cancellation and
JSON-RPC correlation; the official AppBridge supplies App protocol correlation.

Only the canonical presenters and supporting reads are permitted:

| Domain | Presentation tools | App-only supporting reads |
|---|---|---|
| Ontology | `ontology_present`, `ontology_present_evidence` | `ontology_show`, `ontology_evidence` |
| EKG | `ekg_present`, `ekg_present_evidence` | `ekg_graph_query` |
| GRZ | `grz_explore`, `grz_evidence` | `grz_status`, `grz_list_communities`, `grz_get_community`, `grz_app_list_members`, `grz_get_chunk` |

Support calls retain an opaque App session bound to the originating server and
original query/scope. EKG full-provenance reads cannot change query, query mode, top, depth
or fanout. Tool visibility is checked; missing required supporting tools prevent
startup. There are no write, provisioning or model tools in the host allowlist.

Default request deadlines are 30 seconds. EKG may explicitly use `timeoutMs`
1..120000; ontology/GRZ remain 1..30000. The same configured deadline bounds HTTP
work and official SDK requests. Cancellation/expiry retires the owning MCP
connection and stops its owned Windows process tree; reconnect is then required.
Other server connections are independent. Four concurrent HTTP operations,
16-KiB requests, 4-MiB responses, 3-MiB App documents, a 64-KiB server diagnostic tail,
32 open Apps and 10,000 request IDs per launch bound resources.

Stderr is continuously drained, not capped over the server's lifetime. Ordinary
successful reads may cumulatively emit more than 64 KiB. Only the latest 64 KiB
is retained privately; startup/exit/failure metadata reports total, retained and
truncated byte counts. Raw text is never sent to the browser or routine logs;
failed SDK errors carry a non-enumerable `diagnosticTail` for local debugging.
A per-connection token bucket permits a 1-MiB burst and replenishes at 256 KiB/s.
Exceeding that rate closes only the noisy connection with an explicit diagnostic
burst error and requires reconnect. This bounds abusive output without treating
normal accumulated Azure HTTP INFO diagnostics as a server failure.

[Prerequisites and setup](standalone-setup.md) | [Launch](standalone-launch.md)
