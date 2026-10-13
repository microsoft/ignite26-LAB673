"""Exact, opt-in Azure CLI role assignments for the synthetic proof."""

from __future__ import annotations

import re
import subprocess
from dataclasses import asdict, dataclass
from typing import Any, Callable

from ekg_core.execution import ApprovalRequired
from ekg_core.models import ProvisioningSpec, stable_id
from ekg_core.az_identity import IdentityError, active_az_identity, az_executable, az_json
from .planner import plan
from .public_test import validate_public_test


class RbacError(RuntimeError):
    pass


@dataclass(frozen=True)
class RbacSpec:
    principal_object_id: str
    principal_type: str
    container: str


def rbac_plan(spec: ProvisioningSpec, rbac: RbacSpec) -> dict[str, Any]:
    validate_public_test(spec)
    if spec.public_test is None:
        raise ValueError("RBAC helper requires an explicit public-test plan")
    if not isinstance(rbac, RbacSpec) or not re.fullmatch(
        r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}",
        rbac.principal_object_id,
    ):
        raise ValueError("principal_object_id must be the exact Azure token oid GUID")
    if rbac.principal_type not in ("User", "ServicePrincipal"):
        raise ValueError("principal_type must be User or ServicePrincipal, not a group guess")
    if not isinstance(rbac.container, str) or not re.fullmatch(
        r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", rbac.container
    ) or "--" in rbac.container:
        raise ValueError("container must be an existing approved Blob container name")
    target = spec.target
    base = f"/subscriptions/{target.subscription_id}/resourceGroups/{target.resource_group}"
    search = f"{base}/providers/Microsoft.Search/searchServices/{spec.search_name}"
    storage = (f"{base}/providers/Microsoft.Storage/storageAccounts/{spec.storage_name}"
               f"/blobServices/default/containers/{rbac.container}")
    openai = f"{base}/providers/Microsoft.CognitiveServices/accounts/{spec.openai_name}"
    roles = (
        ("Search Service Contributor", search),
        ("Search Index Data Contributor", search),
        ("Storage Blob Data Contributor", storage),
        ("Cognitive Services OpenAI User", openai),
    )
    operations = [
        {"role": role, "scope": scope, "principal_object_id": rbac.principal_object_id,
         "principal_type": rbac.principal_type, "requires_approval": True}
        for role, scope in roles
    ]
    return {
        "plan_id": stable_id("public-rbac-plan", {
            "provision_plan_id": plan(spec).plan_id, "rbac": asdict(rbac),
            "operations": operations,
        }),
        "provision_plan_id": plan(spec).plan_id,
        "operations": operations,
        "warning": "Only exact direct grants are checked. Inherited/group/PIM grants "
                   "are not inferred; propagation and data-plane access need verification.",
    }


def _exact_assignment(
    assignments: Any, *, principal: str, scope: str, definition_id: str,
) -> bool:
    if not isinstance(assignments, list):
        raise RbacError("Azure CLI returned an invalid role assignment list")
    return any(
        isinstance(item, dict)
        and str(item.get("principalId", "")).lower() == principal.lower()
        and str(item.get("scope", "")).lower() == scope.lower()
        and str(item.get("roleDefinitionId", "")).rsplit("/", 1)[-1].lower()
            == definition_id.rsplit("/", 1)[-1].lower()
        for item in assignments
    )


def _check_operation(
    operation: dict[str, Any], subscription_id: str,
    runner: Callable[..., Any],
) -> dict[str, Any]:
    scope, role = operation["scope"], operation["role"]
    definitions = az_json([
        "role", "definition", "list", "--name", role, "--scope", scope,
        "--subscription", subscription_id,
    ], runner=runner)
    if not isinstance(definitions, list) or len(definitions) != 1 or (
        definitions[0].get("roleName") != role
        or not isinstance(definitions[0].get("id"), str)
    ):
        raise RbacError(f"cannot uniquely resolve built-in role {role}")
    definition_id = definitions[0]["id"]
    assignments = az_json([
        "role", "assignment", "list", "--scope", scope,
        "--assignee-object-id", operation["principal_object_id"],
        "--fill-principal-name", "false", "--fill-role-definition-name", "false",
        "--subscription", subscription_id,
    ], runner=runner)
    return {**operation, "role_definition_id": definition_id, "assigned": _exact_assignment(
        assignments, principal=operation["principal_object_id"], scope=scope,
        definition_id=definition_id,
    )}


def rbac_check(
    spec: ProvisioningSpec, rbac: RbacSpec, *,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    desired = rbac_plan(spec, rbac)
    identity = active_az_identity(
        spec.public_test.tenant_id, spec.target.subscription_id, runner=runner
    )
    if (identity["principal_object_id"].lower() != rbac.principal_object_id.lower()
        or identity["principal_type"] != rbac.principal_type):
        raise IdentityError("RBAC target principal differs from the active az identity")
    api_versions = {
        "Microsoft.Search/searchServices": "2025-05-01",
        "Microsoft.Storage/storageAccounts": "2023-05-01",
        "Microsoft.CognitiveServices/accounts": "2023-05-01",
    }
    for scope in dict.fromkeys(op["scope"] for op in desired["operations"]):
        api_version = next((version for kind, version in api_versions.items()
                            if f"/providers/{kind}/" in scope), None)
        if not api_version:
            raise RbacError("unrecognized RBAC resource scope")
        try:
            observed = az_json([
                "resource", "show", "--ids", scope, "--api-version", api_version,
                "--subscription", spec.target.subscription_id,
            ], runner=runner)
        except IdentityError as error:
            raise RbacError(f"RBAC target resource missing or inaccessible: {scope}") from error
        if not isinstance(observed, dict) or str(observed.get("id", "")).lower() != scope.lower():
            raise RbacError(f"RBAC target ID differs: {scope}")
    checked = [
        _check_operation(operation, spec.target.subscription_id, runner)
        for operation in desired["operations"]
    ]
    return {"plan_id": desired["plan_id"], "identity": identity,
            "operations": checked, "missing": [op["role"] for op in checked
                                                 if not op["assigned"]]}


def rbac_grant(
    spec: ProvisioningSpec, rbac: RbacSpec, *, approved_plan_id: str,
    confirmed: bool, runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    if not confirmed:
        raise ApprovalRequired("RBAC writes require explicit confirmation")
    desired = rbac_plan(spec, rbac)
    if approved_plan_id != desired["plan_id"]:
        raise ApprovalRequired(f"explicit approval of RBAC plan {desired['plan_id']} is required")
    checked = rbac_check(spec, rbac, runner=runner)
    for operation in checked["operations"]:
        if operation["assigned"]:
            continue
        args = [
            az_executable(runner), "role", "assignment", "create",
            "--assignee-object-id", rbac.principal_object_id,
            "--assignee-principal-type", rbac.principal_type,
            "--role", operation["role_definition_id"].rsplit("/", 1)[-1],
            "--scope", operation["scope"],
            "--subscription", spec.target.subscription_id, "--output", "json",
        ]
        try:
            result = runner(args, capture_output=True, text=True, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RbacError(
                f"{operation['role']}: role assignment outcome uncertain; inspect exact scope"
            ) from error
        # Even on a conflict, only a fresh exact assignment read establishes success.
        try:
            reread = _check_operation(operation, spec.target.subscription_id, runner)
        except IdentityError as error:
            raise RbacError(f"{operation['role']}: assignment outcome uncertain; "
                            "verify roleAssignments/read and manually inspect scope") from error
        if not reread["assigned"]:
            if result.returncode != 0:
                raise RbacError(
                    f"{operation['role']}: assignment failed or conflicted; "
                    "Microsoft.Authorization/roleAssignments/write at this scope "
                    "requires Owner or Role Based Access Control Administrator"
                )
            raise RbacError(f"{operation['role']}: assignment not visible; wait for "
                            "propagation and recheck before any smoke")
    final = rbac_check(spec, rbac, runner=runner)
    if final["missing"]:
        raise RbacError("RBAC assignments are not all visible; wait and recheck")
    return final
