# New public-test setup

## Quick starts

- "Plan a new isolated public-test setup for EKG."
- "Set up EKG for a public corpus."

## Use this path

Use this path to create all resources in a new resource group from an empty subscription, in one approval. Only bounded public modes may apply.

New Search services default to Serverless in West US 3 (`westus3`) unless the user selects another region. Check current regional offerings and management API `2026-09-01-preview` read-only; no automatic Dedicated fallback. Serverless has no aliases or outbound private indexer networking. IP allowlists require an explicitly chosen compatible Dedicated SKU. Serverless usage cost is unknown, not zero; provisioning does not prove managed Blob graph extraction.

## Public-test plan

Ask for tenant, subscription, and a short name; default to `--location westus3` unless another region is explicitly requested, and confirm the tenant before sign-in. Run one `ekg-provision plan --location westus3 --public-test --public-test-mode entra_only --public-test-tenant-id <t> --public-test-expires-at <within 72h> --create-resource-group --synthetic-data-only` with:

- `--search-identity-name <uai>`: user-assigned identity for Search.
- `--storage-container <c>`: private Blob container.
- `--embedding-deployment <e> --chat-deployment <c>`: model deployments (defaults `text-embedding-3-small` and `gpt-5-mini`), created after a read-only quota check.
- `--operator-object-id "$(az ad signed-in-user show --query id -o tsv)"`: the operator's four roles; the Search identity gets two.

`ip_allowlist` mode needs exact VPN egress hosts and deny-default firewalls. Neither mode enables trusted-service bypass.

## Public data

For a genuinely public corpus use `--public-data-entra --public-data-only --tenant-id <t> --public-data-expires-at <within 72h> --create-resource-group` instead of all public-test and synthetic flags. Confirm independently that only public documents are in scope; never label real content synthetic. It is Entra-only with no IP rules and no private networking.

## Apply

New public plans bind `arm-429-v1`: selected ARM requests may retry definite
transient HTTP 429 at most five times within 120 seconds per request sequence.
Azure's minimum delay is never shortened; the policy replaces SDK retries,
not stacks with them. LRO polling does not replay the create. Quota/auth/config
errors, arbitrary timeouts and 5xx are not retry candidates. The approval card
distinguishes these bounded request retries from **no automatic workflow replay
or cleanup**. Backoff is cancellable and attempts/exhaustion are reported.
Historical plans keep their exact no-retry policy; reconstruct them with
`--request-retry-policy none`. Recovery inherits its immutable journal policy.

1. Show the card, including the public-only acknowledgement and exact expiry.
2. After `approved <plan-id>`, run `apply` with the same flags plus `--plan-id <id> --confirm-writes`. It checks quota and role-assignment permission first, journals each step, and stops on the first failure.
3. Run `verify`, then hand the same names to the build skill. After a failure, review the journal and re-plan; resume needs `plan-resume` approval. Expiry never deletes resources.

Public-data recovery uses the same flags and the latest stopped `--run-id`, including an incomplete linked continuation. `plan-resume` binds the immutable root and full journal lineage hashes plus freshly validated owned resources, preserving the group and proposing only missing operations. Positive creation receipts remain valid even when a later guard failed; never recreate those resources. Refuse foreign, drifted, ambiguous or disconnected state and stale/competing lineage; an absent uncertain write needs a recorded HTTP429, not an unresolved timeout.

Validity uses stable approved identity, ownership/expiry, desired security, model/capacity and exact container/role invariants. Raw ARM snapshots and ETags remain audit evidence: provider-managed metadata evolution during approved child creation is allowed only while all validated invariants still match. ARM resource IDs compare case-insensitively, not arbitrary URLs or tags. After a new exact approval, `resume-apply --plan-id <new-id> --confirm-writes` rechecks quota, permissions and drift, records a distinct hash-linked journal, and stops without automatic workflow replay or cleanup. Request retries follow the source journal's bound policy. Positive acceptance receipts remain separate from subsequent polling failures; GET 404 after an accepted write is not noncreation proof or permission for another PUT. Every prior journal stays unchanged. Never rerun ordinary `apply`, rename resources or create missing pieces manually.

## Return

State what was planned or applied, the expiry, and the one safe next action. Upload, build, and publish need their own approvals.
