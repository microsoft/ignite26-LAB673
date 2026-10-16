# New public-test setup

## Quick starts

- "Plan a new isolated public-test setup for EKG."
- "Set up EKG for a public corpus."

## Use this path

Use this path to create all resources in a new resource group from an empty subscription, in one approval. Only bounded public modes may apply.

## Public-test plan

Ask for tenant, subscription, region, and a short name; confirm the tenant before sign-in. Run one `ekg-provision plan --public-test --public-test-mode entra_only --public-test-tenant-id <t> --public-test-expires-at <within 72h> --create-resource-group --synthetic-data-only` with:

- `--search-identity-name <uai>`: user-assigned identity for Search.
- `--storage-container <c>`: private Blob container.
- `--embedding-deployment <e> --chat-deployment <c>`: model deployments (defaults `text-embedding-3-small` and `gpt-5-mini`), created after a read-only quota check.
- `--operator-object-id "$(az ad signed-in-user show --query id -o tsv)"`: the operator's four roles; the Search identity gets two.

`ip_allowlist` mode needs exact VPN egress hosts and deny-default firewalls. Neither mode enables trusted-service bypass.

## Public data

For a genuinely public corpus use `--public-data-entra --public-data-only --tenant-id <t> --public-data-expires-at <within 72h> --create-resource-group` instead of all public-test and synthetic flags. Confirm independently that only public documents are in scope; never label real content synthetic. It is Entra-only with no IP rules and no private networking.

## Apply

1. Show the card, including the public-only acknowledgement and exact expiry.
2. After `approved <plan-id>`, run `apply` with the same flags plus `--plan-id <id> --confirm-writes`. It checks quota and role-assignment permission first, journals each step, and stops on the first failure.
3. Run `verify`, then hand the same names to the build skill. After a failure, review the journal and re-plan; resume needs `plan-resume` approval. Expiry never deletes resources.

## Return

State what was planned or applied, the expiry, and the one safe next action. Upload, build, and publish need their own approvals.
