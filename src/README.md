# Source

[Part 1: Build knowledge bases with agentic retrieval](notebooks/part1-standard-foundry-iq-kb.ipynb) adapts the ILL344 teaching flow to Cocoarynth Chocolate Works, a fictional bean-to-bar chocolate maker.

It creates a standalone file knowledge source and KB for the label and marketing claims policy. It then connects `cocoarynth-origins`, `cocoarynth-quality`, `cocoarynth-logistics-retail`, and `cocoarynth-policies` to the four-source `cocoarynth-kb-all`, and uses it to solve mysteries whose evidence is spread across farm, factory, shipping, retail, and policy records. The answers and evidence are in [the mysteries file](../data/cocoarynth/questions.yaml). Fabric and Work IQ are not required.

## Run the notebook

1. Complete [self-paced provisioning and index preparation](../deploy_yourself.md) or the [Skillable setup](../infra/README.md#skillable-setup). Setup installs [notebook requirements](notebooks/requirements.txt) into the root `.venv` and restores the four indexes from snapshots.
2. Open the notebook in VS Code and select the repository's `.venv` Python environment as its kernel.
3. Run the cells in order. The notebook locates the root `.env` and policy PDF whether the kernel starts in the repository root or `src/notebooks/`.

Restart the kernel if you previously ran an earlier version, then run all cells in order.

Running the notebook creates knowledge sources and knowledge bases and makes billable ingestion/retrieval/model calls. It uses answer synthesis. It does not configure Fabric, Work IQ, or an agent.

## Preview REST notebooks

These small follow-on exercises keep the
[earlier lab's](https://github.com/microsoft/Build26-LAB532-from-data-to-context-agent-ready-knowledge-with-foundry-iq/tree/main)
mission, numbered steps, activity inspection, and source hunt format. They use
Cocoarynth's existing records and raw REST calls, without using the Azure Search
Python SDK.

| Notebook | Exercise |
|----------|----------|
| [Part 2: Retrieve evidence with microsoft-retriever-1](notebooks/part2-microsoft-retriever-1.ipynb) | Connect the policies index, configure the built-in retriever, and inspect extractive evidence |
| [Part 3: Add answer synthesis to the retriever](notebooks/part3-retriever-answer-synthesis.ipynb) | Connect all four indexes, add an existing Azure OpenAI model, and investigate a multi-document mystery |

The graph index for this lab is not available yet. These exercises use ordinary
search indexes; they do not build a graph or simulate graph-backed results.
Each notebook runs independently in a fresh kernel.

### Prepare the preview connection

Use a prepared Search service that supports `microsoftRetriever1` with
`2026-11-01-preview`. The normal self-paced deployment is not assumed to enable
the feature or populate a separate preview service. The session owner must supply
access and the populated Cocoarynth indexes before you start. These notebooks do
not provision resources, generate embeddings, or change service billing settings.
If retrieval returns HTTP 402 requiring Standard Knowledge Retrieval, ask the
service owner to resolve that prerequisite.

Set these variables in the root `.env` or export them before starting the notebook
kernel. Exported values take precedence over `.env`; keep the preview endpoint
and credential separate from the normal Part 1 deployment variables.

| Variable | Value |
|----------|-------|
| `AZURE_SEARCH_PREVIEW_ENDPOINT` | The approved, feature-enabled Search service's HTTPS origin |
| `AZURE_SEARCH_PREVIEW_ADMIN_KEY` | Its admin key, kept local |
| `AZURE_SEARCH_PREVIEW_RESOURCE_PREFIX` | Your unique prefix starting with `lab673-`, for example `lab673-alex-preview` |
| `AZURE_SEARCH_PREVIEW_INDEX_PREFIX` | Optional; defaults to `cocoarynth`, producing names such as `cocoarynth-policies` |

Part 2 requires only the policies index. Part 3 requires all four indexes and the
existing `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_KEY`,
`AZURE_OPENAI_CHATGPT_DEPLOYMENT`, and `AZURE_OPENAI_CHATGPT_MODEL_NAME` settings
for an answer-synthesis deployment the preview service can call. No model is
provisioned by either notebook.

Use the existing lab kernel and run cells in order. The shared
[`rest_helpers.py`](notebooks/rest_helpers.py) loads `.env` when present, sends
non-streaming JSON requests with a finite timeout, rejects redirects and partial
HTTP 206 results, and surfaces service errors without displaying configured keys.
It conditionally creates or updates only knowledge sources and bases owned by
your notebook prefix; it never replaces the prepared indexes.

### Finish exploring

Retrieval and synthesis calls are billable. Each notebook has an optional cleanup
cell, disabled by default, that removes its knowledge base before its sources.
It leaves the prepared indexes and other notebooks' resources unchanged. Clear
all cell outputs before saving changes for a pull request, and never commit
`.env`, service keys, or live model configuration.
