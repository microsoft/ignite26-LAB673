# Safety and idempotency

Read before write. Prefer deterministic names and PUT upserts. Use ETags for concurrent updates. Deletes, resets, resync, upgrades, key rotation, document batch removal, role changes, and network changes require an explicit impact statement. Validate every mutation and retain a redacted prior definition or source-of-truth recreation path.

## Routine validation

Within the requested task's authorized identity, corpus, network and existing
resources, **fewer than 25 test queries in total** need no separate permission
for query/model charges. Count Search, KB and agent test calls, including retries,
across the task; do not split batches to evade the limit. At **25 or more**, obtain
testing/spend approval first, reusing an approval that already covers it.
Bound runtime/output and report usage; explicit user/organization restrictions
still apply. This does not authorize new resources, grants, data movement,
production changes or formal cloud evaluation/judge runs.

A manual run of an existing, idle indexer with unchanged source, configuration
and data boundary needs no extra confirmation. Check status first; do not
interrupt active work or blindly retry an uncertain run. Creating or changing
an automated schedule still requires approval, as do resets/resync, configuration,
permission and network changes. Diagnose and reuse existing authorization before
asking again.

## Scenario cleanup

1. During creation, track exact resource IDs/names, dependencies, and created versus reused ownership, including role assignments and KS `createdResources`. Read back this inventory before teardown; do not infer ownership from names.
2. An explicit request such as "tear down all resources created by this scenario" authorizes cleanup of that verified inventory. Show the exact resources and impact, then proceed without per-resource confirmation. Reuse this authorization at each operation's approval gate; ask only if ownership, scope, or impact is unclear or changes. Never delete reused/shared resources or alter their references under this authorization.
3. Delete owned KBs first. Before deleting a KS, inspect all KB definitions for references; preserve a source referenced by a retained KB unless reference removal is separately approved. Then delete owned KSs using their [delete contract](../operations/data-plane/knowledge-sources/delete.md), which handles generated assets; do not pre-delete their indexes.
4. For independently created pipelines, delete owned indexers before their skillsets, data sources, and indexes; remove authorized references first. Remove only scenario-created role assignments no longer needed. Delegate Storage/model cleanup to their owning skills within the same scope. Delete owned Search services or exclusively owned resource groups last, after checking for new or reused contents.
5. Verify each deletion by GET/404, including KS-generated assets, and confirm retained resources remain intact. Stop on dependency conflicts and re-discover; never widen the deletion scope to force success. Report failures and remaining resources rather than claiming complete cleanup.
