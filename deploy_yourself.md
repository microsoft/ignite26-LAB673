# Deploy to your own Azure subscription

This guide provisions the LAB673 environment without Skillable, Fabric IQ, or Work IQ. The [first notebook](src/notebooks/part1-standard-foundry-iq-kb.ipynb) is imported from ILL344 as the lab's starting point.

## Prerequisites

- An Azure subscription with sufficient model quota and serverless Search capacity in West Central US.
- Permissions to deploy resources, assign Azure RBAC roles, and list Search/Foundry API keys.
- Azure Developer CLI (`azd`), Git, and Python available locally. The imported optional live-indexing tool requires Python 3.11 or newer.

## Provision resources

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

The post-provision hook prepares `.venv`, installs infrastructure and notebook dependencies, writes a local `.env` with deployment outputs and API keys, configures Content Understanding, and restores the two committed indexes. `.env`, `.azure`, and `.venv` are ignored by Git. Do not share `.env` or logs containing credentials.

The default LLM is `gpt-5.4` (`2026-03-05`, capacity 50), and embeddings use `text-embedding-3-large` (`1`, capacity 30). To override the LLM or capacities before provisioning:

```sh
azd env set LLM_MODEL_NAME gpt-5.4
azd env set LLM_MODEL_VERSION 2026-03-05
azd env set LLM_MODEL_CAPACITY 50
azd env set EMBEDDING_MODEL_CAPACITY 30
```

Use a model supported by your region, subscription, and Content Understanding analyzers. The Content Understanding setup and optional indexing tool use the selected LLM name and deployment.

## Snapshot restoration

Provisioning restores the committed supplier-evidence and sourcing-document indexes by default. For an existing environment that previously disabled restoration, enable it and rerun provisioning:

```sh
azd env set RESTORE_INDEX_SNAPSHOTS true
azd provision
```

Restoration replaces records in those two indexes with precomputed text and vectors; it does not upload PDFs or exercise Content Understanding. Set `RESTORE_INDEX_SNAPSHOTS` to `false` only when you want empty indexes for building a live ingestion pipeline. See [infrastructure guidance](infra/README.md#optional-data-tools) for optional live-indexing commands, authentication, and the rebuilding behavior.

Knowledge sources and knowledge bases are left for the lab exercises; neither data setup option creates them.

## Run the notebook

Open [Part 1](src/notebooks/part1-standard-foundry-iq-kb.ipynb) in VS Code, select the root `.venv` as its kernel, and run cells in order. See [source guidance](src/README.md) for what the notebook creates.

## Cleanup

```sh
azd down
```

Confirm resource-group deletion when prompted. Foundry accounts can remain soft-deleted, retaining names or quota. See [cleanup guidance](infra/README.md#cleanup) for the scoped purge script before reusing an environment.