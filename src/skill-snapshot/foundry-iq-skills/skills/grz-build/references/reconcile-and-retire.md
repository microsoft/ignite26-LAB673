# Reconcile and retire

## Quick starts

- "The apply timed out; what landed in the index?"
- "List my GRZ generations and tell me which ones are safe to retire."
- "Plan retiring my incomplete staging index `<index>`."

## Use this path

Use this path after a failed or uncertain write, or to retire journal-owned, unexposed incomplete staging. Completed generations remain retained.

For [captured input](captured-input.md), bind `status`, `generations` and
`plan-retire` to the exact saved owner Build plan with `--plan-id` or
`--plan-file`. Retire/reconcile use their exact saved operation plan, including
its captured owner authority. Never invent freeze evidence, reopen the mutable
original or select a capture implicitly. Retain the capture and protected
compatibility copy even after incomplete staging is retired.

## Reconcile

1. A write that times out or returns an unclear error is journaled as ambiguous and never retried. The next `apply` stops with `RECONCILE_REQUIRED`.
2. Run the read-only `grz-build reconcile --plan-id <id>` and show what landed and what is missing.
3. Resume with `apply ... --resume-after-reconcile` only after the operator explicitly says yes to that resume. It uploads only the missing documents.

## Retire

1. Run the read-only `grz-build generations`. Only `incomplete-owned` qualifies. `local-current`, `retained`, `source`, `unknown`, `unrecognized`, `unresolved`, `retiring`, and `protected` do not.
2. Run `grz-build plan-retire --index <index>` and show its approval card verbatim, including the document count and reader grants.
3. After `approved <plan-id>`, run `grz-build retire --plan-id <id> --confirm-writes`. Ownership, schema/content digests, generation, count and grants must still match; manifest-bearing or exposed indexes block. It sends one delete, verifies absence and removes only the planned grants.
4. A failed or unclear delete is journaled and not retried. Retiring is irreversible: going back means rebuilding that generation.

## Return

Report what was found or removed and the safe next action. Never propose deleting completed, exposed, source, unknown or unrecognized indexes. No alias inspection or mutation is used.
