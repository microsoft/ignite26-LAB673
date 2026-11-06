# Three-index lab snapshots

The active restore manifest contains exactly three indexes. All use the same
55 original Cocoarynth PDFs; generator JSON is not extraction evidence.

| Index | Definition | Records |
| --- | --- | --- |
| `cocoarynth-topics` | [Definition](cocoarynth-topics-index.json) | [438 rows](cocoarynth-topics-exported.jsonl): eight labeled/vectorized representatives, 158 memberships, sitemap edges, and a manifest |
| `cocoarynth-chunks` | [Definition](cocoarynth-chunks-index.json) | [106 PDF chunk and vector rows](cocoarynth-chunks-exported.jsonl) |
| `cocoarynth-graph` | [Definition](cocoarynth-graph-index.json) | [120 PDF-supported assertions](cocoarynth-graph-exported.jsonl), representing 91 distinct facts |

All source and topic vectors have **3,072 dimensions**. The [manifest](manifest.json) lists index names, document keys, the API version, and payload checksums.

## Ontology private preview

[cocoarynth.owl](cocoarynth.owl) contains 13 classes and 19 properties proposed
from PDF excerpts. [cocoarynth-sitemap.owl](cocoarynth-sitemap.owl) describes
`Topic`, `Document`, `TextChunk`, and their navigation properties.
Neither ontology is restored as an index.

[The loader](../../infra/restore-graph-indexes.py) converts these flat RDF/XML
declarations to the constrained JSON-LD accepted by API `2026-11-01-preview`.
It creates `cocoarynth-graph-knowledge-source` and `cocoarynth-topics-knowledge-source`, each an ordinary
`searchIndex` knowledge source with `searchIndexParameters.graphOntology`
set to `kind: inline`. Both target indexes have an edge-list graph profile
whose provenance index is `cocoarynth-chunks`. The topic source supports
sitemap GQL as well as ordinary topic retrieval.

## Evidence and coverage

Business assertions contain `chunk_id`, the PDF's `parent_id`, and verbatim
`evidence_quotes`. `fact_id` identifies a distinct triple; `id` identifies
one assertion of that fact from a particular chunk. Confidence fields are
unset rather than invented. The [provenance ledger](pdf-extraction-provenance.json)
records declaration evidence, model identity, curation, and limitations.
The compact ontology and graph are not exhaustive, and the extraction was not
a managed indexer run or native ontology approval.

The eight communities and 158 memberships preserve the captured native GRZ
generation. The topic index retains six native terminal representative vectors
and two existing derived parent centroids. Labels and descriptions are separate
model enrichment from the unchanged member chunks, not native GRZ naming.
There are four roots and four children; two roots have no children.
Overall, 97 of 106 chunks are assigned and nine are unassigned.
Only 61 chunks belong to level-0 children. Topic routing includes all six
terminal communities, including the two terminal roots at level 1.

The topic index stores `hasSubtopic`, `hasMember`, and `hasTextChunk` triples
alongside the representatives. `parent_id` on a representative means its
parent community; the graph profile uses the separate `source_parent_id`
field for PDF provenance.

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
