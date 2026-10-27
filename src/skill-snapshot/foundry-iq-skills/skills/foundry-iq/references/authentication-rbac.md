# Authentication and RBAC

The [operation catalog](operation-catalog.yaml) owns operation-specific permission requirements; this reference explains how to resolve and satisfy them. Use the selected source/scenario guide for dependent-resource permissions. Apply these checks to standalone operations as well as hero scenarios.

## Identify who needs access

Distinguish the caller (the user or application executing the operation) from the Search managed identity used for outbound connections to storage and models. Permissions granted to one do not transfer to the other. Prefer managed identity for workloads and user credentials only for interactive setup.

Use Microsoft Entra tokens with audience `https://management.azure.com/.default` for ARM and `https://search.azure.com/.default` for Search data plane. Contributor access to manage the service does not grant Entra-authenticated data-plane access. Check the catalog for the selected operation rather than assuming a management role is sufficient.

Reuse a compatible existing managed identity. Only enable or attach an identity when the selected workflow needs one, and ask before changing it. Enabling a Search identity neither grants access to dependencies nor enables inbound Search RBAC. Check that the service accepts Entra authentication; ask before changing authentication settings and preserve existing clients.

## Check access and ask only when needed

On a permissions blocker, first use [access diagnosis](../hero-scenarios/diagnose-access-issues/diagnose-access-issues.md)
unless already on that route; retain the original operation, principal and runtime.
A 401/403 alone does not prove
a missing grant; diagnose token, identity and command-construction mistakes before
asking the user or administrator to change access.

For scoped Azure discovery, use `az role assignment list --assignee <principal-id>
--scope <resource-id> --include-inherited`. `--all` and `--scope` are incompatible;
do not combine them. This command lists assignments, not proof of effective access.

1. Check the required permission for the exact identity and target resource. Reuse sufficient existing access, including inherited, group, or custom-role access; do not create duplicate grants. Use the narrowest supported scope: Search permissions belong on Search, while dependency permissions belong on the storage, model, or source resource.
2. If access is missing, check whether the caller can grant that permission at that scope. Azure role assignments require `Microsoft.Authorization/roleAssignments/write`, for example through Owner, User Access Administrator, or Role Based Access Control Administrator, subject to assignment conditions. Contributor alone cannot assign roles. For source-specific permissions, check that source's grant authority instead.
3. **If the caller can grant it**, ask: "May I grant `<role>` to `<identity>` on `<scope>` so it can `<action>`?" Include the principal ID and exact resource scope. Apply only the missing grant after explicit approval; reuse approval already covering that exact grant.
4. **If the caller cannot grant it, or authority cannot be verified**, tell the user: "Ask your administrator to grant `<role>` to `<identity>` (principal ID `<id>`) on `<scope>` so it can `<action>`." Pause the dependent operation until access is confirmed. Do not request broad Owner access merely to complete setup.

After an approved grant, allow bounded propagation and verify access through the selected operation. A successful role-assignment write alone is not proof that access is effective. If approval is declined or access remains unconfirmed, report the blocked operation; never silently fall back to keys or broaden permissions.

Never retrieve or print keys unless the selected credential operation explicitly requires it; even then suppress the secret-bearing response. Never expose tokens.

## Model inference role equivalents

For the Search identity's embedding and KB planning calls, reuse sufficient
existing data-plane access on the model account or an ancestor. Built-in
**Foundry User** and **Cognitive Services User** both grant
`Microsoft.CognitiveServices/*` in `DataActions`, with the same exclusions;
neither excludes normal embedding or chat-completion inference.
An existing Foundry User assignment therefore satisfies this dependency.
A project-only assignment does not cover the model account.
Check the actual principal, inherited scope, conditions and deny assignments,
not just the role name or control-plane `Actions`.

For a new grant, retain the recipe's Cognitive Services User choice and ask
first. Do not add it merely because sufficient Foundry User access has another
name. These roles are equivalent for this inference dependency, not for every
management operation or other Foundry permission.

## Official references

- [Search roles and permissions](https://learn.microsoft.com/azure/search/search-security-rbac)
- [Search managed identities](https://learn.microsoft.com/azure/search/search-how-to-managed-identities)
- [Enable Search RBAC](https://learn.microsoft.com/azure/search/search-security-enable-roles)
- [Built-in AI and machine-learning role permissions](https://learn.microsoft.com/azure/role-based-access-control/built-in-roles/ai-machine-learning)
