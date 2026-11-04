# Source

## Lab notebooks

The [lab instructions](../instructions/skillable.md) progress from a
standard knowledge base and MR1 comparison to entity/GQL exploration,
then a topics and sitemap exercise. All three notebooks use the same Foundry IQ
service and the three-index snapshot loader. The entity section is the
main part of the lab.

| Notebook | Focus |
| --- | --- |
| [Knowledge base and MR1](notebooks/lab/01-knowledge-base-and-mr1.ipynb) | Original documents, grounded answers, activity, and a measured narrow-source speed comparison |
| [Entities and graphs](notebooks/lab/02-entities-and-graphs.ipynb) | Ontology, assertions and evidence, native GQL, provenance, and graph-backed retrieval |
| [Topics](notebooks/lab/03-topics.ipynb) | Named hierarchy, coverage, topic-routed vectors, sitemap GQL, and graph-enabled topic retrieval |

Each notebook loads settings from the root `.env` file and uses the
`azure-search-documents` Python SDK directly. Setup restores exactly three
indexes: `cocoarynth-chunks`, `cocoarynth-topics`, and `cocoarynth-graph`.
Part 1 creates four domain-filtered knowledge sources over the single chunk
index, preserving the narrow policy-source MR1 comparison without four content
indexes. Setup also creates `cocoarynth-graph-ks` and `cocoarynth-topics-ks`
with inline ontologies from the checked-in OWL files. The Search service must
support the November ontology private preview.

### Cocoarynth graph explorer

The [graph explorer](explorer/app.py) is a small local web app for the visuals
that the Azure portal doesn't show yet. It reads the same `.env` file and has
three tabs:

- **Ontology**: Entity types and relationships read from [the OWL file](../data/graph-data/cocoarynth.owl).
- **Graph**: Search for an entity, expand its neighbors, and select an assertion to see its evidence.
- **Topics**: Topic labels, descriptions, the preserved hierarchy, and member PDF passages.

Run it from the repository root with the same Python environment as the
notebooks, then open <http://localhost:8765>:

```shell
python src/explorer/app.py
```

## Run the notebooks

1. Complete [self-paced provisioning](../deploy_yourself.md) or the [Skillable setup](../infra/README.md#skillable-setup). Setup installs [notebook requirements](notebooks/requirements.txt) into the root `.venv` and restores the three indexes and two graph-enabled knowledge sources.
2. Open each notebook in VS Code, select the repository's `.venv` Python environment as its kernel, and run the cells in order.

Running the notebooks creates knowledge sources and knowledge bases and makes billable retrieval and model calls. Clear all cell outputs before saving changes for a pull request, and never commit `.env`, service keys, or live model configuration.
