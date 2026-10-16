# Browse topics

## Quick starts

- "What topics does this corpus cover?"
- "List the biggest GRZ communities and a few example articles from each."
- "Show me the evidence chunk behind this community."

## Use this path

Use this path to answer "what is in this corpus?" from a published GRZ build, with plain-language topics, sizes, and example articles.

## Flow

1. `grz-consume --json status` returns the communities per level and `browse_level`, the level with about 10 to 30 communities.
2. `grz-consume --json list-communities` lists that level, largest first. Pass `--level` to go finer (0 is finest) or coarser, and `--cursor` to page.
3. `grz-consume --json get-community <community-id>` returns one community with parent and children; page large child lists with `--children-page-size` and `--children-cursor`.
4. `grz-consume --json list-members <community-id>` pages through a community's chunks in stable order; follow `next_cursor` with `--cursor`.
5. `grz-consume --json get-chunk <chunk-id>` returns the chunk text and provenance.

## Answering

- Answer in plain language: topics, sizes, and example articles. Mention community IDs or levels only when the user drills in.
- Communities may be unnamed. Infer a topic from member `source_id` values and say the label is yours.
- Cite a `chunk_id` and `source_id` for every claim; do not summarize documents you did not retrieve.
- GRZ holds public or synthetic data only. If anything looks restricted, stop and say so.

## Optional Apps

The optional `grz-mcp` adapter requires an Apps-capable session. Only `grz_explore` and
`grz_evidence` are model-visible presentation entries. Their packaged views use these bounded,
app-only supporting reads:

| UI interaction | Supporting operation |
|---|---|
| Generation health and initial hierarchy | `grz_status` |
| Level selection and community pagination | `grz_list_communities` |
| Community detail and child pagination | `grz_get_community` |
| Stable member pagination | `grz_app_list_members` |
| Original chunk evidence | `grz_get_chunk` |

These reads never embed questions or call a model. Doctor and ordinary consumption stay in the CLI.
Sessions without the Apps capability expose no tools or resources. Missing or altered packaged
assets block startup instead of falling back to a general-purpose server.

## Return

Give the topics with sizes and cited example articles, name the level browsed, and suggest one next drill-down.
