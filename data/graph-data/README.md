# Graph index snapshots

Index definitions and captured records for rehydrating the Cocoarynth graph-related indexes.

| Snapshot | Definition | Records |
| --- | --- | --- |
| Business sources | [Definition](cocoarynth-graph-sources-index.json) | [609 source chunks](cocoarynth-graph-sources-exported.jsonl) |
| Ontology | [Definition](cocoarynth-ontology-index.json) | [288 ontology rows](cocoarynth-ontology-exported.jsonl) |
| Business graph | [Definition](cocoarynth-graph-index.json) | [3,938 assertion rows](cocoarynth-graph-exported.jsonl) |
| Source vectors | [Definition](cocoarynth-topic-sources-index.json) | [106 captured chunk/vector rows](cocoarynth-topic-sources-exported.jsonl) |
| Native GRZ topics | [Definition](cocoarynth-topics-index.json) | [273 topic, membership, evidence, and manifest rows](cocoarynth-topics-exported.jsonl) |
| Topic vectors | [Definition](cocoarynth-topic-vectors-index.json) | [8 vectors: 6 native and 2 derived parent centroids](cocoarynth-topic-vectors-exported.jsonl) |
| Sitemap graph | [Definition](cocoarynth-sitemap-graph-index.json) | [379 assertion rows](cocoarynth-sitemap-graph-exported.jsonl) |

All source and topic vectors have **3,072 dimensions**. The [manifest](manifest.json) lists index names, document keys, the API version, and payload checksums.

These additional snapshots are not restored automatically by [lab provisioning](../../infra/README.md).
