# Deploy to your own Azure subscription

This guide provisions the Cocoarynth LAB673 environment without Skillable, Fabric IQ, or Work IQ. The [lab notebooks](src/notebooks/) use Cocoarynth's origin, quality, logistics and retail, and policy records.

## Prerequisites

- An Azure subscription with model quota in a Content Understanding-supported region and serverless Search capacity in West Central US.
- Access to the November ontology private preview on the target Search service, including inline-ontology knowledge sources and native GQL.
- Permissions to deploy resources, assign Azure RBAC roles, and list Search/Foundry API keys.
- Azure Developer CLI (`azd`), Git, and Python available locally.

## Provision resources

Provisioning restores six indexes from `data/graph-data/`: `cocoarynth-topics`, `cocoarynth-chunks`, `cocoarynth-graph`, and three document-group indexes (`cocoarynth-production`, `cocoarynth-sales`, and `cocoarynth-policies`) split from the chunk snapshot. It also creates graph-enabled knowledge sources for the business graph and topic sitemap from the checked-in OWL files. No document ingestion is needed. The notebooks create the three document knowledge sources and knowledge bases. Maintainers who change the documents can [rebuild the snapshots](infra/README.md#rebuild-the-index-snapshots).

```sh
git clone https://github.com/microsoft/ignite26-LAB673.git
cd ignite26-LAB673
azd auth login
azd init
azd env set AZURE_LOCATION westus3
azd env set AZURE_SEARCH_SKU serverless
azd provision
```

If already working in this repository, start with `azd auth login`. During `azd init`, choose a new environment name and use the existing project files; do not select a new template. Select your subscription when prompted.

`AZURE_LOCATION` controls Foundry and Blob Storage. `westus3` matches the source lab and supports Content Understanding; Search always deploys in **West Central US** regardless of that setting. Search defaults to `serverless` with the paid `standard` Knowledge Retrieval plan required by Microsoft Retriever 1. This plan is independent of the Search SKU; it does not change the SKU to Standard (S1). For other Foundry locations, consult [Content Understanding region support](https://learn.microsoft.com/azure/ai-services/content-understanding/language-region-support) and check model availability. Search capacity and model quota are not guaranteed by these templates.

The post-provision hook runs [setup-venv.py](infra/setup-venv.py) to create or reuse `.venv` and install the pinned alpha Search SDK and notebook dependencies. It then writes a local `.env` with deployment outputs and API keys and configures Content Understanding. With restoration enabled, it restores the three-index bundle and both inline-ontology knowledge sources. Missing or inconsistent artifacts stop setup before restoration writes. Existing resources are verified and reused only if they match; setup does not overwrite or delete an earlier dataset. `.env`, `.azure`, and `.venv` are ignored by Git. Do not share `.env` or logs containing credentials.

The template does not grant private-preview access. A deployment without that access cannot complete the graph and sitemap setup; it does not silently substitute text-only retrieval.

The default LLM is `gpt-6-luna` (`2026-09-22`, capacity 200, enough for the knowledge base's multi-step retrieval), and embeddings use `text-embedding-3-large` (`1`, capacity 30). To override the LLM or capacities before provisioning:

```sh
azd env set LLM_MODEL_NAME gpt-6-luna
azd env set LLM_MODEL_VERSION 2026-09-22
azd env set LLM_MODEL_CAPACITY 200
azd env set EMBEDDING_MODEL_CAPACITY 30
```

Use a model supported by your region, subscription, and Content Understanding analyzers. The Content Understanding setup and optional indexing tool use the selected LLM name and deployment.

## Run the notebooks

All six indexes and both graph-enabled knowledge sources are included in setup; no separate graph restoration is needed.

Open the [lab notebooks](src/notebooks/) in VS Code, select the root `.venv` as the kernel, and run the cells in order. See the [source guide](src/README.md) for what the notebooks create.

## Cleanup

```sh
azd down
```

Confirm resource-group deletion when prompted. Foundry accounts can remain soft-deleted, retaining names or quota. See [cleanup guidance](infra/README.md#cleanup) for the scoped purge script before reusing an environment.