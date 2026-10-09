# Infrastructure

This folder provisions the Foundry IQ portion of LAB673 for Skillable and self-paced use. It does not deploy Fabric IQ, Work IQ, Fabric capacity, Entra applications, or sample email.

## Resources

| Resource | Configuration |
| --- | --- |
| Foundry IQ (Azure AI Search) | Serverless in **West Central US**, using `2026-09-01-preview` |
| Blob Storage | Standard LRS account with a private `knowledge` container |
| Foundry | An `AIServices` account and project with managed identities |
| Chat/reasoning | `gpt-5.4`, version `2026-03-05`, Global Standard, capacity 50 |
| Embeddings | `text-embedding-3-large`, version `1`, Global Standard, capacity 30 |
| Content Understanding | Resource defaults mapped to the existing completion and embedding deployments |

Search's region and serverless SKU are fixed in [main.bicep](main.bicep). The `location` parameter controls Foundry and Storage independently. The Skillable flow uses `westus3`, preserving the source lab's Foundry location; Content Understanding is supported there, not in West Central US. Self-paced deployment should also select a Content Understanding-supported region.

The upstream repo recorded insufficient serverless capacity in West Central US on October 5, 2026. Availability and model quota must be checked in the target subscription before delivery. These files deliberately do not fall back to another Search region or a dedicated SKU.

Content Understanding is a capability of the Foundry account, not an additional Azure resource or standalone model deployment. [setup-content-understanding.py](setup-content-understanding.py) configures model-name mappings and the prebuilt completion, mini-completion, and embedding aliases. Both completion aliases reuse the lab LLM, avoiding extra deployments. Individual analyzers must support the selected model; see [model deployment options](https://learn.microsoft.com/azure/ai-services/content-understanding/concepts/models-deployments).

## Skillable setup

Use the existing Windows lab image with Azure CLI and Python available. The optional live-indexing script requires Python 3.11 or newer. The deployment identity needs resource deployment, role-assignment, key-listing, and attendee-directory-read permissions; no Fabric administration, mailbox, or Work IQ admin-consent permissions are needed.

1. Configure [lifecycle_github_repo_download.ps1](lifecycle_github_repo_download.ps1) as the repository download action. It downloads `microsoft/ignite26-LAB673` to `C:\Users\LabUser\Desktop\ignite26-LAB673`. Set `GITHUB_TOKEN` through Skillable secret configuration only if the repository requires authentication. Pin `$revision` to the release commit for delivery.
2. In [lifecycle_bicep_deployment.ps1](lifecycle_bicep_deployment.ps1), replace `REPLACE_WITH_SKILLABLE_RESOURCE_GROUP_NAME` with the resource-group name in the lab definition. Confirm that the `CloudSubscription` and `CloudPortalCredential(User1)` tokens match the lab. These are Skillable substitution tokens, not PowerShell environment variables.
3. Run that deployment action after the download action. It signs in with the lab service principal, resolves the attendee object ID, and launches [deploy-background.ps1](deploy-background.ps1). The foreground action exits while provisioning continues.
4. Monitor `C:\Users\LabUser\Desktop\lifecycle-log.txt`. Wait for `Lab setup completed successfully.` before releasing the environment to the attendee. A background launch alone does not mean setup succeeded.

The background script reuses the foreground Azure CLI login and passes Bicep outputs to [setup-knowledge.ps1](setup-knowledge.ps1). That script prepares the local virtual environment, writes `.env`, configures Content Understanding, and restores `cocoarynth-documents-index` and `cocoarynth-engineering-practices-index` by default. Knowledge sources and knowledge bases are left for [the first notebook](../src/notebooks/part1-standard-foundry-iq-kb.ipynb).

Cocoarynth snapshots have not been captured yet. Complete [the one-time ingestion and export](../deploy_yourself.md#prepare-the-cocoarynth-indexes) and include the new snapshot files before releasing a Skillable environment. Missing snapshots stop setup before restoration writes; the old Caldova snapshots are not a fallback.

Set `$env:RESTORE_INDEX_SNAPSHOTS = "false"` in the lifecycle action before launching the background script only for initial snapshot capture or a deliberate live-ingestion exercise. Re-running restoration replaces records in the two Cocoarynth indexes with the captured snapshots. Disabling restoration does not delete existing indexes.

## Self-paced deployment

Follow [the self-deployment guide](../deploy_yourself.md). [main.parameters.json](main.parameters.json) supplies azd parameters; [postprovision.sh](hooks/postprovision.sh) and [postprovision.ps1](hooks/postprovision.ps1) perform environment and Content Understanding setup after provisioning.

Both deployment paths install [notebook requirements](../src/notebooks/requirements.txt), which include [infrastructure requirements](requirements.txt) and `ipykernel` for the notebook kernel. The full upstream requirements, agent-framework, Fabric, and OneLake packages are not needed.

## Optional data tools

Snapshot restoration runs during provisioning by default. The other data tools are included for maintainers and are not automatically run:

| Tool | Purpose |
| --- | --- |
| [create-knowledge.py](create-knowledge.py) | Restore the two Cocoarynth index snapshots, bypassing Blob ingestion and Content Understanding |
| [create-index-snapshots.py](create-index-snapshots.py) | Upload the eight Cocoarynth PDFs and build Blob data sources, Content Understanding skillsets, embedding skills, indexes, and indexers |
| [export-search-index.py](../scripts/export-search-index.py) | Export portable index definitions and document/vector snapshots |
| [validate-index-snapshots.py](../scripts/validate-index-snapshots.py) | Validate committed snapshots without Azure access |

After provisioning, use the virtual environment created by setup. On macOS/Linux, these commands run from the repository root:

```sh
.venv/bin/python infra/create-index-snapshots.py
.venv/bin/python scripts/export-search-index.py
.venv/bin/python scripts/validate-index-snapshots.py
```

On the Windows lab VM, use `.venv\Scripts\python.exe` instead. The upload tool authenticates to Blob Storage with `DefaultAzureCredential`; sign in as the attendee who received Blob Data Contributor, rather than relying on a different service principal's management-plane access.

The live-indexing tool clears only the selected Cocoarynth corpus prefixes and their index records before rebuilding them. Run it only against disposable lab resources. Its compatibility with the target serverless preview and Content Understanding configuration still needs an Azure deployment rehearsal. Snapshot restoration is a separate alternative, not proof that live ingestion works.

The current PDF manifest and source revision are in [Cocoarynth data guidance](../data/README.md). The legacy `sync-caldova-data.py` script and old Caldova assets remain unchanged for reference and are not part of the active lab flow.

## Cleanup

[lifecycle_teardown_cogservices.ps1](lifecycle_teardown_cogservices.ps1) accepts a required `ResourceGroupName` and only deletes and purges `lab673-foundry-*` accounts in that group, including their projects and model deployments. It does not enumerate or purge unrelated subscription-wide accounts, and it does not delete Azure ML workspaces. Run it before Skillable removes the resource group if the lab requires immediate model-quota recovery. The Windows image needs the Az PowerShell modules used by this action.

Skillable's resource-group cleanup removes Search and Storage. For self-paced use, `azd down` removes the resource group; Foundry soft-delete may require explicit purge before reusing the same resource names. If a custom `resourcePrefix` is used, review the cleanup name filter before running it.

## Source and adaptations

Imported from [ILL344](https://github.com/microsoft/aitour27-ILL344-turning-data-into-agent-ready-knowledge-with-microsoft-iq) at commit `dc74ce12fc9c4d1fc9c49fcd7b0c5cbf482cbcca`:

- Retained snapshot restoration, live-indexing, corpus synchronization, export, and offline validation tools with their relevant PDFs and snapshots.
- Adapted the Bicep, Skillable lifecycle, self-paced hooks, and environment setup for LAB673.
- Made Blob Storage unconditional and fixed Search to West Central US serverless.
- Added explicit Content Understanding default-model configuration.
- Scoped Search-to-Foundry managed-identity roles to the Foundry account rather than the subscription.
- Enabled index restoration by default and imported the first notebook with Foundry-only prerequisites and repository-relative asset lookup.
- Excluded Fabric/Work IQ provisioning, email seeding, Fabric JSON, legacy datasets, and the later notebooks.

The active corpus and two indexed sources now follow [the Cocoarynth developer KB lab](https://github.com/pamelas-organization/developer-kb-for-github-copilot) at revision `1cdf35934462a46752da542f0c856ac82b475075`. Adaptations retain the existing single-container Blob layout, portable citation fields without image projections, and notebook answer synthesis. See [provenance](../data/cocoarynth/provenance.json).

No cloud resources have been provisioned or deployment credentials stored in this repository as part of this import.
