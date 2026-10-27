# Infrastructure

This folder provisions the Foundry IQ portion of LAB673 for Skillable and self-paced use. It does not deploy Fabric IQ, Work IQ, Fabric capacity, Entra applications, or sample email.

## Resources

| Resource | Configuration |
| --- | --- |
| Foundry IQ (Azure AI Search) | Serverless in **West Central US**, using `2026-09-01-preview` |
| Search graph identity | User-assigned identity attached to Search for managed knowledge graph builds, with Storage Blob Data Reader and Cognitive Services OpenAI User |
| Blob Storage | Standard LRS account with a private `knowledge` container |
| Foundry | An `AIServices` account and project with managed identities |
| Chat/reasoning | `gpt-5.4`, version `2026-03-05`, Global Standard, capacity 200 |
| Embeddings | `text-embedding-3-large`, version `1`, Global Standard, capacity 30 |
| Content Understanding | Resource defaults mapped to the existing completion and embedding deployments |

Search's region and serverless SKU are fixed in [main.bicep](main.bicep). The `location` parameter controls Foundry and Storage independently. The Skillable flow uses `westus3`, preserving the source lab's Foundry location; Content Understanding is supported there, not in West Central US. Self-paced deployment should also select a Content Understanding-supported region.

The Skillable lifecycle action passes `resourcePrefix="lab673"`, matching the Bicep default used by self-paced deployments. The repository and Desktop folder remain `ignite26-LAB673`. The target Azure policies must allow these resource names; other policy constraints still apply.

The upstream repo recorded insufficient serverless capacity in West Central US on October 5, 2026. Availability and model quota must be checked in the target subscription before delivery. These files deliberately do not fall back to another Search region or a dedicated SKU.

Content Understanding is a capability of the Foundry account, not an additional Azure resource or standalone model deployment. [setup-content-understanding.py](setup-content-understanding.py) configures model-name mappings and the prebuilt completion, mini-completion, and embedding aliases. Both completion aliases reuse the lab LLM, avoiding extra deployments. Individual analyzers must support the selected model; see [model deployment options](https://learn.microsoft.com/azure/ai-services/content-understanding/concepts/models-deployments).

## Skillable setup

Use the existing Windows lab image with Azure CLI and Python available. The optional live-indexing script requires Python 3.11 or newer. The deployment identity needs resource deployment, role-assignment, key-listing, and attendee-directory-read permissions; no Fabric administration, mailbox, or Work IQ admin-consent permissions are needed.

1. Configure [lifecycle_github_repo_download.ps1](lifecycle_github_repo_download.ps1) as the repository download action. It downloads `microsoft/ignite26-LAB673` to `C:\Users\LabUser\Desktop\ignite26-LAB673`, retaining the original Skillable script's `$token` authentication. Keep your existing token setup before this snippet. Re-running the action deletes and replaces the destination folder. For delivery, replace `main` in the ZIP URL with the release commit.
2. Run that deployment action after the download action. Like the original ILL344 action, it writes its embedded background script to `C:\Users\LabUser\Desktop\deploy-background.ps1`, signs in with the lab service principal, resolves the attendee object ID, and launches that generated script. The foreground action exits while provisioning continues; the repository's separate `infra/deploy-background.ps1` is not used by this action.
3. Monitor `C:\Users\LabUser\Desktop\lifecycle-log.txt`. Wait for `=== Background deploy script completed ===` before releasing the environment to the attendee. A background launch alone does not mean setup succeeded.

The background script reuses the foreground Azure CLI login, retrieves Search and Foundry API keys directly with `az rest` and `az cognitiveservices account keys list`, and passes the keys to [setup-knowledge.ps1](setup-knowledge.ps1). That script writes `.env` from the keys and inherited Bicep outputs using PowerShell, prepares the local virtual environment, configures Content Understanding, and restores the four Cocoarynth indexes (`cocoarynth-origins`, `cocoarynth-quality`, `cocoarynth-logistics-retail`, and `cocoarynth-policies`) by default. Skillable setup does not use Python's `AzureCliCredential`; self-paced deployment retains its `azd` credential flow. Knowledge sources and knowledge bases are left for [the first notebook](../src/notebooks/part1-standard-foundry-iq-kb.ipynb).

Snapshots for the four Cocoarynth indexes are in `data/index-data/`. After changing the documents, [rebuild the snapshots](#rebuild-the-index-snapshots) and commit them before releasing a Skillable environment. Missing snapshots stop setup before restoration writes.

The additional [offline ontology, topic/vector, and sitemap snapshots](../data/graph-data/README.md) are separate and are not restored by either deployment path. They include the captured source vectors; restoring them does not require re-embedding that text. The separate [EKG re-ingestion check](../docs/graph-ks-reingestion.md) verified compatible source/vector restoration and native GQL on `magottei-s1m-os`, but that service rejects the existing-index Graph KS preview API. It does not establish Graph KS/NL2GQL readiness for the lab deployment.

Set `$env:RESTORE_INDEX_SNAPSHOTS = "false"` in the lifecycle action before launching the background script only for rebuilding snapshots or a deliberate live-ingestion exercise. Re-running restoration replaces records in the four Cocoarynth indexes with the captured snapshots. Disabling restoration does not delete existing indexes.

## Self-paced deployment

Follow [the self-deployment guide](../deploy_yourself.md). [main.parameters.json](main.parameters.json) supplies azd parameters; [postprovision.sh](hooks/postprovision.sh) and [postprovision.ps1](hooks/postprovision.ps1) perform environment and Content Understanding setup after provisioning.

Both deployment paths install [notebook requirements](../src/notebooks/requirements.txt), which include [infrastructure requirements](requirements.txt) and `ipykernel` for the notebook kernel. The full upstream requirements, agent-framework, Fabric, and OneLake packages are not needed.

## Rebuild the index snapshots

Provisioning restores the four Cocoarynth indexes from the snapshots in `data/index-data/`, without uploading PDFs or running Content Understanding. Rebuild the snapshots only after changing the documents in `data/cocoarynth/`. These tools are for maintainers and are not run automatically:

| Tool | Purpose |
| --- | --- |
| [create-index-snapshots.py](create-index-snapshots.py) | Upload the 55 Cocoarynth PDFs and build Blob data sources, Content Understanding skillsets, embedding skills, indexes, and indexers |
| [export-search-index.py](../scripts/export-search-index.py) | Export portable index definitions and document/vector snapshots |
| [validate-index-snapshots.py](../scripts/validate-index-snapshots.py) | Validate committed snapshots without Azure access |
| [create-knowledge.py](create-knowledge.py) | Restore the four index snapshots (what provisioning runs) |

1. Provision an environment with restoration turned off (`azd env set RESTORE_INDEX_SNAPSHOTS false`, then `azd provision`), or reuse an existing one.
2. Sign in as the attendee identity that has Blob Data Contributor access; the upload tool uses `DefaultAzureCredential` rather than a service principal's management-plane access. From the repository root, run:

   ```sh
   .venv/bin/python infra/create-index-snapshots.py
   .venv/bin/python scripts/export-search-index.py
   .venv/bin/python scripts/validate-index-snapshots.py
   ```

   On Windows, use `.venv\Scripts\python.exe`. The live-indexing tool requires Python 3.11 or newer.
3. Commit the eight files in `data/index-data/`. Chunk counts come from ingestion; don't edit them by hand.
4. To check restoration, run `.venv/bin/python infra/create-knowledge.py`, or `azd env set RESTORE_INDEX_SNAPSHOTS true` and `azd provision`.

Ingestion uploads the PDFs listed in [the corpus manifest](../data/cocoarynth/corpora.json) under one prefix per index in the `knowledge` container, creates `cocoarynth-origins`, `cocoarynth-quality`, `cocoarynth-logistics-retail`, and `cocoarynth-policies`, and runs Content Understanding with 700-token semantic chunking and 3072-dimensional embeddings. It clears and replaces only those four corpora's blobs and index records, and incurs model charges, so run it only against disposable lab resources. The current snapshots were captured on 13 October 2026. Content Understanding can return transient errors; rerunning the affected indexer resolves them.

Restoration replaces records in the four indexes with the snapshot text and vectors. Setting `RESTORE_INDEX_SNAPSHOTS=false` skips restoration and does not clear existing indexes.

How the documents themselves are generated is in [Cocoarynth data guidance](../data/README.md).

## Cleanup

[lifecycle_teardown_cogservices.ps1](lifecycle_teardown_cogservices.ps1) accepts a required `ResourceGroupName` and an optional `ResourcePrefix` (default `lab673`), matching the Skillable deployment action. For resources from earlier `ill344`-prefixed deployments, pass `-ResourcePrefix ill344` instead. It only deletes and purges `<ResourcePrefix>-foundry-*` accounts in the specified group, including their projects and model deployments. It does not enumerate or purge unrelated subscription-wide accounts, and it does not delete Azure ML workspaces. Run it before Skillable removes the resource group if the lab requires immediate model-quota recovery. The Windows image needs the Az PowerShell modules used by this action.

Skillable's resource-group cleanup removes Search and Storage. For self-paced use, `azd down` removes the resource group; Foundry soft-delete may require explicit purge before reusing the same resource names. If a custom `resourcePrefix` is used, pass that same prefix to the cleanup script.

## Source and adaptations

Imported from [ILL344](https://github.com/microsoft/aitour27-ILL344-turning-data-into-agent-ready-knowledge-with-microsoft-iq) at commit `dc74ce12fc9c4d1fc9c49fcd7b0c5cbf482cbcca`:

- Retained snapshot restoration, live-indexing, export, and offline validation tools.
- Adapted the Bicep, Skillable lifecycle, self-paced hooks, and environment setup for LAB673.
- Made Blob Storage unconditional and fixed Search to West Central US serverless.
- Added explicit Content Understanding default-model configuration.
- Scoped Search-to-Foundry managed-identity roles to the Foundry account rather than the subscription.
- Enabled index restoration by default and imported the first notebook with Foundry-only prerequisites and repository-relative asset lookup.
- Excluded Fabric/Work IQ provisioning, email seeding, Fabric JSON, legacy datasets, and the later notebooks.

The corpus is a generated set of Cocoarynth documents split across four indexes. Adaptations retain the existing single-container Blob layout, portable citation fields without image projections, and notebook answer synthesis. See [Cocoarynth data guidance](../data/README.md).

No cloud resources have been provisioned or deployment credentials stored in this repository as part of this import.
