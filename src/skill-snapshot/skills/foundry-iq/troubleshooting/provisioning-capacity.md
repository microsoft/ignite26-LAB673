# Provisioning and Capacity

Use for failed service creation/scaling. Record subscription, region, SKU/capacity, deployment error, UTC time, and correlation/request ID; redact credentials.
Follow the [API version policy](../references/api-version-policy.md) with the original request version as input; do not silently change it. Apply the [HTTP contract](../references/http-contract.md).
Start read-only; require approval for registration, billable changes, or a different region/tier. Follow [service provisioning](../references/service-provisioning.md); never replace or delete a reused service to force success.

## Workflow

1. **Still provisioning, not failed.** [Read the service](../operations/search-management/services/get.md) and the original ARM operation/deployment error. If still running, make at most two spaced status checks and report in-progress rather than submitting another create/scale request.
   Use the terminal error to distinguish authorization, invalid parameters, quota, or regional capacity; a data-plane connectivity failure alone is not a provisioning failure.
2. **Invalid name or unregistered provider.** [Check name availability](../operations/search-management/services/check-name-availability.md): the name is globally unique, 2-60 lowercase letters/digits/dashes, without dashes in the first two positions, at the end, or consecutively.
   In the subscription's Resource providers view, check `Microsoft.Search` registration. If missing, ask the subscription owner to register it; do not silently register providers. Check the requested SKU and features are supported in the intended region and original API version.
3. **Quota versus capacity.** [List subscription usage](../operations/search-management/usages/list-by-subscription.md) and check the tier/region service quota; only one Free service is allowed per subscription.
   Available quota does not guarantee regional capacity. For capacity errors, consult current regional availability and propose an allowed alternative region/tier or support request; get approval and preserve residency/network requirements before changing the plan.

**Verify/stop:** After the cause is resolved, retry the original approved creation/scale operation once using its [catalog contract](../references/operation-catalog.yaml); preserve method, payload, region, and tier. Read back terminal success and expected settings; otherwise return the exact error, quota/capacity evidence, and required owner action.

**Sources:** [Creation prerequisites and naming](https://learn.microsoft.com/azure/search/search-create-service-portal), [Quota versus capacity](https://learn.microsoft.com/azure/search/search-limits-quotas-capacity#diagnose-quota-capacity-or-limit-failures).
