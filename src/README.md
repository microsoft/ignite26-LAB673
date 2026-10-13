# Source

The [temporary skill distribution snapshot](skill-snapshot/README.md) contains
the pinned Foundry IQ, graph-routing, EKG, grounding, GRZ and ontology skills and
production runtimes for testing. See its inventory and runtime prerequisites
before using it; it is not a published release.

[Part 1: Build knowledge bases with agentic retrieval](notebooks/part1-standard-foundry-iq-kb.ipynb) adapts the ILL344 teaching flow to Cocoarynth, the chocolate retailer from [the developer KB lab](https://github.com/pamelas-organization/developer-kb-for-github-copilot).

It creates a standalone file knowledge source and KB for the wholesale traceability data-sharing policy. It then connects `cocoarynth-documents-index` and `cocoarynth-engineering-practices-index` to the two-source `cocoarynth-kb-all`. Retrieval questions combine partner CSV requirements, data-sharing rules, and engineering guidance. Fabric and Work IQ are not required.

## Run the notebook

1. Complete [self-paced provisioning and index preparation](../deploy_yourself.md) or the [Skillable setup](../infra/README.md#skillable-setup). Setup installs [notebook requirements](notebooks/requirements.txt) into the root `.venv`. Snapshot restoration remains enabled by default, but Cocoarynth snapshots must be captured before delivery.
2. Open the notebook in VS Code and select the repository's `.venv` Python environment as its kernel.
3. Run the cells in order. The notebook locates the root `.env` and policy PDF whether the kernel starts in the repository root or `src/notebooks/`.

Restart the kernel if you previously ran the Caldova version, then run all cells in order. Old execution outputs have been cleared.

Running the notebook creates knowledge sources and knowledge bases and makes billable ingestion/retrieval/model calls. It uses answer synthesis rather than the developer KB app's extractive output. No application repository is indexed, so the KB cannot verify the application's current implementation. It does not configure Fabric, Work IQ, or an agent.
