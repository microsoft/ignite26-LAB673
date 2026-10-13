from __future__ import annotations

import re
from typing import Any

from ekg_core.models import BuildSpec, OntologyMode, ProvisioningSpec
from ekg_provision.planner import plan as provision_plan

from .executor import BuildError
from .managed_pipeline import SEARCH_API_VERSION
from .planner import PREVIEW_ENTITLEMENT_UNVERIFIABLE


def preview_enablement_handoff(
    build: BuildSpec, provision: ProvisioningSpec,
    provision_verification: dict[str, Any], *, tenant_id: str,
) -> dict[str, Any]:
    """Prepare a human handoff from read-only, exact-service provisioning evidence."""
    if build.ontology_mode is OntologyMode.NONE:
        raise ValueError("preview enablement handoff requires an ontology-backed build")
    if not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", tenant_id):
        raise ValueError("handoff requires an explicit tenant GUID")
    target = provision.target
    service = (provision_verification.get("resources") or {}).get("create-search_service")
    expected_id = (
        f"/subscriptions/{target.subscription_id}/resourceGroups/{target.resource_group}"
        f"/providers/Microsoft.Search/searchServices/{provision.search_name}"
    )
    expected_endpoint = f"https://{provision.search_name}.search.windows.net"
    if (
        provision_verification.get("status") != "verified"
        or str(provision_verification.get("tenant_id", "")).casefold() != tenant_id.casefold()
        or provision_verification.get("plan_id") !=
            provision_plan(provision, require_active=False).plan_id
        or not isinstance(service, dict)
        or service.get("status") != "present"
        or str(service.get("resource_id", "")).casefold() != expected_id.casefold()
        or str(service.get("endpoint", "")).casefold() != expected_endpoint.casefold()
        or str(service.get("location", "")).replace(" ", "").casefold() !=
            str(target.location).casefold()
        or str(service.get("sku", "")).casefold() != provision.search_sku.casefold()
        or str(service.get("provisioning_state", "")).casefold() != "succeeded"
        or build.target.subscription_id != target.subscription_id
        or build.target.resource_group != target.resource_group
        or str(build.target.location or "").replace(" ", "").casefold() !=
            str(service.get("location", "")).replace(" ", "").casefold()
        or str(build.target.search_endpoint or "").casefold() != expected_endpoint.casefold()
        or (build.tenant_id is not None and build.tenant_id.casefold() != tenant_id.casefold())
        or (build.search_sku is not None and build.search_sku.casefold() !=
            str(service.get("sku", "")).casefold())
    ):
        raise BuildError("preview enablement handoff requires matching verified Search service evidence")
    return {
        "status": "approval_required",
        "code": "GUARDED_ATTEMPT_REQUIRES_APPROVAL",
        "technical_verification": PREVIEW_ENTITLEMENT_UNVERIFIABLE,
        "service": {
            "tenant_id": tenant_id,
            "subscription_id": target.subscription_id,
            "resource_group": target.resource_group,
            "resource_id": service["resource_id"],
            "name": provision.search_name,
            "region": service["location"],
            "sku": service["sku"],
        },
        "feature": "graphExtraction (Search-managed indexed Blob Knowledge Source)",
        "search_api_version": SEARCH_API_VERSION,
        "prerequisites": {
            "search_user_assigned_identity": build.search_identity_resource_id,
            "embedding_deployment": build.embedding_deployment,
            "embedding_model": build.embedding_model,
            "embedding_dimensions": build.embedding_dimensions,
            "chat_deployment": build.chat_deployment,
            "chat_model": build.chat_model,
            "storage_and_openai_access": "Search identity requires scoped data-plane access",
        },
        "build_identity": {"tenant_id": tenant_id, "search_sku": service["sku"]},
        "next_action": (
            "Set BuildSpec tenant_id and search_sku to these exact observed values. "
            "Preview entitlement remains unverified. Obtain separate explicit approval "
            "for the matching plan before one journaled attempt; a 400/403 or "
            "ambiguous outcome must not be retried automatically. Do not contact "
            "the preview owner on behalf of the user."
        ),
    }
