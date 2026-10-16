# Capacity, RBAC, smoke

## Quick starts

- "Review TPM quota, RBAC, and the smoke plan for this environment."
- "Raise the chat deployment capacity."

## Use this path

Use this path for model quota and capacity, scoped role assignments, the synthetic smoke test, and cleanup evidence.

## Capacity

1. `ekg-provision quota` (read-only) reads regional usage and the model catalog with the same deployment flags.
2. `ekg-provision plan-capacity --capacity-deployment <name> --capacity <K>` shows current and desired capacity (thousands of tokens per minute), quota headroom, and the plan ID. Only SKU capacity changes; PTU is out of scope.
3. After `approved <plan-id>`, run `capacity-update` with the same flags plus `--plan-id <id> --confirm-writes`. It refuses on drift or insufficient quota and verifies by fresh read. Above the quota limit, a quota request comes first.

## RBAC

1. `plan-rbac` is offline; `rbac-check` is read-only and checks the active tenant, subscription, and object ID.
2. After approval, `rbac-grant` grants only four exact scoped data roles. Inherited access remains possible.

## Smoke test

`plan-smoke` then `smoke-run` tests one synthetic Blob, a Search index, a document push and query, and an optional embedding. It needs its own approval, verified ARM posture, a pre-existing container, and conditional cleanup. It does not prove an EKG workflow.

## Cleanup

`plan-cleanup --run-id <id>` is offline and manual-only. `cleanup-approve --run-id <id> --plan-id <id>` records approval and never deletes Azure resources. Never enable trusted services or widen ingress to make indexers reach Storage or OpenAI.

## Return

Separate reviewed plans from applied changes, and give one safe next action.
