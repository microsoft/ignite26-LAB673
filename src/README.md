# Source

[Part 1: Build knowledge bases with agentic retrieval](notebooks/part1-standard-foundry-iq-kb.ipynb) is the starting notebook, imported from ILL344 at commit `dc74ce12fc9c4d1fc9c49fcd7b0c5cbf482cbcca`.

It creates a file knowledge source for Caldova's purchasing policy, connects the restored supplier-evidence and sourcing-document indexes, and builds knowledge bases with agentic retrieval. Fabric and Work IQ are not required.

## Run the notebook

1. Complete [self-paced provisioning](../deploy_yourself.md) or the [Skillable setup](../infra/README.md#skillable-setup). Setup installs [notebook requirements](notebooks/requirements.txt) into the root `.venv` and restores the two indexes by default.
2. Open the notebook in VS Code and select the repository's `.venv` Python environment as its kernel.
3. Run the cells in order. The notebook locates the root `.env` and policy PDF whether the kernel starts in the repository root or `src/notebooks/`.

The imported notebook has no saved outputs. Running it creates knowledge sources and knowledge bases and makes billable retrieval/model calls. It does not configure Fabric, Work IQ, or an agent.
