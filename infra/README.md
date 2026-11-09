# Infrastructure

This folder provisions the Foundry IQ portion of LAB673 for Skillable and self-paced use. It does not deploy Fabric IQ, Work IQ, Fabric capacity, Entra applications, or sample email.

## Resources

| Resource | Configuration |
| --- | --- |
| Foundry IQ (Azure AI Search) | **West Central US**, serverless by default (`searchSkuName`), with paid `standard` Knowledge Retrieval, using `2026-09-01-preview` |
| Search graph identity | Optional (`createSearchGraphIdentity`, off by default; set `CREATE_SEARCH_GRAPH_IDENTITY=true` with azd). A user-assigned identity attached to Search for managed knowledge graph builds, with Storage Blob Data Reader and Cognitive Services OpenAI User. The lab restores graphs from snapshots and doesn't need it. |
| Blob Storage | Standard LRS account with a private `knowledge` container |
| Foundry | An `AIServices` account and project with managed identities |
| Chat/reasoning | `gpt-6-luna`, version `2026-09-22`, Global Standard, capacity 200 |
| Embeddings | `text-embedding-3-large`, version `1`, Global Standard, capacity 30 |
| Content Understanding | Resource defaults mapped to the existing completion and embedding deployments |

Search's region is fixed in [main.bicep](main.bicep); its SKU comes from the `searchSkuName` parameter. The `location` parameter controls Foundry and Storage independently. The Skillable flow uses `westus3`, preserving the source lab's Foundry location; Content Understanding is supported there, not in West Central US. Self-paced deployment should also select a Content Understanding-supported region.

The Skillable lifecycle action passes `resourcePrefix="lab673"`, matching the Bicep default used by self-paced deployments. The repository and Desktop folder remain `ignite26-LAB673`. The target Azure policies must allow these resource names; other policy constraints still apply.

`searchSkuName` defaults to `serverless`. The template enables the paid `standard` Knowledge Retrieval plan for every SKU because Microsoft Retriever 1 has no free tier. This plan is independent of the Search SKU; it does not change the SKU to Standard (S1). The November ontology private-preview requirement still applies. To choose a dedicated SKU, use `azd env set AZURE_SEARCH_SKU standard` or `searchSkuName="standard"` in the Skillable deployment parameters. Search capacity and model quota must be checked in the target subscription before delivery. These files deliberately do not fall back to another Search region.

Content Understanding is a capability of the Foundry account, not an additional Azure resource or standalone model deployment. [setup-content-understanding.py](setup-content-understanding.py) configures model-name mappings and the prebuilt completion, mini-completion, and embedding aliases. Both completion aliases reuse the lab LLM, avoiding extra deployments. Individual analyzers must support the selected model; see [model deployment options](https://learn.microsoft.com/azure/ai-services/content-understanding/concepts/models-deployments).

## Skillable setup

Use the existing Windows lab image with Azure CLI and Python available. The optional live-indexing script requires Python 3.11 or newer. The deployment identity needs resource deployment, role-assignment, key-listing, and attendee-directory-read permissions; no Fabric administration, mailbox, or Work IQ admin-consent permissions are needed.

1. Configure [lifecycle_github_repo_download.ps1](lifecycle_github_repo_download.ps1) as the repository download action. It downloads `microsoft/ignite26-LAB673` to `C:\Users\LabUser\Desktop\ignite26-LAB673`, retaining the original Skillable script's `$token` authentication. Keep your existing token setup before this snippet. Re-running the action deletes and replaces the destination folder. For delivery, replace `main` in the ZIP URL with the release commit.
2. Run that deployment action after the download action. Like the original ILL344 action, it writes its embedded background script to `C:\Users\LabUser\Desktop\deploy-background.ps1`, signs in with the lab service principal, resolves the attendee object ID, and launches that generated script. The foreground action exits while provisioning continues; the repository's separate `infra/deploy-background.ps1` is not used by this action.
3. Monitor `C:\Users\LabUser\Desktop\lifecycle-log.txt`. Wait for `=== Background deploy script completed ===` before releasing the environment to the attendee. A background launch alone does not mean setup succeeded.

The background script reuses the foreground Azure CLI login, retrieves Search and Foundry API keys directly with `az rest` and `az cognitiveservices account keys list`, and passes the keys to [setup-knowledge.ps1](setup-knowledge.ps1). That script writes `.env` from the keys and inherited Bicep outputs using PowerShell, prepares the local virtual environment, configures Content Understanding, and restores six indexes by default:

| Index | Role |
| --- | --- |
| `cocoarynth-topics` | Canonical TopicGraph edge-list facts for eight named topics, four root links, four child links, proportions, and six leaf vectors |
| `cocoarynth-chunks` | 106 chunks from 55 PDFs, with embeddings and a `domain` field for the four original document folders; the business graph's provenance index and the topic centroid search's source |
| `cocoarynth-graph` | Business triples extracted from those PDF chunks under the checked-in OWL schema |
| `cocoarynth-production`, `cocoarynth-sales`, `cocoarynth-policies` | The same chunks grouped by `domain` for Part 1's document knowledge sources: production is origins plus quality (64), sales is logistics-retail (32), and policies (10) |

The bundle holds snapshots for the first three indexes. The restore script
builds the three document-group indexes from the `cocoarynth-chunks` snapshot, so
they share its chunk IDs and embeddings.

Setup creates `cocoarynth-graph-knowledge-source` and `cocoarynth-topics-knowledge-source` with inline
ontologies from the OWL files. The Search service must have the November
ontology private preview, including native GQL and inline-ontology knowledge
sources. The Bicep template does not grant that access. Skillable setup does
not use Python's `AzureCliCredential`; self-paced deployment retains its `azd`
credential flow. The [lab notebooks](../src/notebooks/) create the three
document knowledge sources and the knowledge bases.

The active snapshots are in `data/graph-data/`. Missing artifacts, invalid
checksums, or PDF evidence mismatches stop setup before restoration writes.
Re-running setup creates missing resources and verifies existing ones; it does
not replace an earlier dataset. Use a fresh approved lab service or an explicit
prefix for a separate restoration when existing names contain different data.

Set `$env:RESTORE_INDEX_SNAPSHOTS = "false"` in the lifecycle action before
launching the background script only for a deliberate maintainer capture
exercise. Disabling restoration does not delete existing indexes.

## Self-paced deployment

Follow [the self-deployment guide](../deploy_yourself.md). [main.parameters.json](main.parameters.json) supplies azd parameters; [postprovision.sh](hooks/postprovision.sh) and [postprovision.ps1](hooks/postprovision.ps1) perform environment and Content Understanding setup after provisioning.

Both deployment paths call [setup-venv.py](setup-venv.py) to create or reuse the root `.venv` and install [notebook requirements](../src/notebooks/requirements.txt). These include the pinned alpha Search SDK from [infrastructure requirements](requirements.txt) and `ipykernel` for the notebook kernel. The notebooks do not install packages themselves. The full upstream requirements, agent-framework, Fabric, and OneLake packages are not needed.

To prepare only the local Python environment without provisioning Azure resources, run this from the repository root:

```powershell
python .\infra\setup-venv.py
```

## Rebuild the index snapshots

Provisioning restores the three-index bundle without uploading PDFs, running
Content Understanding, or making extraction/naming model calls. Rebuild the
bundle only after changing the PDFs in `data/cocoarynth/`. The original
four-domain capture tools remain available for maintainers in a separate,
disposable capture environment; they do not produce the complete three-index
bundle automatically:

| Tool | Purpose |
| --- | --- |
| [create-index-snapshots.py](create-index-snapshots.py) | Upload the 55 Cocoarynth PDFs and build Blob data sources, Content Understanding skillsets, embedding skills, indexes, and indexers |
| [export-search-index.py](../scripts/export-search-index.py) | Export portable index definitions and document/vector snapshots |
| [validate-index-snapshots.py](../scripts/validate-index-snapshots.py) | Validate committed snapshots without Azure access |
| [create-knowledge.py](create-knowledge.py) | Load `.env` and ensure the three-index bundle and both graph-enabled knowledge sources (what provisioning runs) |
| [restore-graph-indexes.py](restore-graph-indexes.py) | Validate, restore, or read back the active three-index bundle and OWL bindings |

1. Provision an environment with restoration turned off (`azd env set RESTORE_INDEX_SNAPSHOTS false`, then `azd provision`), or reuse an existing one.
2. Sign in as the attendee identity that has Blob Data Contributor access; the upload tool uses `DefaultAzureCredential` rather than a service principal's management-plane access. From the repository root, run:

   ```sh
   .venv/bin/python infra/create-index-snapshots.py
   .venv/bin/python scripts/export-search-index.py
   .venv/bin/python scripts/validate-index-snapshots.py
   ```

   On Windows, use `.venv\Scripts\python.exe`. The live-indexing tool requires Python 3.11 or newer.
3. Retain the eight capture files in `data/index-data/`. Chunk counts come from ingestion; don't edit them by hand.
4. Rebuild `cocoarynth-chunks` from the PDF chunk captures, preserving provenance and adding the document-group `domain`. Propose the business OWL from PDF text, then extract ontology-constrained triples with exact chunk evidence. Do not feed `world/*.json` to either step.
5. Recompute the topic hierarchy when the corpus changes. Export the plugin's canonical `topicgraph-release-v1` edge-list schema and documents into `cocoarynth-topics`, making `object_vector` retrievable as the publisher does. Roots are level 0; only leaves store centroids. Do not add legacy `kind`/membership/manifest rows or reuse an old native generation identity for changed inputs. The current lab snapshot is a documented format adaptation of its previous capture, not a new native build.
6. Capture the three definitions and record sets, both OWL files, and extraction provenance in `data/graph-data/`. Update `manifest.json` to match their LF-normalized byte counts and SHA-256 checksums. Run `python .\infra\restore-graph-indexes.py --validate-only` before committing a replacement bundle.
7. Against the intended preview-enabled lab service, run `.venv\Scripts\python.exe infra\create-knowledge.py`. Existing destinations with different data are rejected rather than overwritten.

Ingestion uploads the PDFs listed in [the corpus manifest](../data/cocoarynth/corpora.json) under one prefix per index in the `knowledge` container, creates `cocoarynth-origins`, `cocoarynth-quality`, `cocoarynth-logistics-retail`, and `cocoarynth-policies`, and runs Content Understanding with 700-token semantic chunking and 3072-dimensional embeddings. It clears and replaces only those four corpora's blobs and index records, and incurs model charges, so run it only against disposable lab resources. The current snapshots were captured on 13 October 2026. Content Understanding can return transient errors; rerunning the affected indexer resolves them.

Those four ingestion indexes are capture inputs, not the attendee layout.
The active restore manifest contains only the chunk, topic, and business graph
indexes. The current model-generated ontology, extraction, and naming receipts
are summarized in [the provenance ledger](../data/graph-data/pdf-extraction-provenance.json);
they are not represented as a managed extraction run or a native ontology approval.
Setting `RESTORE_INDEX_SNAPSHOTS=false` skips restoration and does not clear
existing indexes.

How the documents themselves are generated is in [Cocoarynth data guidance](../data/README.md).

## Restore graph snapshots (private preview)

[restore-graph-indexes.py](restore-graph-indexes.py) restores the three active
indexes in [the inventory](../data/graph-data/README.md), plus both
graph-enabled knowledge sources. This is the same loader used by default lab
setup, not an optional seven-index add-on.
[requirements-graph.txt](requirements-graph.txt) includes the same November
SDK pin as the infrastructure and notebooks.

The command uses Search API `2026-11-01-preview` for every operation. The
destination must support native graph queries and the private inline-ontology
feature. Set `AZURE_SEARCH_ADMIN_KEY` for that service and
`AZURE_OPENAI_ENDPOINT` for its existing Foundry embedding resource, then pass
the Search HTTPS root explicitly. The command does not load `.env`.
`--embedding-endpoint` and `--embedding-deployment` can supply the query
vectorizer binding explicitly; the recorded model remains
`text-embedding-3-large`. Vectorizers use the Search service's existing managed
identity permissions, not a key stored in the snapshots.

From the repository root:

```powershell
python .\infra\restore-graph-indexes.py --validate-only
python .\infra\restore-graph-indexes.py --endpoint "https://<search-service>.search.windows.net"
```

Offline validation requires only Python, with no SDK installation or Azure
access. The second command leaves the six indexes and two graph-enabled
knowledge sources available for use. By default, all destination names must be
absent. Add `--ensure` to create missing resources and verify matching existing
ones, or `--verify-only` to check a complete restoration without writes.
Existing resources are never overwritten.

For a temporary end-to-end check, add `--prefix <unique-prefix> --cleanup`. Cleanup removes only resources marked as owned by that run and uses conditional ETag checks. A prefix changes physical index bindings, not document IDs, logical graph names, or generation identities.

The command verifies index schemas, every document field and stored float32
vector, vector lookup, and three known-answer business traversals with
provenance. It also checks the canonical topic forest, coverage and proportions,
and executes `HasRootCommunity` and `HasSubCommunity` GQL traversals.
Topic counts and capture provenance live in the separate restore manifest,
not an embedded topic-index manifest. The topic index stores no PDF nodes or
membership edges; the notebook and explorer retrieve nearest source chunks by
centroid. Both knowledge
sources are always created or verified with inline JSON-LD converted from the
checked-in OWL files; `--graph-ks` remains a compatibility flag.
Index restoration uses the Python SDK; REST is limited to native GQL and
private knowledge-source creation through the SDK's transport. No indexer,
embedding generation, or model inference runs during restoration. Knowledge-base
graph-search activity is exercised separately in notebooks 2 and 3.

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

The generated Cocoarynth documents retain four source groups, now served from
one chunk index alongside the topic and business graph indexes. Adaptations
retain the existing single-container Blob layout, portable citation fields
without image projections, and notebook answer synthesis. See
[Cocoarynth data guidance](../data/README.md).

No cloud resources have been provisioned or deployment credentials stored in this repository as part of this import.
