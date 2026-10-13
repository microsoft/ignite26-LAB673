# Graph traversal

## Use this path

Use this path when the user asks relationship or multi-hop questions and the published descriptor advertises graph retrieval.

## Graph flow

1. Confirm graph retrieval is enabled with `ekg-skills-ekg_consume_capabilities` when that is not already known.
2. Use `ekg-skills-ekg_consume_graph_query` with the user question.
3. Increase `depth`, `top`, or `fanout` only when the user needs broader traversal and the previous result stayed within limits.
4. The MCP tool defaults `detail` to `compact`. Ask for `full` only when chunk-level provenance is needed.

## Premise checking and limits

- Check named entities separately when the prompt contains a factual assumption. If evidence contradicts the premise, correct it before answering the corrected question.
- Graph retrieval never falls back silently to document retrieval.
- If the tool warns that anchors were skipped or traversal hit a round-trip limit, say so and split the question into smaller hops instead of overstating coverage.
- If graph retrieval is not enabled, return that explicitly and stop.

## Return

Report the path, the cited sources behind the returned edges, any traversal warning, and whether the answer is confirmed, contradicted, or still unverified by the evidence.
