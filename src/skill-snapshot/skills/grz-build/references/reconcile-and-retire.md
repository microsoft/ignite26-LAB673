# Reconcile and retire

## Quick starts

- "The apply timed out; what landed in the index?"
- "List my GRZ generations and tell me which ones are safe to retire."
- "Plan retiring the superseded generation `<index>`."

## Use this path

Use this path after a failed or uncertain write, or to free a Search index slot by retiring an old generation.

## Reconcile

1. A write that times out or returns an unclear error is journaled as ambiguous and never retried. The next `apply` stops with `RECONCILE_REQUIRED`.
2. Run the read-only `grz-build reconcile --plan-id <id>` and show what landed and what is missing.
3. Resume with `apply ... --resume-after-reconcile` only after the operator explicitly says yes to that resume. It uploads only the missing documents.

## Retire

1. Run the read-only `grz-build generations`. Each `grz-{dataset}-` index has a role: `alias-bound`, `superseded`, `source`, or `unrecognized`. Only `superseded` qualifies; never retire the published generation or the source.
2. Run `grz-build plan-retire --index <index>` and show its approval card verbatim, including the document count and reader grants.
3. After `approved <plan-id>`, run `grz-build retire --plan-id <id> --confirm-writes`. It refuses if the alias target, generation ID, document count, or reader grants changed since the plan, then sends one delete, confirms the index is gone, and removes the listed reader grants.
4. A failed or unclear delete is journaled and not retried. Retiring is irreversible: going back means rebuilding that generation.

## Return

Report what was found or removed, the exact plan ID used, and the single safe next action. Never propose deleting an `alias-bound`, `source`, or `unrecognized` index.
