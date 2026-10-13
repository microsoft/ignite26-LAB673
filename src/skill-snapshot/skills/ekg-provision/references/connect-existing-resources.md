# Connect existing resources

## Quick starts

- "Connect EKG to my existing Search service, Storage account and Azure OpenAI account."
- "Check whether my Azure resources are ready for an EKG, without changing anything."

## Use this path

Use this path when the operator already has candidate Search, Storage, and Azure OpenAI resources and wants a read-only readiness answer before any change.

## Discovery

1. Confirm the tenant and subscription first.
2. Run `ekg-skills-ekg_doctor` if sign-in or environment readiness is uncertain.
3. Run `ekg-skills-ekg_provision_connect` with the confirmed tenant and subscription, plus whatever names, ARM IDs, container, deployments, or search identity are already known.

## Interpretation

- `blocked`: a hard prerequisite failed, such as unsupported Search tier, missing identity, or insecure resource posture. Return the exact blocker.
- `incomplete`: the tool found candidates but needs the operator to choose one.
- `needs_setup`: the tool found gaps it can later fill, such as a missing private container, deployment, or role assignment. The write still belongs to the CLI approval path.
- `ready`: return the exact build binding and next step.
- `unverified`: role or quota evidence could not be fully confirmed. Treat this as uncertainty, not as a missing grant proof.

## Approved write follow-through

When connect returns a setup plan and the user wants it, keep the same flags and move to `ekg-provision connect-apply` only after `approved <plan-id>`. MCP never grants roles or creates resources.

## Return

State tenant, subscription, status, and the single next safe action. Do not invent missing resources, identities, or role grants.
