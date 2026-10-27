# Validation

Creation success is not workload success. Read resources back, wait for terminal
status, verify effective configuration and workload outcomes, and test cleanup
only for owned, approved trial resources.

## Lightweight manual verification (default)

For setup, troubleshooting or "a couple of quick checks", run a bounded pilot,
not a Foundry evaluation job. Under the [routine-query allowance](safety-and-idempotency.md#routine-validation),
check known facts with original-document citations, an unanswerable question,
required-source coverage and requested freshness. Use the actual app/runtime
identity; verify differently entitled denial where permissions apply. Preserve
privacy, source provenance and request IDs; report failures and unverified checks.
Do not create datasets, cloud evaluation assets or judges for this branch.

Invoke Hill-Climb only for an explicit benchmark, evaluation or quality-optimization
request. Manual checks are useful authoring/pilot feedback, not benchmark scores,
statistical improvement or production-ready release assurance. Production cutover
and workload-specific acceptance remain separately approved.

## Semantic readback

Compare intended writable/effective configuration, not raw JSON or SDK byte
equality. Normalize documented service defaults and equivalent serializations
only: source definitions may include default properties, and MCP `allowed_tools`
can be a names list or a `tool_names` filter object. Additional filter predicates
are not equivalent. Ignore read-only metadata; do not drop unknown writable fields,
sources, tools, identity/security settings or meaningful ordering to force a match.
ETags, ownership, version pins and approval digests still require exact matching.
