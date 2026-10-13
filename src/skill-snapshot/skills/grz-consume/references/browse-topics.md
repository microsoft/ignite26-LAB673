# Browse topics

## Quick starts

- "What topics does this corpus cover?"
- "List the biggest GRZ communities and a few example articles from each."
- "Show me the evidence chunk behind this community."

## Use this path

Use this path to answer "what is in this corpus?" from a published GRZ build, with plain-language topics, sizes, and example articles.

## Flow

1. `grz-skills-grz_status` returns the communities per level and `browse_level`, the level with about 10 to 30 communities.
2. `grz-skills-grz_list_communities` lists that level, largest first. Pass `level` to go finer (0 is finest) or coarser, and `cursor` to page.
3. `grz-skills-grz_get_community` returns one community by `community_id`.
4. `grz-skills-grz_list_members` pages through a community's chunks in stable order; follow `next_cursor`.
5. `grz-skills-grz_get_chunk` returns the chunk text and provenance for one `chunk_id`.

## Answering

- Answer in plain language: topics, sizes, and example articles. Mention community IDs or levels only when the user drills in.
- Communities may be unnamed. Infer a topic from member `source_id` values and say the label is yours.
- Cite a `chunk_id` and `source_id` for every claim; do not summarize documents you did not retrieve.
- GRZ holds public or synthetic data only. If anything looks restricted, stop and say so.

## Return

Give the topics with sizes and cited example articles, name the level browsed, and suggest one next drill-down.
