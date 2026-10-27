# Authentication and RBAC

Use for 401/403 from ARM, Search, or an outbound dependency. Record the failing endpoint, operation, status/error, UTC time, and request ID; redact tokens, keys, and private content.
Follow the [API version policy](../references/api-version-policy.md) with the original request version as input; do not silently change it. Apply the [HTTP contract](../references/http-contract.md).
Start read-only; get approval before permission or authentication changes. Use the [shared RBAC check](../references/authentication-rbac.md) rather than granting broad roles or falling back to keys.

## Workflow

1. **Wrong tenant or token audience (401).** Check the active subscription and tenant with `az account show`. Refresh an expired credential using the existing sign-in flow.
   Use `https://management.azure.com/.default` for ARM and `https://search.azure.com/.default` for Search. Never print the acquired token or silently switch tenants.
2. **Missing inbound Search permission (403).** [Read the service](../operations/search-management/services/get.md) and check whether `authOptions` permits Entra authentication; `disableLocalAuth` only controls keys.
   Compare the caller's effective access with the catalog: Search Service Contributor manages objects, Search Index Data Contributor loads documents, and Search Index Data Reader queries/retrieves. ARM Contributor alone is insufficient for data access.
3. **Search cannot access a dependency.** If the caller can reach Search but ingestion/model calls fail, check the identity selected by the data source or skill, not the signed-in user's roles.
   For Blob ingestion, the Search managed identity needs Storage Blob Data Reader on the approved storage scope. Follow the source/model guide for other grants; network-related 403s go to [network diagnosis](private-network-dns.md).

**Verify/stop:** Retry the original operation once after credential refresh or bounded grant propagation. If still denied, return the failing identity, required role/scope, and administrator action; never report a role-assignment write as proof of access.

**Sources:** [Search roles](https://learn.microsoft.com/azure/search/search-security-rbac), [Blob knowledge-source prerequisites](https://learn.microsoft.com/azure/search/agentic-knowledge-source-how-to-blob).
