# Rank and verify

## Quick starts

- "Why is `<topic>` the largest community?" (premise check)
- "Show what a global retrieve would return for this question."

## Use this path

Use this path to test whether a question's premise matches the build, or to preview global retrieval behavior.

## Premise check

A question such as "why is X the largest topic?" assumes facts. Compare them with the sizes and levels from `grz-consume --json status` and `list-communities` and the text from `get-chunk`.

1. If the evidence contradicts the premise, say so first and cite the `community_id`, `chunk_id`, and `source_id`, then answer the corrected question.
2. If it neither confirms nor contradicts it, say it is unverified in this build and answer what you can.
3. Never answer as if a contradicted premise were true.

## Global-retrieve stand-in

`grz-simulate simulate-global-retrieve --question "..."` embeds once locally; `--vector <json> --embedding-model-id <id>` is also supported. On v2 generations it returns question-ranked members per selected community (capped at 50); on v1 it falls back to a stable sample. It is a developer stand-in, not product `globalRetrieve`; say so when you use it.

Pass the same descriptor and endpoint/documents flags as consume, before the verb. Text
embedding supports only the registered local model and may download its weights. For other
embedding identities, use a matching precomputed vector; never substitute a model or dimension.

## Return

Give the ranked evidence with citations, state any premise correction first, and name whether the result is the stand-in.
