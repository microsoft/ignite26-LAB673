# Deploy to your own Azure subscription

This guide provisions the Cocoarynth LAB673 environment without Skillable, Fabric IQ, or Work IQ. The [lab notebooks](src/notebooks/lab/) use Cocoarynth's origin, quality, logistics and retail, and policy records.

## Prerequisites

- An Azure subscription with sufficient model quota and serverless Search capacity in West Central US.
- Permissions to deploy resources, assign Azure RBAC roles, and list Search/Foundry API keys.
- Azure Developer CLI (`azd`), Git, and Python available locally.

## Provision resources

Provisioning restores the four Cocoarynth indexes from the snapshots in `data/index-data/`, so no document ingestion is needed. Knowledge sources and knowledge bases are left for the notebooks to create. Maintainers who change the documents can [rebuild the snapshots](infra/README.md#rebuild-the-index-snapshots).

```sh
git clone https://github.com/microsoft/ignite26-LAB673.git
cd ignite26-LAB673
azd auth login
azd init
azd env set AZURE_LOCATION westus3
azd provision
```

If already working in this repository, start with `azd auth login`. During `azd init`, choose a new environment name and use the existing project files; do not select a new template. Select your subscription when prompted.

`AZURE_LOCATION` controls Foundry and Blob Storage. `westus3` matches the source lab and supports Content Understanding; Search always deploys **serverless in West Central US** regardless of that setting. For other Foundry locations, consult [Content Understanding region support](https://learn.microsoft.com/azure/ai-services/content-understanding/language-region-support) and check model availability. Search capacity and model quota are not guaranteed by these templates.

The post-provision hook prepares `.venv`, installs infrastructure and notebook dependencies, writes a local `.env` with deployment outputs and API keys, and configures Content Understanding. With restoration enabled, it also restores the four Cocoarynth indexes from their captured snapshots. Missing snapshots stop setup before restoration writes. `.env`, `.azure`, and `.venv` are ignored by Git. Do not share `.env` or logs containing credentials.

The default LLM is `gpt-5.4` (`2026-03-05`, capacity 200, enough for the knowledge base's multi-step retrieval), and embeddings use `text-embedding-3-large` (`1`, capacity 30). To override the LLM or capacities before provisioning:

```sh
azd env set LLM_MODEL_NAME gpt-5.4
azd env set LLM_MODEL_VERSION 2026-03-05
azd env set LLM_MODEL_CAPACITY 200
azd env set EMBEDDING_MODEL_CAPACITY 30
```

Use a model supported by your region, subscription, and Content Understanding analyzers. The Content Understanding setup and optional indexing tool use the selected LLM name and deployment.

## Run the notebooks

Notebooks 2 and 3 also need the graph and topic indexes. [Restore the graph snapshots](infra/README.md#restore-graph-snapshots-private-preview) on the same Foundry IQ service before running them.

Open the [lab notebooks](src/notebooks/lab/) in VS Code, select the root `.venv` as the kernel, and run the cells in order. See the [source guide](src/README.md) for what the notebooks create.

## Cleanup

```sh
azd down
```

Confirm resource-group deletion when prompted. Foundry accounts can remain soft-deleted, retaining names or quota. See [cleanup guidance](infra/README.md#cleanup) for the scoped purge script before reusing an environment.