# Publish and readers

## Quick starts

- "Publish the verified GRZ generation."
- "Which readers will lose access if I publish this generation?"
- "Add this principal as a reader on the next build and re-plan."

## Use this path

Use this path after `grz-build verify` passed and the operator wants the generation to become the current build.

## Publish

1. Confirm `verify` succeeded for the exact generation ID. If it did not, return to the plan-and-apply path.
2. Show the approval card that `verify` returned verbatim and wait for the separate reply `approved <generation-id>`.
3. Run `grz-build publish --generation-id <id> --approve-cutover`. Publish moves the `grz-{dataset}-{vector-field}-active` alias and records the generation as this account's current build, so browsing needs no paths afterward.
4. Tell the operator they can now start Copilot CLI and ask what topics the corpus covers.

## Reader access

Search roles scoped to one index do not follow the alias. `plan` lists the Search Index Data Reader grants made directly on the current index under `reader_grants`, `apply` grants each one on the new index before upload, and `publish` compares both indexes.

- If `publish` stops with `READERS_MISSING`, say who would lose access. Do not drop readers on your own; re-run `apply` with the same plan, or re-plan with `--drop-reader <principal-object-id>` only when the operator asks.
- Use `--reader <principal-object-id>` only for a principal the operator names.
- `READER_GRANTS_FORBIDDEN` means the build identity cannot read or write role assignments on the Search service; report it and stop.
- Grants inherited from the service or resource group are not copied.

## Return

Report the generation ID, whether publish ran, the alias it now binds, any reader gaps, and the single safe next action. Never retry a publish whose outcome is unknown; use the reconcile path instead.
