# Health and access

## Quick starts

- "Is my GRZ environment ready to browse?"
- "Why can't I read the GRZ sidecar? Check my descriptor and sign-in."
- "Browse a different GRZ build from this descriptor file."

## Use this path

Use this path when browsing is blocked, the environment is unknown, or the user wants to point at a different build.

## Checks

1. Run `grz-skills-grz_doctor` first, and again after any blocked result. It only reads: versions, `uv`, the Azure sign-in tenant, the descriptor, sidecar health, and reader access. Doctor never signs in.
2. If `ready` is false, fix the first `fail` check using the top-level `next_step`; `warn` does not block.
3. When the MCP tools are unavailable, use `grz-consume doctor --json`. If `grz-consume` is missing, read the [local runtime installation instructions](../../../README.md#install-the-local-runtimes) first. Install or run the shipped `runtime/grz-skills[azure,embed]` package with dependencies from public PyPI, then rerun doctor.

## Choosing the build

- With no flags, tools browse the build this account published last.
- Pass `descriptor_path` (MCP) or `--descriptor` (CLI, or `GRZ_DESCRIPTOR`) to read a different build, plus `--endpoint https://<service>.search.windows.net` with sign-in.
- `--auth entra --tenant-id <tenant>` uses Entra sign-in. Name the tenant to the operator first, and use an identity holding only Search Index Data Reader on the one `grz-*` index.
- `--auth query-key` reads `GRZ_SEARCH_QUERY_KEY`. Never use an admin key.

## Limits

- `status.active` is always `unknown` because consume reads the index named in the descriptor, never the alias.
- Consume is read-only: it blocks every request except document search, count, and lookup. The enforced boundary is the reader role, not the client check.
- `READ_ACCESS_DENIED` names the index; ask the builder for the role on it.

## Return

Report ready or blocked, the first failing check, and the single safe next action.
