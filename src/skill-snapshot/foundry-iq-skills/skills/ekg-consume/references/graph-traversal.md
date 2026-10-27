# Graph traversal

## Use this path

Use this path for relationship or multi-hop questions when the published descriptor advertises graph retrieval.

## Graph flow

1. Confirm graph retrieval with `ekg-consume capabilities --descriptor <path> --json` when not already known.
2. Run `ekg-consume query --graph --descriptor <path> --query "<question>" --json`.
3. Bounds: `--depth` 1-3 (default 2), `--top` 1-10 (default 5), `--fanout` 1-50 (default 20). Widen only when the previous result stayed within limits.
4. `--detail full` (default) keeps chunk-level evidence on edges. `--detail compact`
   deduplicates identical evidence records while retaining distinct chunks and each edge's
   `source_ids`/`evidence_ids` links.

## Query modes

`--graph --query-mode traverse` is the default multi-hop path. Its result includes
`query_mode: "traverse"` and an ordered `executed_gql` list of the statements actually sent.

Use `--graph --query-mode gql --query "<MATCH ... RETURN ...>"` for a single read-only
statement. Writes, multiple statements, comments, semicolons, control characters and
multiline quoted literals are rejected. Ordinary newline, carriage-return and tab whitespace
outside literals is allowed. The query is limited to 2048 characters and results to 1000 rows;
use an explicit `ORDER BY` and `LIMIT` for predictable bounded results.

`--graph --query-mode nl2gql` plans against the descriptor's published `edge_types`. A
configured `endpoints.chat_deployment` uses the descriptor's OpenAI endpoint and existing
Azure credentials; that identity must already have inference access. Model/transport failures are explicit, not
silently replaced with another planner. Without a chat deployment, deterministic synthesis
supports named-entity neighborhoods (quote the exact entity name); it is not a general
natural-language reasoner or an offline Search execution path. The result identifies
`planner_strategy`. Empty rows or diagnostic errors permit one repair attempt, preserving
the original entity filter. A second diagnostic error fails explicitly.

Raw/NL results include the exact `executed_gql` string, `gql_columns`, clean `gql_rows`,
`graph_diagnostics` and `graph_stats`, including scalar projections without graph endpoints.
Returned endpoint bindings with source provenance are mapped to graph facts and use the same
source hydration and stale-source handling as traversal. Missing endpoint/predicate bindings
are not invented. Undirected matches and multi-edge rows without attributable relationship IDs
stay tabular rather than acquiring invented directions or edge-specific citations. Multi-label
nodes retain their returned labels and use the matched type, or a stable returned label, for display.
Compact results preserve query and table metadata.

## Premise checking and limits

- Retrieve the named entities and asserted facts, not only the requested impact. If evidence contradicts the premise, say so and cite the correcting source; if neither confirmed nor contradicted, say it is unverified.
- Graph retrieval never falls back silently to document retrieval. If it is not enabled, say so and stop.
- Traversal is bounded by request budget with no completeness or total-count guarantee. If anchors were skipped or a warning appears, split the question and query from the intermediate entity.
- Keep entity IDs, aliases, directed predicates, warnings, and source citations intact. Never invent a missing passage or link.

## Optional presentation

An Apps-capable host may run the optional `ekg-apps` server, whose `ekg_present` and `ekg_present_evidence` tools show bounded graph results. The operator binds the descriptor at start. It is read-only and never replaces the CLI.
The graph/evidence views use app-only `ekg_graph_query` for bounded supporting reads. Sessions
without Apps expose no tools or resources. Resource bytes must match the accepted packaged
provenance; missing or altered HTML blocks startup with a reinstall instruction.
All three tools advertise `query_mode` with the same choices; JSON `null` means `traverse`.

## Return

Report the path, the sources behind each returned edge, any traversal warning, and whether the answer is confirmed, contradicted, or unverified.
