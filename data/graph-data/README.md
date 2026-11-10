# Three-index lab snapshots

The active restore manifest contains exactly three indexes. All use the same
55 original Cocoarynth PDFs; generator JSON is not extraction evidence.

| Index | Definition | Records |
| --- | --- | --- |
| `cocoarynth-topics` | [Definition](cocoarynth-topics-index.json) | [54 canonical edge-list facts](cocoarynth-topics-exported.jsonl): eight named topics, hierarchy links, proportions, and six leaf vectors |
| `cocoarynth-chunks` | [Definition](cocoarynth-chunks-index.json) | [106 PDF chunk and vector rows](cocoarynth-chunks-exported.jsonl) |
| `cocoarynth-graph` | [Definition](cocoarynth-graph-index.json) | [120 PDF-supported assertions](cocoarynth-graph-exported.jsonl), representing 91 distinct facts |

All source and topic vectors have **3,072 dimensions**. The [manifest](manifest.json) lists index names, document keys, the API version, and payload checksums.

## Ontology private preview

[cocoarynth.owl](cocoarynth.owl) contains 13 classes and 19 properties proposed
from PDF excerpts. [cocoarynth-sitemap.owl](cocoarynth-sitemap.owl) describes
the TopicGraph 2.3.0 `TopicGraph`, `Topic`, and `Vector` navigation schema.

[The loader](../../infra/restore-graph-indexes.py) converts these flat RDF/XML
declarations to the constrained JSON-LD accepted by API `2026-11-01-preview`.
It creates `cocoarynth-graph-knowledge-source` and `cocoarynth-topics-knowledge-source`, each an ordinary
`searchIndex` knowledge source with `searchIndexParameters.graphOntology`
set to `kind: inline`. Both target indexes have an edge-list graph profile.
The business graph resolves its assertion evidence through `cocoarynth-chunks`.
The topic knowledge source supports hierarchy GQL and retrieval of topic
titles and descriptions. Topic centroid queries retrieve related PDF chunks
from the source index.

## Evidence and coverage

Business assertions contain `chunk_id`, the PDF's `parent_id`, and verbatim
`evidence_quotes`. `fact_id` identifies a distinct triple; `id` identifies
one assertion of that fact from a particular chunk. Confidence fields are
unset rather than invented. The compact ontology and graph are not exhaustive,
and the extraction was not a managed indexer run or native ontology approval.

## Canonical topic format

The topic index uses the Foundry IQ plugin's
`topicgraph-release-v2` contract. Each row is a `subject_id` / `predicate` /
typed object statement in `topicgraph-topic`.

| Predicate | Object field | Meaning |
| --- | --- | --- |
| `HasRootTopic` | `object_id` | `TopicGraph` to a broad root `Topic` |
| `HasSubTopic` | `object_id` | Parent `Topic` to child `Topic` |
| `prop:title`, `prop:description` | `object_string` | Topic display text |
| `prop:level`, `prop:proportion`, `prop:parentProportion` | `object_double` | Depth and shares of clustered chunks / parent |
| `HasCentroidVector` | `object_vector` | A leaf's retrievable 3,072-dimensional centroid |

Roots are level **0**, children level **1**. Stored IDs are opaque
`topic:<n>` values.
Only the six terminal topics store vectors, including the two terminal
roots. A parent's centroid is derived at read time from the
proportion-weighted mean of its leaf centroids.

The hierarchy contains eight topics and four parent-child links.
Titles and descriptions summarize each group's chunks. The [lab metadata](manifest.json)
records coverage and topic counts: the groups cover 97 of 106 source chunks,
and 61 also belong to level-1 children.

A topic's count is `round(proportion × 97)`, using the **clustered** source
count rather than all 106 chunks. The explorer and notebook search
`cocoarynth-chunks` with the topic centroid, capped at that count and at 1,000,
to show nearest chunks. These approximate the topic's core. The search ranks
chunks from the full source index by similarity to the centroid.
Use GQL to navigate the topic hierarchy and source-vector queries to find PDF
examples.

## Restoration

[Lab provisioning](../../infra/README.md) restores all three indexes, splits the
chunk snapshot into three document-group indexes for Part 1, and creates both
graph-enabled knowledge sources by default. Offline validation needs only Python:

```powershell
python .\infra\restore-graph-indexes.py --validate-only
```

Run the command from the repository root. See [restore guidance](../../infra/README.md#restore-graph-snapshots-private-preview)
for service requirements and destination handling.

Use an explicit prefix for a separate restoration on an existing service.
The loader verifies destination schemas and data before reusing resources.
