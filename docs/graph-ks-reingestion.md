# Graph re-ingestion and Graph KS verification

**Re-ingestion, captured vectors, and native GQL passed on `magottei-s1m-os`; server-side Graph Knowledge Source (KS) and NL2GQL remain blocked.** The service rejects `2026-11-01-preview`, the API version required by the current existing-index `searchIndexParameters.graphOntology` registration contract. This is not a successful Graph KS test.

The [verification script](../scripts/verify-graph-ks.py) prepares compatible snapshots, safely restores them, and checks the actual serving path. The [run record](../data/graph-data/cocoarynth-ekg-restore-check.json) preserves the preparation plan, restore/readback results, exact service errors, and raw native graph responses.

## What was verified

| Check | Result |
| --- | --- |
| Compatible source, ontology, and graph indexes | Complete readback: 609 evidence records, 288 ontology rows, and 3,938 unchanged assertions |
| Captured source vectors | All 106 vectors, each 3,072-dimensional, are bit-identical at float32 precision; vector self-query ranks first with score `0.99999976` |
| Native GQL | Three known-answer paths passed, including mixed-direction three-hop traversal |
| Evidence joins | Original assertion, chunk, and parent IDs match; explicit source-key lookups return the original text, blob URL, and pointer |
| Server-side provenance hydration | HTTP 400: `Provenance document hydration is not supported for this service.` |
| Existing-index Graph KS / server NL2GQL | HTTP 400: `The version indicated by the api-version query string parameter does not exist.` |

The native paths are batch `PE26-0902` to bean lot `PE25-L11`; case `CASE-2607-18` through shipment and depot stop to `riverbend-bay-4`; and case `CASE-2609-14` through batch and bean lot to exactly farms `el-cedro` and `las-brisas`. These use fixture-derived GQL, not server NL2GQL.

The service is Standard SKU. This run does not establish support on the separately provisioned Serverless lab service. No embeddings were regenerated, no model inference was invoked, and no existing knowledge source or knowledge base was changed.

## Repeat the check

Run from the repository root. Set `$EkgPython` to the Python interpreter in an already prepared, checksum-verified EKG skills runtime; `prepare` requires its official `ekg_core` inline-ontology validator. It does not install packages. This run used Foundry-IQ-Skills commit `a78252c32312fa54ec9bf53da36dc66104f9316b` from [PR 2344752](https://msdata.visualstudio.com/Azure%20Search/_git/Foundry-IQ-Skills/pullrequest/2344752), with EKG wheel SHA-256 `55fc7a91598ebded97bcf36fa79ebbe225dcf74a8f95450c391921c46319cefe`. That is verification provenance, not a replacement for the older bundle-generation provenance.

`prepare` is offline:

```powershell
$Prepared = Join-Path $env:TEMP "lab673-ekg-snapshot"
& $EkgPython .\scripts\verify-graph-ks.py prepare `
  --output $Prepared --prefix lab673-ekg-f7d06ba6
```

For live commands, use an authenticated **isolated Azure CLI profile**, with `AZURE_CONFIG_DIR` and the intended `AZURE_TENANT_ID` set in that shell. The script rejects the shared default profile and does not fall back to API keys or another identity. Confirm the destination, capacity for three indexes, and prefix before restoring; use a different explicit prefix and endpoint for a separate lab destination.

```powershell
& $EkgPython .\scripts\verify-graph-ks.py restore `
  --prepared $Prepared `
  --endpoint https://magottei-s1m-os.search.windows.net `
  --model-source-kb lab673-snapshot-20261013-kb-sol

& $EkgPython .\scripts\verify-graph-ks.py verify `
  --prepared $Prepared `
  --endpoint https://magottei-s1m-os.search.windows.net
```

Run `verify` even when `restore` reports the current capability block; do not join them with `&&`. Each writes its JSON report into `$Prepared`.

| Exit code | Meaning |
| --- | --- |
| `0` | The command completed; a successful `restore` is still `prepared_not_verified`, not a Graph KS pass |
| `1` | A data, schema, authentication, query, or other execution check failed |
| `2` | Prerequisite stages may have passed, but the required Graph KS API is unavailable |

The script creates only absent resources or resumes resources with the exact ownership marker and matching data. It uploads only missing documents, refuses foreign or changed records, and never deletes indexes, changes existing schemas, scales a service, grants roles, or runs managed extraction. A verified rerun uploaded zero documents.

When the required preview becomes available, `restore` can create the prepared Graph KS and a separate KB using the single existing Entra-authenticated model binding explicitly named by `--model-source-kb`. This creation/retrieval branch has **not** been exercised on a supporting service; model access is unverified. It does not copy API keys or grant model permissions. `verify` will then invoke KB retrieval, which can incur model charges.

For a server NL2GQL pass, raw KB activity must show successful execution against the exact Graph KS and graph index, positive graph-row counts, the natural-language query, and server-generated GQL. The script replays that GQL and checks the independent expected entities and original evidence joins. Lexical answers or client-side graph planning cannot satisfy this check.

## Compatibility and scope

Source fields map `chunk_id` to `uid`, `chunk` to `snippet`, `parent_id` to `snippet_parent_id`, `blob_path` to `blob_url`, and captured `text_vector` to `snippet_vector`. Original identifiers, text, metadata, chunk boundaries, and all captured vectors are preserved. The 503 structured records never had captured embeddings and use **empty vector collections**, not nulls, zero vectors, or newly generated embeddings.

Search normalizes typed `object_datetime` values to UTC. Readback compares those values by instant while requiring the original lexical `object` text to remain unchanged.

The Graph KS candidate contains a separately validated flat relationship projection: **39 classes and all 70 object properties**. It excludes 185 datatype properties and subclass reasoning to fit the inline ontology limits. The restored native ontology index is retained as a snapshot; this Graph KS contract instead consumes inline JSON-LD. The full approved business JSON/OWL and all 3,938 assertions remain unchanged. Full-OWL planning, managed extraction, grounding, and the separate topic/sitemap navigation vocabulary are outside this smoke check.

Server provenance hydration is an independent capability. Native graph execution passed using provenance IDs; source resolution is explicitly labeled `client-key-lookup`, never server hydration or a client graph-query fallback.

The original three task-owned GRZ preparation indexes were removed with explicit approval after complete committed snapshots, live readback, and absence of dependencies were verified. Their offline source vectors, topics, sitemap, and historical restore receipt remain intact. The new EKG test indexes are `lab673-ekg-f7d06ba6-sources`, `lab673-ekg-f7d06ba6-ontology`, and `lab673-ekg-f7d06ba6-graph`; no Graph KS or KB was created during this run. Existing lab provisioning remains unchanged.
