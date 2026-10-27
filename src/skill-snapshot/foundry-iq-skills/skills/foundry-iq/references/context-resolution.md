# Context resolution

Discover tenant, subscription, resource group, Search service, endpoint, location, SKU, identity, local-auth state, public-network state, current objects, ETags, quotas, and dependent resource IDs read-only. Keep demos in a dedicated tagged resource group. Stop on tenant/subscription mismatch or an unresolved ownership boundary.

## Script paths

Set `$loadedSkillPath` to the absolute path of the loaded `SKILL.md`, not an
assumed checkout or current directory. Resolve it before invoking a packaged
helper; stop if the loaded file is unavailable:

```powershell
$skillRoot = Split-Path -Parent (Resolve-Path -LiteralPath $loadedSkillPath -ErrorAction Stop).Path
$snapshotScript = Join-Path $skillRoot 'scripts\snapshot_diagnostics.py'
```

Pipe only the response JSON to `python $snapshotScript` with the selected kind
and a non-sensitive label. Other helpers use `Join-Path $skillRoot` with their
packaged path under `scripts`.

For shell-neutral examples, replace `<helper>` with the absolute packaged script
path resolved from that same loaded skill, not the current working directory.

## Retrieval setup decisions

Recommend from discovered evidence; ask when confidence is low.

| Decision | Guidance |
|---|---|
| Extraction | Start with basic text extraction. Choose Content Understanding Standard when representative diagrams, tables or layouts need richer extraction. |
| Architecture | Keep small one-off context local. Use classic Search for bounded lookup or custom indexing/ranking; prefer a KB for managed ingestion, source selection, multi-search/synthesis or agentic citations. A KB runs on a Search service. |
| Retrieval | Prefer hybrid keyword + vector retrieval for better coverage; choose keyword-only or vector-only when the data type calls for it. Verify index/model support and include embedding costs in approval. |
| Reuse | Prefer compatible existing services, sources, KBs and pipelines; provision missing resources with [service approval](service-provisioning.md). |

Customer goals are sufficient inputs. Inspect size, freshness, permissions and
representative questions before writes. For document assistants, prepare content
through the File/Blob scenario, then connect the same KB to the agent.

KS -> KB: verify readiness, then [compose](../operations/data-plane/knowledge-bases/create-or-update.md)
and [retrieve](../operations/data-plane/knowledge-retrieval/retrieve.md).
For a single operation, use the [catalog](operation-catalog.yaml) and its
source-type guide.
