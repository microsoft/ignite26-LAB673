# Rank and verify

## Quick starts

- "Why is `<topic>` the largest community?" (premise check)

## Use this path

Use this path to test whether a question's premise matches the build.

## Premise check

A question such as "why is X the largest topic?" assumes facts. Compare them with the sizes and levels from `grz-consume --json status` and `list-communities` and the text from `get-chunk`.

1. If the evidence contradicts the premise, say so first and cite the `community_id`, `chunk_id`, and `source_id`, then answer the corrected question.
2. If it neither confirms nor contradicts it, say it is unverified in this build and answer what you can.
3. Never answer as if a contradicted premise were true.

The developer global-retrieval simulator is not included in this snapshot.
Do not imply that community browsing runs product `globalRetrieve`.

## Return

Give the evidence with citations and state any premise correction first.
