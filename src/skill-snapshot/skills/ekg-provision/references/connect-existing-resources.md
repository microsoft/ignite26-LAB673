# Connect existing resources

## Quick starts

- "Check whether my existing Search, Storage, and OpenAI resources are ready for EKG."
- "Connect EKG to the resources in resource group `<rg>`."

## Use this path

Use this path when the user already has a Search service, a Storage account, and an Azure OpenAI or Foundry account.

## Install

Run `ekg-provision --version`. If missing, show `uv tool install --python 3.12 "<plugin-root>/runtime/ekg-skills[build,consume,provision]"` and wait for the operator. Never self-install; use the approved feed when required. Missing uv: https://docs.astral.sh/uv/getting-started/installation/.

## Flow

1. Confirm the tenant, then `ekg-provision connect --tenant-id <t> --subscription-id <s>` with `--resource-group` plus `--search-name`, `--storage-name`, `--openai-name`, or exact `--search-resource-id`, `--storage-resource-id`, `--openai-resource-id`. Add `--storage-container`, both deployments, `--search-identity-resource-id`, and `--documents` for a throttle estimate when known.
2. `incomplete` returns `candidates`; ask the user to pick and rerun. `blocked` lists failed checks (Free tier, key-only auth, public container, no user-assigned identity); the user fixes those outside EKG. Connect never creates an identity.
3. Review `capacity` (SKU, TPM, quota headroom) and `roles`. OpenAI access is diagnosed from observed DataActions/NotDataActions, not role names. `permission_coverage` is not `effective_access`. Covered custom roles need no duplicate grant; absent/unknown coverage needs authorization diagnosis, not an assumed grant. Keep operator and Search identity, scopes and any explicitly requested grant separate.
4. `needs_setup` returns one `setup_plan` for a missing container, deployment, or proposed roles. Show its card; after `approved <plan-id>`, run `connect-apply` with the same flags plus `--plan-id <id> --confirm-writes`. It re-reads, refuses on drift, stops on first failure, and never retries.
5. `ready` returns `build_binding.build_args`: the exact `ekg-build` target flags. Reuse the observed ARM OpenAI endpoint unchanged; never invent an alias.

## Return

State the connect status, failed checks, and the one safe next action.
