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
the canonical `CommunityGraph`, `Community`, and `Vector` navigation schema.
Neither ontology is restored as an index.

[The loader](../../infra/restore-graph-indexes.py) converts these flat RDF/XML
declarations to the constrained JSON-LD accepted by API `2026-11-01-preview`.
It creates `cocoarynth-graph-knowledge-source` and `cocoarynth-topics-knowledge-source`, each an ordinary
`searchIndex` knowledge source with `searchIndexParameters.graphOntology`
set to `kind: inline`. Both target indexes have an edge-list graph profile.
The business graph resolves its assertion evidence through `cocoarynth-chunks`.
The topic graph has no per-chunk provenance or membership edges; its source
supports hierarchy GQL and ordinary retrieval of topic titles and descriptions.

## Evidence and coverage

Business assertions contain `chunk_id`, the PDF's `parent_id`, and verbatim
`evidence_quotes`. `fact_id` identifies a distinct triple; `id` identifies
one assertion of that fact from a particular chunk. Confidence fields are
unset rather than invented. The [provenance ledger](pdf-extraction-provenance.json)
records declaration evidence, model identity, curation, and limitations.
The compact ontology and graph are not exhaustive, and the extraction was not
a managed indexer run or native ontology approval.

## Canonical topic format

The topic snapshot follows the current Foundry IQ plugin's
`topicgraph-release-v1` contract. Each row is a `subject_id` / `predicate` /
typed object statement in `topicgraph-community`. There is no `kind`,
`community_id`, `centroid`, or `payload` field and no embedded manifest.

| Predicate | Object field | Meaning |
| --- | --- | --- |
| `HasRootCommunity` | `object_id` | `CommunityGraph` to a broad root `Community` |
| `HasSubCommunity` | `object_id` | Parent `Community` to child `Community` |
| `prop:title`, `prop:description` | `object_string` | Topic display text |
| `prop:level`, `prop:proportion`, `prop:parentProportion` | `object_double` | Depth and shares of clustered chunks / parent |
| `HasCentroidVector` | `object_vector` | A leaf's retrievable 3,072-dimensional centroid |

Roots are level **0**, children level **1**. Stored IDs are opaque
`community:<n>` values; the plugin CLI displays them as `topic:<n>`.
Only the six terminal communities store vectors, including the two terminal
roots. A parent's centroid is derived at read time from the
proportion-weighted mean of its leaf centroids.

This is a deterministic format adaptation, **not a new native build**.
The eight communities, four parent-child links, counts, titles, descriptions,
and six native leaf vectors are preserved from the previous capture.
Titles and descriptions remain separate model enrichment from the captured
member chunks, not native GRZ naming. The [restore manifest](manifest.json)
records the source generation, old-to-new IDs, pinned plugin contract, and
coverage: 97 of 106 chunks were assigned and nine were unassigned; 61 also
belong to level-1 children. The business ontology and extraction are unchanged.

A topic's count is `round(proportion × 97)`, using the **clustered** source
count rather than all 106 chunks. The explorer and notebook search
`cocoarynth-chunks` with the topic centroid, capped at that count and at 1,000,
to show nearest chunks. These approximate the topic's core; they are not exact
stored memberships and can include originally unassigned chunks.
GQL traverses the topic hierarchy only. PDF examples require a separate source
vector query, not a graph join or graph provenance lookup.

## Restoration and retained captures

[Lab provisioning](../../infra/README.md) restores all three indexes, splits the
chunk snapshot into three document-group indexes for Part 1, and creates both
graph-enabled knowledge sources by default. Offline validation needs only Python:

```powershell
python .\infra\restore-graph-indexes.py --validate-only
```

Run the command from the repository root. See [restore guidance](../../infra/README.md#restore-graph-snapshots-private-preview)
for service requirements and destination handling.

Older ontology-index, graph-source, topic-source, separate-vector, and sitemap
capture files remain in this folder for provenance. They are **not in the active
manifest and are never restored by the lab loader**. In particular, the old
generator-backed graph-source capture must not be used as PDF extraction evidence.
An existing service with the retired topic layout is rejected by `--ensure`;
use a fresh approved lab service or an explicit prefix rather than overwrite it.
