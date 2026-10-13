# Rank and verify

## Quick starts

- "Which articles in community `<id>` best answer this question?"
- "Why is `<topic>` the largest community?" (premise check)

## Use this path

Use this path to rank a community's members for a question or to check whether a question's premise matches the build.

## Ranked members

- Call `grz-skills-grz_list_members` with `question` and `top_k` (up to 50) to rank distinct articles inside one community, or pass `question_vector` with a vector from the model named in `status`.
- Question text needs the `embed` extra; a vector needs no embedder. Older v1 builds can page members, but question ranking requires a rebuild (`MEMBER_RANKING_UNAVAILABLE`).
- Ranked lists can carry off-topic tails from weakly matching communities. Report scores and do not overstate coverage.

## Premise check

A question such as "why is X the largest topic?" assumes facts. Compare them with the sizes and levels from `grz-skills-grz_status` and `grz-skills-grz_list_communities` and the text from `grz-skills-grz_get_chunk`.

1. If the evidence contradicts the premise, say so first and cite the `community_id`, `chunk_id`, and `source_id`, then answer the corrected question.
2. If it neither confirms nor contradicts it, say it is unverified in this build and answer what you can.
3. Never answer as if a contradicted premise were true.

## Return

Give the ranked evidence with citations and state any premise correction first.
