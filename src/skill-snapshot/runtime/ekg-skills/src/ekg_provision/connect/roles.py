from typing import Any, Callable
from ekg_core.models import stable_id
from ekg_core.az_identity import IdentityError, az_json
from .spec import ACCEPTED_ROLES, UNVERIFIED_ROLE, ConnectSpec
from .openai_roles import OpenAICoverage
def _principal_roles(
    spec: ConnectSpec, principal: str, principal_type: str, scope: str, roles: tuple[str, ...],
    who: str, runner: Callable[..., Any],
    *, openai_coverage: OpenAICoverage | None = None,
) -> list[dict[str, Any]]:
    if roles == ("Cognitive Services OpenAI User",):
        coverage = openai_coverage or OpenAICoverage(spec, runner)
        return [coverage.check(principal, principal_type, scope, who)]
    try:
        assignments = az_json([
            "role", "assignment", "list", "--scope", scope, "--assignee-object-id", principal,
            "--include-inherited", "--fill-principal-name", "false",
            "--subscription", spec.subscription_id,
        ], runner=runner)
    except IdentityError:
        assignments = None
    rows = []
    for role in roles:
        row = {"principal": who, "principal_object_id": principal,
               "principal_type": principal_type, "role": role, "scope": scope}
        if not isinstance(assignments, list):
            rows.append({**row, "status": "unverified",
                         "detail": "Role assignments are unreadable at this scope."})
            continue
        match = next((item for item in assignments if isinstance(item, dict)
                      and str(item.get("principalId", "")).lower() == principal.lower()
                      and item.get("roleDefinitionName") in ACCEPTED_ROLES[role]
                      and (scope.lower() == str(item.get("scope", "")).lower()
                           or scope.lower().startswith(str(item.get("scope", "")).lower()
                                                       .rstrip("/") + "/"))), None)
        if match:
            rows.append({**row, "status": "assigned", "via_role": match["roleDefinitionName"],
                         "inherited": str(match["scope"]).lower() != scope.lower()})
        else:
            rows.append({**row, "status": "unverified", "detail": UNVERIFIED_ROLE})
    return rows
def _grant_command(spec: ConnectSpec, row: dict[str, Any]) -> list[str]:
    return ["az", "role", "assignment", "create",
            "--assignee-object-id", row["principal_object_id"],
            "--assignee-principal-type", row["principal_type"],
            "--role", row["role"], "--scope", row["scope"],
            "--subscription", spec.subscription_id]
def _rbac(spec: ConnectSpec, operator: dict[str, str], ids: dict[str, str],
          uai: dict[str, Any] | None, runner: Callable[..., Any]) -> list[dict[str, Any]]:
    container = (f"{ids['storage']}/blobServices/default/containers/{spec.storage_container}")
    oid, kind = operator["principal_object_id"], operator["principal_type"]
    coverage = OpenAICoverage(spec, runner)
    rows = _principal_roles(spec, oid, kind, ids["search"],
                            ("Search Service Contributor", "Search Index Data Contributor"),
                            "operator", runner)
    rows += _principal_roles(spec, oid, kind, container, ("Storage Blob Data Contributor",),
                             "operator", runner)
    rows += _principal_roles(spec, oid, kind, ids["openai"], ("Cognitive Services OpenAI User",),
                             "operator", runner, openai_coverage=coverage)
    if uai and uai.get("principal_id"):
        pid = uai["principal_id"]
        rows += _principal_roles(spec, pid, "ServicePrincipal", container,
                                 ("Storage Blob Data Reader",), "search_identity", runner)
        rows += _principal_roles(spec, pid, "ServicePrincipal", ids["openai"],
                                 ("Cognitive Services OpenAI User",), "search_identity", runner,
                                 openai_coverage=coverage)
    return rows
def _role_plan(spec: ConnectSpec, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    proposed = [row for row in rows if row["status"] != "assigned"
                and row.get("grant_recommended", True)]
    if not proposed:
        return None
    operations = [{
        "role": row["role"], "scope": row["scope"], "principal": row["principal"],
        "principal_object_id": row["principal_object_id"],
        "principal_type": row["principal_type"], "requires_approval": True,
        "command": _grant_command(spec, row),
    } for row in proposed]
    identity = {"tenant_id": spec.tenant_id.lower(), "subscription_id": spec.subscription_id.lower(),
                "operations": [{**{key: op[key] for key in ("role", "principal_object_id",
                                                           "principal_type")},
                                "scope": op["scope"].lower()} for op in operations]}
    return {
        "plan_id": stable_id("connect-rbac-plan", identity),
        "operations": operations,
        "warning": "These roles were not found directly or inherited. A group or PIM grant "
                   "may already cover some of them; check before approving. Each assignment "
                   "needs roleAssignments/write (Owner or Role Based Access Control "
                   "Administrator) at its scope.",
    }
