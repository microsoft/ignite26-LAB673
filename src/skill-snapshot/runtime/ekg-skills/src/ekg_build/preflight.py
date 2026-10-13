"""Offline route decisions and read-only, exact-resource preflight."""

from __future__ import annotations

import re
from typing import Any, Protocol

from ekg_core.models import (
    BuildSpec, Event, KnowledgeSourceKind, OntologyMode, PreflightResult,
    RequestedOutcome, RouteDecision, SourceKind, stable_id,
)

from .managed_pipeline import SEARCH_API_VERSION
from .preview import PREVIEW_ENTITLEMENT_UNVERIFIABLE, probe_error, search_resource_id


class ResourceReader(Protocol):
    def inspect_search_service(self, resource_id: str, tenant_id: str) -> dict[str, Any]: ...
    def inspect_resource(self, resource_id: str, tenant_id: str) -> dict[str, Any]: ...


_ARM_ID = re.compile(
    r"/subscriptions/([0-9a-fA-F-]{36})/resourceGroups/([^/]+)/"
    r"providers/(Microsoft\.[^/]+)/([^/]+)/([^/]+)", re.IGNORECASE,
)
_GUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")


def _identity(resource_id: str | None, provider: str, resource_type: str) -> tuple[str, str, str] | None:
    match = _ARM_ID.fullmatch(resource_id or "")
    if not match or not _GUID.fullmatch(match[1]) or (
        match[3].casefold(), match[4].casefold()
    ) != (provider.casefold(), resource_type.casefold()):
        return None
    return match[1], match[2], match[5]


def route(spec: BuildSpec) -> RouteDecision:
    outcome = spec.requested_outcome or (
        RequestedOutcome.GRAPH_BUILD if spec.ontology_mode is not OntologyMode.NONE
        else RequestedOutcome.KB_HANDOFF
    )
    kind = spec.knowledge_source_kind or (
        KnowledgeSourceKind.SHAREPOINT if spec.source and spec.source.kind is SourceKind.SHAREPOINT_LIBRARY
        else KnowledgeSourceKind.AZURE_BLOB if outcome is RequestedOutcome.GRAPH_BUILD
        or spec.source and spec.source.kind is SourceKind.BLOB_PREFIX
        else KnowledgeSourceKind.FILE
    )
    if outcome is RequestedOutcome.KB_HANDOFF:
        return RouteDecision(outcome, kind, "unsupported",
                             blocked_by=("KB_HANDOFF_NOT_IMPLEMENTED: EKG does not create or bind a Foundry IQ KB",))
    if kind is not KnowledgeSourceKind.AZURE_BLOB or (
        spec.source and spec.source.kind is SourceKind.SHAREPOINT_LIBRARY
    ):
        return RouteDecision(outcome, kind, "unsupported",
                             blocked_by=("UNSUPPORTED_GRAPH_ROUTE: graphExtraction is verified only on Azure Blob KS; no automatic source copy",))
    if spec.ontology_mode is OntologyMode.NONE or not spec.graph_retrieval:
        return RouteDecision(outcome, kind, "unsupported",
                             blocked_by=("GRAPH_INPUT_REQUIRED: graph Build needs an ontology and graph_retrieval",))
    if spec.source is not None and spec.source_manifest is None:
        return RouteDecision(
            outcome, kind, "contract_only",
            evidence=(f"Search {SEARCH_API_VERSION} Azure Blob graphExtraction verified on one service only",),
            uncertainty=(PREVIEW_ENTITLEMENT_UNVERIFIABLE,),
            blocked_by=("SOURCE_ROUTE_NOT_INTEGRATED: explicit source manifests are not consumed by Build yet",),
        )
    if spec.source is not None:
        return RouteDecision(
            outcome, kind, "verified_path",
            evidence=(f"Search {SEARCH_API_VERSION} Azure Blob graphExtraction via approved staging",),
            uncertainty=(PREVIEW_ENTITLEMENT_UNVERIFIABLE,),
        )
    return RouteDecision(
        outcome, kind, "verified_path",
        evidence=(f"legacy local corpus to managed Azure Blob KS uses Search {SEARCH_API_VERSION}",),
        uncertainty=(PREVIEW_ENTITLEMENT_UNVERIFIABLE,),
    )


def target_blockers(spec: BuildSpec) -> tuple[str, ...]:
    target = spec.target
    errors: list[str] = []
    if target.search_resource_id is not None:
        try:
            expected_search = search_resource_id(spec)
        except ValueError:
            expected_search = None
        if (not isinstance(target.search_resource_id, str) or not expected_search
                or target.search_resource_id.casefold() != expected_search.casefold()):
            errors.append("TARGET_ID_MISMATCH: Search ARM ID differs from exact subscription, RG or endpoint")
    for label, resource_id, provider, kind, endpoint, suffix in (
        ("Storage", target.storage_resource_id, "Microsoft.Storage", "storageAccounts",
         target.storage_endpoint, "blob.core.windows.net"),
        ("OpenAI", target.openai_resource_id, "Microsoft.CognitiveServices", "accounts",
         target.openai_endpoint, None),
    ):
        if resource_id is None:
            continue
        parsed = _identity(resource_id, provider, kind)
        if parsed is None:
            errors.append(f"TARGET_ID_MISMATCH: {label} ARM ID is invalid")
        elif label == "Storage" and endpoint != f"https://{parsed[2]}.{suffix}":
            errors.append("TARGET_ENDPOINT_MISMATCH: Storage endpoint differs from exact account ARM ID")
        elif label == "OpenAI" and not isinstance(endpoint, str):
            errors.append("TARGET_ENDPOINT_MISMATCH: OpenAI endpoint is required with its ARM ID")
    if spec.source and spec.source.kind is SourceKind.BLOB_PREFIX:
        parsed = _identity(spec.source.resource_id, "Microsoft.Storage", "storageAccounts")
        if parsed is None or spec.source.reference != f"https://{parsed[2]}.blob.core.windows.net":
            errors.append("SOURCE_ID_MISMATCH: Blob source endpoint differs from exact account ARM ID")
    return tuple(errors)


def scope(spec: BuildSpec, decision: RouteDecision | None) -> dict[str, Any]:
    from .executor import staging_prefix

    try:
        derived_search_id = search_resource_id(spec)
    except ValueError:
        derived_search_id = None
    return {
        "source_kind": spec.source.kind.value if spec.source else "legacy_local_path",
        "source_id": spec.source.source_id if spec.source else stable_id("source", spec.corpus_source),
        "source_resource_id": spec.source.resource_id if spec.source else None,
        "manifest_digest": spec.source_manifest.digest if spec.source_manifest else None,
        "document_count": spec.source_manifest.document_count if spec.source_manifest else None,
        "requested_outcome": decision.outcome.value if decision else "legacy_document_index",
        "knowledge_source_kind": decision.knowledge_source_kind.value if decision else None,
        "tenant_id": spec.tenant_id,
        "subscription_id": spec.target.subscription_id,
        "search_resource_id": spec.target.search_resource_id or derived_search_id,
        "storage_resource_id": spec.target.storage_resource_id,
        "openai_resource_id": spec.target.openai_resource_id,
        **({
            "storage_container": spec.storage_container,
            "staging_prefix": staging_prefix(spec),
            "search_endpoint": spec.target.search_endpoint,
            "storage_endpoint": spec.target.storage_endpoint,
            "openai_endpoint": spec.target.openai_endpoint,
        } if spec.source_manifest and spec.source else {}),
    }


def _observed_mismatch(blockers: list[str]) -> bool:
    return any(item.startswith((
        "TARGET_ID_MISMATCH:", "TARGET_ENDPOINT_MISMATCH:",
        "TARGET_SKU_MISMATCH:", "TARGET_REGION_MISMATCH:", "TARGET_NOT_READY:",
        "TENANT_MISMATCH:", "PERMISSION_DENIED:", "TARGET_INSPECTION_FAILED:",
    )) for item in blockers)


def preflight(spec: BuildSpec, reader: ResourceReader | None = None) -> PreflightResult:
    from .planner import plan

    desired = plan(spec)
    legacy_documents = desired.route is None and spec.ontology_mode is OntologyMode.NONE
    decision = desired.route or (None if legacy_documents else route(spec))
    blockers = list(desired.blocked_by)
    unsupported = decision is not None and decision.capability == "unsupported"
    if unsupported:
        blockers.extend(reason for reason in (
            decision.blocked_by or ("UNSUPPORTED_ROUTE: no implemented route",)
        ) if reason not in blockers)
    evidence: dict[str, Any] = {
        "origin": "offline_contract",
        "capability": decision.capability if decision else "legacy_document_index",
    }
    uncertainties = list(decision.uncertainty) if decision else []
    can_inspect = (
        reader is not None and not probe_error(spec) and not target_blockers(spec)
        and not unsupported
    )
    if can_inspect:
        expected = spec.target.search_resource_id or search_resource_id(spec)
        observed = reader.inspect_search_service(expected, spec.tenant_id)
        evidence["origin"] = "injected_resource_observations"
        if not isinstance(observed, dict):
            blockers.append("TARGET_INSPECTION_FAILED: Search inspection did not return resource metadata")
        else:
            properties = observed.get("properties")
            sku = observed.get("sku")
            if (str(observed.get("id", "")).casefold() != expected.casefold()
                    or str(observed.get("name", "")).casefold() != expected.rsplit("/", 1)[-1].casefold()
                    or not isinstance(properties, dict)
                    or properties.get("endpoint") != spec.target.search_endpoint):
                blockers.append("TARGET_ID_MISMATCH: observed Search ARM identity or endpoint differs")
            elif not isinstance(sku, dict) or str(sku.get("name", "")).casefold() != str(spec.search_sku or "").casefold():
                blockers.append("TARGET_SKU_MISMATCH: observed Search SKU differs")
            elif str(observed.get("location", "")).replace(" ", "").casefold() != str(spec.target.location or "").casefold():
                blockers.append("TARGET_REGION_MISMATCH: observed Search region differs")
            elif str(properties.get("provisioningState", "")).casefold() != "succeeded":
                blockers.append("TARGET_NOT_READY: Search provisioning is not complete")
            if (observed.get("tenant_id") and
                    str(observed["tenant_id"]).casefold() != spec.tenant_id.casefold()
                    or spec.source_manifest and not observed.get("tenant_id")):
                blockers.append("TENANT_MISMATCH: observed tenant differs from requested tenant")
            if observed.get("permissions") == "denied":
                blockers.append("PERMISSION_DENIED: caller lacks required Search access")
            evidence["search_arm_observed"] = not _observed_mismatch(blockers)
            if not observed.get("tenant_id"):
                uncertainties.append("TENANT_UNVERIFIED: Search ARM resource does not attest tenant membership")
        for label, resource_id, endpoint in (
            ("Storage", spec.target.storage_resource_id, spec.target.storage_endpoint),
            ("OpenAI", spec.target.openai_resource_id, spec.target.openai_endpoint),
        ):
            if not resource_id or _observed_mismatch(blockers):
                continue
            if not hasattr(reader, "inspect_resource"):
                uncertainties.append(f"{label.upper()}_UNVERIFIED: no read-only resource reader is available")
                continue
            observed = reader.inspect_resource(resource_id, spec.tenant_id)
            if (not isinstance(observed, dict)
                    or str(observed.get("id", "")).casefold() != resource_id.casefold()
                    or observed.get("endpoint") != endpoint):
                blockers.append(f"TARGET_ID_MISMATCH: observed {label} ARM identity or endpoint differs")
            elif (observed.get("tenant_id") and
                  str(observed["tenant_id"]).casefold() != spec.tenant_id.casefold()
                  or spec.source_manifest and not observed.get("tenant_id")):
                blockers.append(f"TENANT_MISMATCH: observed {label} tenant differs")
            elif observed.get("permissions") == "denied":
                blockers.append(f"PERMISSION_DENIED: caller lacks required {label} access")
            else:
                evidence[f"{label.lower()}_arm_observed"] = True
    elif not unsupported:
        uncertainties.append("TARGET_UNVERIFIED: no read-only resource observations were supplied")
    if not unsupported:
        uncertainties.append("PERMISSIONS_UNVERIFIED: ARM identity alone does not prove data-plane RBAC or network access")
    if spec.source is not None:
        uncertainties.append(
            "SOURCE_APPROVAL_RECHECK_REQUIRED: source bytes must be rechecked before staging"
            if spec.source_manifest else
            "SOURCE_NOT_INVENTORIED: provide an adapter-produced manifest for this route"
        )
    priority = next((item for item in blockers if item.startswith((
        "TARGET_ID_MISMATCH:", "TARGET_ENDPOINT_MISMATCH:",
        "TARGET_SKU_MISMATCH:", "TARGET_REGION_MISMATCH:", "TARGET_NOT_READY:",
        "TENANT_MISMATCH:", "PERMISSION_DENIED:", "SOURCE_ID_MISMATCH:",
    ))), None)
    if priority is None and unsupported:
        priority = decision.blocked_by[0] if decision.blocked_by else "UNSUPPORTED_ROUTE: no implemented route"
    if priority is None and blockers:
        priority = blockers[0]
    code = priority.split(":", 1)[0] if priority else (
        "DOCUMENT_INDEX_UNVERIFIED" if legacy_documents else "PREVIEW_ENTITLEMENT_UNVERIFIABLE"
    )
    next_action = (
        "Inventory the source with its read-only adapter, attach its manifest, then request "
        "separate approval of the exact staged Azure Blob graph plan."
        if code == "SOURCE_ROUTE_NOT_INTEGRATED" else
        "Use a separately implemented KB handoff; do not claim that EKG created a KB."
        if code == "KB_HANDOFF_NOT_IMPLEMENTED" else
        "Implement read-only exact-resource verification before attempting Build with these target IDs."
        if code == "TARGET_VERIFICATION_NOT_INTEGRATED" else
        "Correct the exact source, target or route and rerun read-only preflight."
        if blockers else
        "Inspect the legacy document-index plan and request separate approval for its writes; "
        "this path creates no Knowledge Base or graph."
        if legacy_documents else
        "Review the exact plan and unknown preview/permissions; request separate approval for one guarded attempt."
    )
    event = Event("preflight", "blocked" if blockers else "planned", code, {
        "plan_id": desired.plan_id, "blockers": blockers,
        "uncertainty": uncertainties, "evidence": evidence,
    })
    return PreflightResult(desired.plan_id, "blocked" if blockers else "unverified", code, next_action,
                           decision, desired.scope or scope(spec, decision), (event,))
