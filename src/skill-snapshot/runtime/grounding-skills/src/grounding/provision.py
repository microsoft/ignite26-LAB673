"""grounding-provision: connect, doctor and idempotent create-if-not-exists (resource group + Search service)."""

from __future__ import annotations

import time
import uuid
from typing import Any

from . import API_VERSION
from .azure import (AUTHZ_API, ROLE_IDS, SEARCH_ARM_API, Azure, endpoint_for, role_gaps, validate_endpoint)
from .errors import AuthError, GroundingError, ServiceError
from .names import DEFAULT_PREFIX, validate_resource_group_name, validate_service_name
from .plan import approval_card, provision_plan_id, require_plan_id

WRITE_ROLES = ["Search Service Contributor", "Search Index Data Contributor"]
ALL_ROLES = WRITE_ROLES + ["Search Index Data Reader"]
DEFAULT_SKU = "basic"
SKUS = ("free", "basic", "standard", "standard2", "standard3")


def _service_id(sub: str, rg: str, name: str) -> str:
    return f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Search/searchServices/{name}"


def _summarize(svc: dict[str, Any]) -> dict[str, Any]:
    props = svc.get("properties", {})
    parts = svc.get("id", "").split("/")
    rg = parts[parts.index("resourceGroups") + 1] if "resourceGroups" in parts else ""
    return {"name": svc.get("name"), "resource_group": rg, "location": svc.get("location"),
            "sku": (svc.get("sku") or {}).get("name"), "endpoint": endpoint_for(svc.get("name", "")),
            "provisioning_state": props.get("provisioningState"),
            "local_auth_disabled": bool(props.get("disableLocalAuth")),
            "entra_auth": bool(props.get("disableLocalAuth")) or "aadOrApiKey" in (props.get("authOptions") or {})}


def list_services(az: Azure, sub: str) -> list[dict[str, Any]]:
    r = az.arm("GET", f"/subscriptions/{sub}/providers/Microsoft.Search/searchServices", api=SEARCH_ARM_API)
    return [_summarize(s) for s in r.get("value", [])]


def probe_preview(az: Azure, endpoint: str) -> dict[str, Any]:
    """Read-only: can this identity list indexes with API 2026-08-01-preview on this service?"""
    try:
        r = az.search("GET", endpoint, "/indexes?$select=name", allow=(400, 404))
    except GroundingError as exc:
        return {"api_version": API_VERSION, "available": None, "code": exc.code, "indexes": []}
    if r.get("_status") in (400, 404):
        return {"api_version": API_VERSION, "available": False, "status": r["_status"],
                "message": str((r.get("error") or {}).get("message", ""))[:300], "indexes": []}
    names = [i.get("name") for i in r.get("value", [])]
    return {"api_version": API_VERSION, "available": True, "indexes": names}


def check_roles(az: Azure, scope: str, roles: list[str]) -> dict[str, bool]:
    r = az.arm("GET", f"{scope}/providers/Microsoft.Authorization/permissions", api=AUTHZ_API)
    return role_gaps(r.get("value", []), roles)


def inspect_service(az: Azure, sub: str, svc: dict[str, Any]) -> dict[str, Any]:
    out = dict(svc)
    scope = _service_id(sub, svc["resource_group"], svc["name"])
    try:
        out["roles"] = check_roles(az, scope, ALL_ROLES)
    except GroundingError as exc:
        out["roles"] = {"error": exc.code}
    preview = probe_preview(az, svc["endpoint"])
    out["preview_api"] = {k: v for k, v in preview.items() if k != "indexes"}
    out["grounding_index_names"] = [n for n in preview["indexes"] if str(n).startswith(DEFAULT_PREFIX)]
    missing = [r for r, ok in out["roles"].items() if ok is False]
    out["missing_roles"] = missing
    return out


def connect(az: Azure, ident: dict[str, Any], service: str = "", endpoint: str = "") -> dict[str, Any]:
    """Read-only discovery. The CLI layer decides whether to persist the chosen endpoint."""
    sub = ident["subscription"]
    services = list_services(az, sub)
    if endpoint:
        host = validate_endpoint(endpoint).split("//")[1].split(".")[0]
        service = service or host
    chosen = [s for s in services if s["name"] == service] if service else []
    if service and not chosen:
        raise GroundingError("SERVICE_NOT_FOUND", f"no Search service named {service!r} in this subscription",
                             "Run grounding-provision connect without --service to list services, or "
                             "grounding-provision create to plan a new one.")
    result: dict[str, Any] = {"ok": True, "tenant": ident["tenant"], "subscription": sub,
                              "services": [{k: s[k] for k in ("name", "resource_group", "location", "sku", "endpoint")}
                                           for s in services]}
    if not services:
        result["next_step"] = "No Search service found. Run `grounding-provision create` to plan one."
    if len(chosen) == 1:
        detail = inspect_service(az, sub, chosen[0])
        result["selected"] = detail
        result["warnings"] = same_service_warning()
    elif not service and services:
        result["next_step"] = "Pass --service <name> to select one and run its checks."
    return result


def same_service_warning() -> list[str]:
    return ["The grounding index must live on the same Search service as the Knowledge Source it will ground; "
            "for an existing build, connect to that build's service rather than creating a new one."]


def doctor(az: Azure, ident: dict[str, Any], endpoint: str) -> dict[str, Any]:
    endpoint = validate_endpoint(endpoint)
    name = endpoint.split("//")[1].split(".")[0]
    svc = next((s for s in list_services(az, ident["subscription"]) if s["name"] == name), None)
    if not svc:
        raise GroundingError("SERVICE_NOT_FOUND", f"service {name!r} not found in subscription")
    d = inspect_service(az, ident["subscription"], svc)
    problems = []
    if d["missing_roles"]:
        problems.append(f"missing roles: {', '.join(d['missing_roles'])}")
    if d["preview_api"].get("available") is not True:
        problems.append(f"API {API_VERSION} not confirmed available on this service")
    if not d["entra_auth"]:
        problems.append("service does not have Entra (RBAC) data-plane auth enabled")
    return {"ok": not problems, "tenant": ident["tenant"], "subscription": ident["subscription"],
            "service": d, "problems": problems, "warnings": same_service_warning()}


# ---------------------------------------------------------------------------------------------------------------
def create_plan(az: Azure, ident: dict[str, Any], *, resource_group: str, service_name: str, location: str,
                sku: str = DEFAULT_SKU) -> dict[str, Any]:
    validate_resource_group_name(resource_group)
    validate_service_name(service_name)
    if sku not in SKUS:
        raise GroundingError("SKU_INVALID", f"sku must be one of {', '.join(SKUS)}")
    sub = ident["subscription"]
    plan_id = provision_plan_id(ident["tenant"], sub, resource_group, service_name, location, sku)
    rg = az.arm("GET", f"/subscriptions/{sub}/resourcegroups/{resource_group}", allow=(404,))
    rg_exists = rg.get("_status") != 404
    svc_exists, svc_info = False, None
    existing = list_services(az, sub)
    for s in existing:
        if s["name"] == service_name:
            svc_exists, svc_info = True, s
    if not svc_exists:
        avail = az.arm("POST", f"/subscriptions/{sub}/providers/Microsoft.Search/checkNameAvailability",
                       {"name": service_name, "type": "searchServices"}, api=SEARCH_ARM_API)
        if avail.get("nameAvailable") is False:
            raise GroundingError("SERVICE_NAME_TAKEN", f"Search service name {service_name!r} is unavailable: "
                                 f"{avail.get('message', avail.get('reason', ''))}",
                                 "Choose a different --service-name (names are globally unique).")
    if svc_exists and svc_info["resource_group"].lower() != resource_group.lower():
        raise GroundingError("SERVICE_IN_OTHER_GROUP",
                             f"service {service_name!r} already exists in resource group {svc_info['resource_group']!r}",
                             "Use that resource group (it will be reused), or pick another service name.")
    changes = [
        f"Resource group {resource_group}: " + ("exists, reused" if rg_exists else f"create in {location}"),
        f"Search service {service_name}: " + ("exists, reused (no changes)" if svc_exists else
                                              f"create, sku {sku}, 1 replica, 1 partition, {location}, "
                                              "Entra (RBAC) auth only, local keys disabled"),
        "Role assignments for the signed-in identity at the service scope (only those not already held): "
        + ", ".join(ALL_ROLES),
    ]
    cost = (f"{sku} tier, 1 search unit, billed hourly while the service exists; no model or embedding calls. "
            f"This subscription currently has {len(existing)} Search service(s).")
    notices = same_service_warning()
    return {"ok": True, "kind": "provision", "plan_id": plan_id, "tenant": ident["tenant"], "subscription": sub,
            "resource_group": resource_group, "service_name": service_name, "location": location, "sku": sku,
            "resource_group_exists": rg_exists, "service_exists": svc_exists,
            "no_op": rg_exists and svc_exists, "changes": changes, "cost": cost, "notices": notices,
            "approval": approval_card(plan_id, f"create-if-not-exists Search service {service_name}", changes, cost,
                                      notices)}


def _wait_service(az: Azure, sub: str, rg: str, name: str, timeout: float = 900.0) -> dict[str, Any]:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        r = az.arm("GET", _service_id(sub, rg, name), api=SEARCH_ARM_API)
        state = (r.get("properties") or {}).get("provisioningState")
        if state == "succeeded":
            return r
        if state in ("failed", "deleting"):
            raise ServiceError("PROVISIONING_FAILED", f"service provisioning state: {state}")
        time.sleep(10)
    raise ServiceError("PROVISIONING_TIMEOUT", "service did not reach succeeded in time",
                       "Re-run create with the same --plan-id; it is idempotent.")


def create_apply(az: Azure, ident: dict[str, Any], plan_id: str, **kw: Any) -> dict[str, Any]:
    plan = create_plan(az, ident, **kw)
    require_plan_id(plan_id, plan["plan_id"])
    sub, rg, name, loc = ident["subscription"], plan["resource_group"], plan["service_name"], plan["location"]
    actions: list[str] = []
    if not plan["resource_group_exists"]:
        az.arm("PUT", f"/subscriptions/{sub}/resourcegroups/{rg}", {"location": loc})
        actions.append("resource_group_created")
    else:
        actions.append("resource_group_reused")
    if not plan["service_exists"]:
        body = {"location": loc, "sku": {"name": plan["sku"]},
                "properties": {"replicaCount": 1, "partitionCount": 1, "hostingMode": "default",
                               "publicNetworkAccess": "enabled", "disableLocalAuth": True}}
        az.arm("PUT", _service_id(sub, rg, name), body, api=SEARCH_ARM_API)
        actions.append("service_created")
    else:
        actions.append("service_reused")
    svc = _wait_service(az, sub, rg, name)
    scope = _service_id(sub, rg, name)
    held = check_roles(az, scope, ALL_ROLES)
    assigned, still_needed, pending = [], [], []
    principal_type = "User" if "@" in (ident.get("principal") or "") else "ServicePrincipal"
    for role in ALL_ROLES:
        if held.get(role):
            continue
        ra = uuid.uuid5(uuid.NAMESPACE_URL, f"{scope}|{ident['principal_id']}|{role}")
        body = {"properties": {
            "roleDefinitionId": f"/subscriptions/{sub}/providers/Microsoft.Authorization/roleDefinitions/{ROLE_IDS[role]}",
            "principalId": ident["principal_id"], "principalType": principal_type}}
        try:
            if az.arm("GET", f"{scope}/providers/Microsoft.Authorization/roleAssignments/{ra}", api=AUTHZ_API,
                      allow=(404,)).get("_status") != 404:
                pending.append(role)
                continue
            az.arm("PUT", f"{scope}/providers/Microsoft.Authorization/roleAssignments/{ra}", body, api=AUTHZ_API)
            assigned.append(role)
        except AuthError:
            still_needed.append(role)
    final = _summarize(svc)
    return {"ok": True, "kind": "provision", "plan_id": plan["plan_id"], "actions": actions,
            "no_op": plan["no_op"] and not assigned, "service": final, "roles_assigned": assigned,
            "roles_assigned_awaiting_propagation": pending,
            "roles_still_needed": still_needed, "roles_already_held": [r for r in ALL_ROLES if held.get(r)],
            "next_step": ("Role assignments can take a few minutes to propagate. Then run "
                          f"`grounding-provision connect --service {name}`."
                          + (f" Ask an owner to grant: {', '.join(still_needed)}." if still_needed else "")),
            "warnings": same_service_warning()}
