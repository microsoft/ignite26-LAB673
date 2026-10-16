from __future__ import annotations

import re

from ekg_core.models import BuildSpec

def search_resource_id(spec: BuildSpec) -> str:
    target = spec.target
    endpoint = target.search_endpoint or ""
    match = re.fullmatch(r"https://([a-z0-9][a-z0-9-]{0,58}[a-z0-9])\.search\.windows\.net", endpoint)
    if (
        not match
        or not isinstance(target.subscription_id, str)
        or not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}",
                            target.subscription_id)
        or not isinstance(target.resource_group, str)
        or not re.fullmatch(r"[a-zA-Z0-9_.()\-]{1,90}", target.resource_group)
    ):
        raise ValueError("managed graph requires an exact Search service endpoint, subscription and RG")
    return (
        f"/subscriptions/{target.subscription_id}/resourceGroups/{target.resource_group}"
        f"/providers/Microsoft.Search/searchServices/{match.group(1)}"
    )


def graph_input_error(spec: BuildSpec) -> str | None:
    try:
        search_resource_id(spec)
    except ValueError:
        return "GRAPH_TARGET_INVALID: exact Search endpoint, subscription and resource group are required"
    if not isinstance(spec.tenant_id, str) or not re.fullmatch(
        r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", spec.tenant_id
    ):
        return "TENANT_REQUIRED: explicit tenant_id is required for fresh identity verification"
    if not isinstance(spec.search_sku, str) or not spec.search_sku.strip():
        return "SEARCH_SKU_REQUIRED: explicit Search SKU is required"
    if not isinstance(spec.target.location, str) or not spec.target.location.strip():
        return "SEARCH_REGION_REQUIRED: explicit Search region is required"
    return None
