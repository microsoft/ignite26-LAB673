# Status and telemetry

## Use this path

Use this path for environment checks, local journal status, progress, timings, model-usage attribution, and generation protection. Every command here is read-only.

## Commands

- `ekg-build doctor --json`: environment, tenant, descriptor, reader probe, and model checks. Missing inputs report `skip`.
- `ekg-build status --build-journal <absolute-journal> --run-id <journal.run_id> --json`: the exact local managed run. Read `run_id` from that journal; never invent it or use `plan_id` instead.
- `ekg-build progress`: reuse the original binding, source manifest, ontology, `--graph` and journal flags (no apply approval flags). `continuing` at the 120-minute checkpoint is normal; wait for the next run.
- `ekg-build telemetry --build-journal <path>`: local journal timings only. Report service synchronization separately from local steps; if it is missing, run `reconcile` first.
- `ekg-build attribution`: indexer status, skillset, and Azure Monitor metrics for the exact BuildSpec, naming the bottleneck. Extraction parallelism and reasoning effort change the plan ID.
- `ekg-build generations --descriptor <serving descriptor>`: live generations and what protects them.

## Interpretation rules

- A verified journal is history, not a fresh statement that the service is still serving.
- `generations` protects only the descriptors you pass. If the serving set is incomplete, say cleanup advice is incomplete too.
- When extraction needs more than one 2-hour indexer run, plan the full build with `--ingestion-interval PT5M`.
- A managed build needs three free Search index slots. If the service is full, move to retirement.

## Return

Report the exact phase, the source of truth used, any returned uncertainty, and one safe next action. Never expose journal contents, secrets, or document text unless asked.
