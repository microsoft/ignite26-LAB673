# Capacity, RBAC, smoke

## Use this path

Use this path for bounded follow-on operations against existing provisioned resources: quota checks, TPM resizing, explicit RBAC plans, smoke tests, and cleanup evidence.

## Read-only reviews

- `ekg-provision quota` checks model catalog availability and remaining TPM headroom.
- `ekg-provision plan-capacity` reviews a capacity-only patch and prints the exact plan ID.
- `ekg-provision plan-rbac` reviews the four data-role grants used by EKG's public-test path.
- `ekg-provision plan-smoke` reviews a synthetic proof workflow.
- `ekg-provision plan-cleanup` reads the local provisioning journal and proposes manual cleanup evidence only.

## Write gates

- `ekg-provision capacity-update`, `ekg-provision rbac-grant`, and `ekg-provision smoke-run` each require the exact approved plan ID and `--confirm-writes`.
- `ekg-provision cleanup-approve` records approval of the cleanup plan but never deletes Azure resources.
- Re-read drift or quota failures block the write; do not patch around them.

## Return

State which bounded plan was reviewed, whether the result was read-only or applied, and what evidence source you used. Keep cost, role, and network claims tied to the exact reviewed plan.
