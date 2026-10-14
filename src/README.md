# Source

[Part 1: Build knowledge bases with agentic retrieval](notebooks/part1-standard-foundry-iq-kb.ipynb) adapts the ILL344 teaching flow to Cocoarynth Chocolate Works, a fictional bean-to-bar chocolate maker.

It creates a standalone file knowledge source and KB for the label and marketing claims policy. It then connects `cocoarynth-origins`, `cocoarynth-quality`, `cocoarynth-logistics-retail`, and `cocoarynth-policies` to the four-source `cocoarynth-kb-all`, and uses it to solve mysteries whose evidence is spread across farm, factory, shipping, retail, and policy records. The answers and evidence are in [the mysteries file](../data/cocoarynth/questions.yaml). Fabric and Work IQ are not required.

## Run the notebook

1. Complete [self-paced provisioning and index preparation](../deploy_yourself.md) or the [Skillable setup](../infra/README.md#skillable-setup). Setup installs [notebook requirements](notebooks/requirements.txt) into the root `.venv` and restores the four indexes from snapshots.
2. Open the notebook in VS Code and select the repository's `.venv` Python environment as its kernel.
3. Run the cells in order. The notebook locates the root `.env` and policy PDF whether the kernel starts in the repository root or `src/notebooks/`.

Restart the kernel if you previously ran an earlier version, then run all cells in order.

Running the notebook creates knowledge sources and knowledge bases and makes billable ingestion/retrieval/model calls. It uses answer synthesis. It does not configure Fabric, Work IQ, or an agent.
