# Document retrieval

## Quick starts

- "Which documents mention `<topic>`? Cite the original files."
- "Find the passages that support this answer about `<entity>`."

## Use this path

Use this path when the user needs cited document evidence from a published EKG deployment and graph traversal is either unnecessary or unavailable.

## Retrieval flow

1. Confirm the question is about reading evidence, not changing the deployment.
2. Use `ekg-skills-ekg_consume_query` or `ekg-skills-ekg_consume_retrieve`; the tool names are aliases.
3. Set `vector: false` for lexical-only retrieval. Leave `vector` unset or true for hybrid retrieval when embeddings are available.
4. Use `top` only when the user needs more or fewer hits than the default.

## Safety and limits

- Return the cited provenance from the tool response, not invented summaries of unseen documents.
- If the result contradicts the user question, say that first.
- If the tool fails with a read-only backend error, return the safe message and next diagnostic step instead of retrying a mutation.
- Telemetry is observational only. If latency matters, summarize it from the returned `telemetry` block or a later local `ekg-skills-ekg_build_telemetry` report.

## Return

Answer from the retrieved evidence, name whether the search was lexical or hybrid, and cite the returned sources.
