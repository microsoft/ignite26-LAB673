# Graph traversal

## Use this path

Use this path for relationship or multi-hop questions when the published descriptor advertises graph retrieval.

## Graph flow

1. Confirm graph retrieval with `ekg-consume capabilities --descriptor <path> --json` when not already known.
2. Run `ekg-consume query --graph --descriptor <path> --query "<question>" --json`.
3. Bounds: `--depth` 1-3 (default 2), `--top` 1-10 (default 5), `--fanout` 1-50 (default 20). Widen only when the previous result stayed within limits.
4. `--detail full` (default) keeps chunk-level evidence on edges. `--detail compact` deduplicates evidence by source; it is not chunk-level provenance.

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

## Return

Report the path, the sources behind each returned edge, any traversal warning, and whether the answer is confirmed, contradicted, or unverified.
