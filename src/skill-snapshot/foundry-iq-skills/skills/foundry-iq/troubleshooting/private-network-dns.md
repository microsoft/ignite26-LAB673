# Private Networking and DNS

Use for DNS failures, timeouts, or firewall-related 403s. Record the failing hostname, caller execution network, status/error, UTC time, and request ID; redact credentials and private content.
Follow the [API version policy](../references/api-version-policy.md) with the original request version as input; do not silently change it. Apply the [HTTP contract](../references/http-contract.md).
Start read-only; ask before DNS, firewall, endpoint, or indexer changes. Follow [networking rules](../references/networking.md); never enable public access or disable a firewall to bypass the failure.

## Workflow

1. **Wrong DNS or caller network.** From the actual failing host, run `nslookup <service>.search.windows.net`; for a private path, verify the alias resolves through `privatelink.search.windows.net` to the intended private endpoint IP.
   Check the private DNS zone's VNet link/forwarding and the caller's VPN/VNet route. Continue using `https://<service>.search.windows.net`, not the private-link hostname or raw IP. A successful lookup from a developer laptop does not prove agent reachability.
2. **Inbound endpoint is not ready.** [Read the private endpoint connection](../operations/search-management/private-endpoint-connections/get.md); confirm the right service/subresource, approval, and successful provisioning.
   A pending/rejected connection needs the resource owner's action. Once routing/DNS is correct, retry the original authenticated read once; an authentication error should then follow [RBAC diagnosis](authentication-rbac.md), not another network change.
3. **Search cannot reach private Storage/models.** An inbound Search endpoint does not provide outbound dependency access. [Read the shared private link](../operations/search-management/shared-private-link-resources/get.md) and verify target/group ID, `Approved` status, and `Succeeded` provisioning state.
   For an independently managed indexer, check `parameters.configuration.executionEnvironment` is `private`; propose an approved [indexer update](../operations/data-plane/indexers/create-or-update.md) if needed. Do not manually rewrite a knowledge source's generated pipeline; use its supported source configuration.

**Verify/stop:** Recheck from the failing host; for outbound ingestion, use an approved indexer run and inspect its status. If still blocked, return hostname, resolved IP, connection states, failing direction, and network-owner action; keep the private boundary intact.

**Sources:** [Inbound private endpoint and DNS](https://learn.microsoft.com/azure/search/service-create-private-endpoint), [Outbound shared private links](https://learn.microsoft.com/azure/search/search-indexer-howto-access-private).
