# Deploy to your own Azure subscription

This guide provisions the Cocoarynth LAB673 environment without Skillable, Fabric IQ, or Work IQ. The [first notebook](src/notebooks/part1-standard-foundry-iq-kb.ipynb) uses the chocolate-shop lab's product documents and engineering practices.

## Prerequisites

- An Azure subscription with sufficient model quota and serverless Search capacity in West Central US.
- Permissions to deploy resources, assign Azure RBAC roles, and list Search/Foundry API keys.
- Azure Developer CLI (`azd`), Git, and Python available locally. The imported optional live-indexing tool requires Python 3.11 or newer.

## Provision resources

The new Cocoarynth snapshots have not been captured yet. For the initial maintainer deployment, temporarily skip restoration and follow the index-preparation section below. Once real Cocoarynth snapshots are included in the repository, leave restoration enabled for attendee deployments.

```sh
git clone https://github.com/microsoft/ignite26-LAB673.git
cd ignite26-LAB673
azd auth login
azd init
azd env set AZURE_LOCATION westus3
azd env set RESTORE_INDEX_SNAPSHOTS false
azd provision
```

If already working in this repository, start with `azd auth login`. During `azd init`, choose a new environment name and use the existing project files; do not select a new template. Select your subscription when prompted.

`AZURE_LOCATION` controls Foundry and Blob Storage. `westus3` matches the source lab and supports Content Understanding; Search always deploys **serverless in West Central US** regardless of that setting. For other Foundry locations, consult [Content Understanding region support](https://learn.microsoft.com/azure/ai-services/content-understanding/language-region-support) and check model availability. Search capacity and model quota are not guaranteed by these templates.

The post-provision hook prepares `.venv`, installs infrastructure and notebook dependencies, writes a local `.env` with deployment outputs and API keys, and configures Content Understanding. With restoration enabled, it also restores the two Cocoarynth indexes from their captured snapshots. Missing snapshots stop setup before restoration writes; the old Caldova snapshots are never used as a fallback. `.env`, `.azure`, and `.venv` are ignored by Git. Do not share `.env` or logs containing credentials.

The default LLM is `gpt-5.4` (`2026-03-05`, capacity 50), and embeddings use `text-embedding-3-large` (`1`, capacity 30). To override the LLM or capacities before provisioning:

```sh
azd env set LLM_MODEL_NAME gpt-5.4
azd env set LLM_MODEL_VERSION 2026-03-05
azd env set LLM_MODEL_CAPACITY 50
azd env set EMBEDDING_MODEL_CAPACITY 30
```

Use a model supported by your region, subscription, and Content Understanding analyzers. The Content Understanding setup and optional indexing tool use the selected LLM name and deployment.

## Prepare the Cocoarynth indexes

If resources are already provisioned, start here; reprovisioning is not required to ingest the new documents. Sign in using the attendee identity that has Blob Data Contributor access. Run from the repository root:

```sh
.venv/bin/python infra/create-index-snapshots.py
.venv/bin/python scripts/export-search-index.py
.venv/bin/python scripts/validate-index-snapshots.py
```

On Windows, use `.venv\Scripts\python.exe`. Ingestion uploads eight PDFs under separate prefixes in the `knowledge` container, creates `cocoarynth-documents-index` and `cocoarynth-engineering-practices-index`, and runs Content Understanding with 700-token semantic chunking and 3072-dimensional embeddings. It replaces blobs and records for those two corpora and incurs model charges. It does not remove the old Caldova resources.

Export captures real indexed text and vectors into `data/index-data/`; offline validation checks portability and schema. Review and include those four Cocoarynth snapshot files in the delivery repository. Do not reuse Caldova vectors or fabricate chunk counts. The target serverless preview's live ingestion still requires an Azure rehearsal.

## Snapshot restoration

Snapshot restoration remains enabled by default in both deployment paths. After capturing Cocoarynth snapshots, enable it for the environment and rerun provisioning:

```sh
azd env set RESTORE_INDEX_SNAPSHOTS true
azd provision
```

Restoration replaces records in the two Cocoarynth indexes with precomputed text and vectors; it does not upload PDFs or exercise Content Understanding. Setting `RESTORE_INDEX_SNAPSHOTS=false` skips restoration and does not clear existing indexes. See [infrastructure guidance](infra/README.md#optional-data-tools) for authentication and rebuilding behavior.

Knowledge sources and knowledge bases are left for the lab exercises; neither data setup option creates them.

## Run the notebook

Open [Part 1](src/notebooks/part1-standard-foundry-iq-kb.ipynb) in VS Code, select the root `.venv` as its kernel, and run cells in order. See [source guidance](src/README.md) for what the notebook creates.

## Cleanup

```sh
azd down
```

Confirm resource-group deletion when prompted. Foundry accounts can remain soft-deleted, retaining names or quota. See [cleanup guidance](infra/README.md#cleanup) for the scoped purge script before reusing an environment.