# Health and access

## Quick starts

- "Is my GRZ environment ready to browse?"
- "Why can't I read the GRZ sidecar? Check my descriptor and sign-in."
- "Browse a different GRZ build from this descriptor file."

## Use this path

Use this path when browsing is blocked, the environment is unknown, or the user wants to point at a different build.

## Checks

1. Follow [runtime setup](../../graph-guide/references/install-and-checks.md#plugin-and-clis): explicit `setup grz`, then `run grz grz-consume --help`. Retain the launcher prefix on later commands; warm run never installs.
2. Run `grz-consume --json doctor`, and again after any blocked result. It only reads: versions, `uv`, the Azure sign-in tenant, the descriptor, sidecar health, and reader access. Doctor never signs in.
3. If `result.ready` is false, fix the first `fail` check using `result.next_step`; `warn` does not block.

## Choosing the build

- With no flags, the CLI browses the build this account published last.
- Pass `--descriptor` (or `GRZ_DESCRIPTOR`) before the subcommand to read a different build, plus either `--documents sidecar.json` for an offline file or `--endpoint https://<service>.search.windows.net` with sign-in.
- `--auth entra --tenant-id <tenant>` uses Entra sign-in. Name the tenant to the operator first, and use an identity holding only Search Index Data Reader on the one `grz-*` index.
- `--auth query-key` reads `GRZ_SEARCH_QUERY_KEY`. Never use an admin key.

## Limits

- `status.active` is always `unknown`: consume reads the descriptor's physical index, never an alias. Local publication does not retarget already-bound servers or other machines.
- Consume is read-only: it blocks every request except document search, count, and lookup. The enforced boundary is the reader role, not the client check.
- `READ_ACCESS_DENIED` names the index; ask the builder for the role on it.

## Return

Report ready or blocked, the first failing check, and the single safe next action.
