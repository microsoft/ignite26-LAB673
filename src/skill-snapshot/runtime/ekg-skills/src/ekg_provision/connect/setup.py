"""The one follow-up plan connect offers: missing container, model deployments and roles."""
from typing import Any, Callable
from ekg_core.az_identity import IdentityError
from ekg_core.models import ModelDeploymentSpec, ProvisioningSpec, Target, stable_id
from ..capacity import quota_preflight, read_regional_quota
from .roles import _grant_command
from .spec import ConnectSpec, _check, _parts

# The same defaults `ekg-provision plan` uses for new deployments.
MODEL_DEFAULTS = {"embedding": ("text-embedding-3-small", "1"),
                  "chat": ("gpt-5-mini", "2025-08-07")}
DEFAULT_SKU, DEFAULT_CAPACITY = "GlobalStandard", 50


def _container_operation(spec: ConnectSpec, storage_id: str) -> dict[str, Any]:
    return {"kind": "blob_container", "name": spec.storage_container, "scope": storage_id,
            "requires_approval": True,
            "command": ["az", "storage", "container-rm", "create", "--storage-account",
                        storage_id, "--name", spec.storage_container, "--public-access", "off"]}


def _deployment_operations(
    spec: ConnectSpec, openai_id: str, openai: dict[str, Any], checks: list,
    runner: Callable[..., Any],
) -> list[dict[str, Any]]:
    missing = openai.get("missing_deployments") or {}
    if not missing:
        return []
    group, account = _parts(openai_id)
    wanted = tuple(ModelDeploymentSpec(role, name, *MODEL_DEFAULTS[role], DEFAULT_SKU,
                                       DEFAULT_CAPACITY) for role, name in missing.items())
    pspec = ProvisioningSpec(
        target=Target(subscription_id=spec.subscription_id, resource_group=group,
                      location=openai["location"]),
        search_name="unused", storage_name="unused", openai_name=account,
        model_deployments=wanted)
    try:
        report = quota_preflight(pspec, read_regional_quota(pspec, runner=runner),
                                 deployments=wanted)
    except (IdentityError, RuntimeError):
        _check(checks, "capacity.new_deployments", "fail",
               "Could not read regional quota, so the missing models can't be planned. "
               "Check Reader access on the subscription, then run connect again.")
        return []
    rows = {row["deployment"]: row for row in report["deployments"]}
    operations = []
    for deployment in wanted:
        row = rows.get(deployment.name) or {}
        if row.get("blockers"):
            _check(checks, f"capacity.new_{deployment.role}", "fail",
                   "; ".join(row["blockers"]) + ". Request more quota, or pick another region.")
            continue
        operations.append({
            "kind": "model_deployment", "role": deployment.role, "name": deployment.name,
            "model": deployment.model, "version": deployment.version, "sku": deployment.sku,
            "capacity_k_tpm": deployment.capacity, "scope": openai_id,
            "quota": {key: row.get(key) for key in ("quota_name", "quota_current_k_tpm",
                                                    "quota_limit_k_tpm")},
            "requires_approval": True,
            "command": ["az", "cognitiveservices", "account", "deployment", "create",
                        "--resource-group", group, "--name", account,
                        "--deployment-name", deployment.name,
                        "--model-name", deployment.model,
                        "--model-version", deployment.version, "--model-format", "OpenAI",
                        "--sku-name", deployment.sku,
                        "--sku-capacity", str(deployment.capacity),
                        "--subscription", spec.subscription_id],
        })
    return operations


def _role_operations(spec: ConnectSpec, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{
        "role": row["role"], "scope": row["scope"], "principal": row["principal"],
        "principal_object_id": row["principal_object_id"],
        "principal_type": row["principal_type"], "requires_approval": True,
        "command": _grant_command(spec, row),
    } for row in rows if row["status"] != "assigned" and row.get("grant_recommended", True)]


def plain(operation: dict[str, Any]) -> str:
    """One plain-language line per write, for the approval text."""
    if operation.get("kind") == "blob_container":
        return f"Create private Blob container {operation['name']}"
    if operation.get("kind") == "model_deployment":
        return (f"Deploy {operation['model']} as {operation['name']} ({operation['sku']}, "
                f"{operation['capacity_k_tpm']}K tokens/min), after a quota check")
    who = "you" if operation["principal"] == "operator" else "the Search identity"
    where = ("the container" if "/containers/" in operation["scope"] else
             "the Search service" if "/searchServices/" in operation["scope"] else
             "the OpenAI account")
    return f"Grant {operation['role']} for {who} on {where}"


def setup_plan(
    spec: ConnectSpec, ids: dict[str, str | None], storage: dict[str, Any] | None,
    openai: dict[str, Any] | None, roles: list[dict[str, Any]], checks: list,
    runner: Callable[..., Any],
) -> dict[str, Any] | None:
    resources = []
    if storage and storage.get("missing_container") and ids["storage"]:
        resources.append(_container_operation(spec, ids["storage"]))
    if openai and ids["openai"]:
        resources += _deployment_operations(spec, ids["openai"], openai, checks, runner)
    grants = _role_operations(spec, roles)
    if not (resources or grants):
        return None
    identity: dict[str, Any] = {
        "tenant_id": spec.tenant_id.lower(), "subscription_id": spec.subscription_id.lower(),
        "operations": [{**{key: op[key] for key in ("role", "principal_object_id",
                                                   "principal_type")},
                        "scope": op["scope"].lower()} for op in grants]}
    if resources:
        identity["resources"] = [
            {key: op.get(key) for key in ("kind", "name", "model", "version", "sku",
                                          "capacity_k_tpm")} | {"scope": op["scope"].lower()}
            for op in resources]
    operations = resources + grants
    return {
        # A roles-only plan keeps its original ID prefix and value.
        "plan_id": stable_id("connect-setup-plan" if resources else "connect-rbac-plan",
                             identity),
        "operations": operations,
        "writes": [plain(op) for op in operations],
        "warning": "Missing roles were not found directly or inherited; a group or PIM grant "
                   "may already cover some. Role writes need Owner or Role Based Access "
                   "Control Administrator at their scope. Nothing is retried or cleaned up "
                   "automatically.",
    }
