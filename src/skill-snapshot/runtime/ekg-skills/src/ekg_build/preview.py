from __future__ import annotations

import re

from ekg_core.models import BuildSpec

PREVIEW_ENTITLEMENT_UNVERIFIABLE = (
    "PREVIEW_ENTITLEMENT_UNVERIFIABLE: no authoritative read-only entitlement "
    "signal is documented for this Search service. An explicitly approved, "
    "journaled exact-service attempt may fail with 400/403; never treat a "
    "caller-supplied record or successful service statistics as entitlement."
)


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


def probe_error(spec: BuildSpec) -> str | None:
    try:
        search_resource_id(spec)
    except ValueError:
        return ("PREVIEW_ENABLEMENT_REQUIRED: exact Search service endpoint, "
                f"subscription and RG are required; {PREVIEW_ENTITLEMENT_UNVERIFIABLE}")
    if not isinstance(spec.tenant_id, str) or not re.fullmatch(
        r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", spec.tenant_id
    ):
        return ("PREVIEW_ENABLEMENT_REQUIRED: explicit tenant_id is required for "
                f"fresh identity verification; {PREVIEW_ENTITLEMENT_UNVERIFIABLE}")
    if not isinstance(spec.search_sku, str) or not spec.search_sku.strip():
        return "PREVIEW_ENABLEMENT_REQUIRED: explicit Search SKU is required"
    if not isinstance(spec.target.location, str) or not spec.target.location.strip():
        return "PREVIEW_ENABLEMENT_REQUIRED: explicit Search region is required"
    return None
