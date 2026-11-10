# Source

## Lab notebooks

The [lab instructions](../instructions/skillable.md) progress from a
standard knowledge base and microsoft-retriever-1 comparison to entity/GQL exploration,
then a topic graph exercise. All three notebooks use the same Foundry IQ
service and the indexes that setup restores. The entity section is the
main part of the lab.

| Notebook | Focus |
| --- | --- |
| [Knowledge base and Microsoft Retriever 1](notebooks/01-knowledge-base-and-mr1.ipynb) | Original documents, grounded answers, activity, and a measured speed comparison with microsoft-retriever-1 |
| [Entity graph](notebooks/02-entities-and-graphs.ipynb) | Assertions and evidence, native GQL, provenance, and graph-backed retrieval |
| [Topic graph](notebooks/03-topics.ipynb) | Topic coverage, centroid-nearest chunks, hierarchy GQL, and a customer complaint investigation using topics and PDF evidence |

Each notebook loads settings from the root `.env` file and uses the
`azure-search-documents` Python SDK directly. Setup restores six indexes:
`cocoarynth-chunks`, `cocoarynth-topics`, `cocoarynth-graph`, and one index per
document group (`cocoarynth-production`, `cocoarynth-sales`, and
`cocoarynth-policies`). Part 1 creates a
knowledge source for each document-group index. Setup also creates `cocoarynth-graph-knowledge-source` and `cocoarynth-topics-knowledge-source`
with inline ontologies from the checked-in OWL files. The Search service must
support the November ontology private preview.

### Cocoarynth graph explorer

The [graph explorer](explorer/app.py) is a small local web app for the visuals
that the Azure portal doesn't show yet. It reads the same `.env` file and has
three tabs:

- **Graph ontology**: Entity types and relationships read from [the OWL file](../data/graph-data/cocoarynth.owl).
- **Graph entities**: Search for an entity, expand its neighbors, and select an assertion to see its evidence.
- **Topics**: Browse topic titles and descriptions, follow the hierarchy, and read centroid-nearest PDF chunks grouped by document.

The topic index uses the TopicGraph 2.3.0 `topicgraph-release-v2` edge-list
contract: `HasRootTopic`, `HasSubTopic`, literal properties, and
`HasCentroidVector` with retrievable `object_vector` values on terminal topics only.
Roots are level 0. The explorer derives parent vectors from proportion-weighted terminal topics.
Check coverage in `data/graph-data/manifest.json`, navigate the hierarchy with
topic graph GQL, and search the chunk index with a topic's centroid to explore
related source documents.

Each panel starts with a "From" row that names the index or file its data comes
from. Entity, fact, and chunk rows also have a **Copy ID**
button, for looking up the same document in the portal's search explorer.

Run it from the repository root with the same Python environment as the
notebooks, then open <http://localhost:8765>:

```shell
python src/explorer/app.py
```

## Run the notebooks

1. Complete [self-paced provisioning](../deploy_yourself.md) or the [Skillable setup](../infra/README.md#skillable-setup). Both call [setup-venv.py](../infra/setup-venv.py) to create or reuse the root `.venv` and install [notebook requirements](notebooks/requirements.txt), including the pinned alpha Search SDK. Setup also restores the three-index bundle and two graph-enabled knowledge sources.
2. Open each notebook in VS Code, select the repository's `.venv` Python environment as its kernel, and run the cells in order.

Running the notebooks creates knowledge sources and knowledge bases and makes billable retrieval and model calls. Clear all cell outputs before saving changes for a pull request, and never commit `.env`, service keys, or live model configuration.
