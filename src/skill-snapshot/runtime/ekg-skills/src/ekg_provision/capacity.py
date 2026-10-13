"""Read-only model quota preflight and approval-gated deployment capacity updates."""

from __future__ import annotations

import json
import subprocess
from typing import Any, Callable

from ekg_core.execution import ApprovalRequired
from ekg_core.models import ModelDeploymentSpec, ProvisioningSpec, stable_id
from ekg_core.telemetry import TelemetryRecorder
from ekg_core.az_identity import IdentityError, active_az_identity, az_executable, az_json

API_VERSION = "2024-10-01"
ARM = "https://management.azure.com"


class CapacityError(RuntimeError):
    pass


def _account_id(spec: ProvisioningSpec) -> str:
    target = spec.target
    return (f"/subscriptions/{target.subscription_id}/resourceGroups/{target.resource_group}"
            f"/providers/Microsoft.CognitiveServices/accounts/{spec.openai_name}")


def deployment_url(spec: ProvisioningSpec, name: str) -> str:
    return f"{ARM}{_account_id(spec)}/deployments/{name}?api-version={API_VERSION}"


def _location_url(spec: ProvisioningSpec, collection: str) -> str:
    return (f"{ARM}/subscriptions/{spec.target.subscription_id}/providers/"
            f"Microsoft.CognitiveServices/locations/{spec.target.location}/{collection}"
            f"?api-version={API_VERSION}")


def _get(url: str, runner: Callable[..., Any]) -> Any:
    return az_json(["rest", "--method", "get", "--url", url], runner=runner)


def read_regional_quota(spec: ProvisioningSpec, *,
                        runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    """Return subscription usages and the model catalog for the target region."""
    usages = _get(_location_url(spec, "usages"), runner)
    models = _get(_location_url(spec, "models"), runner)
    if not isinstance(usages, dict) or not isinstance(models, dict):
        raise CapacityError("Azure returned invalid usages or models")
    return {"usages": usages.get("value") or [], "models": models.get("value") or []}


def _usage_name(sku: str, model: str) -> str:
    return f"OpenAI.{sku}.{model}"


def _usage(usages: list[Any], name: str) -> dict[str, Any] | None:
    for item in usages:
        if isinstance(item, dict) and (item.get("name") or {}).get("value") == name:
            return item
    return None


def _offered(models: list[Any], deployment: ModelDeploymentSpec) -> dict[str, Any]:
    versions = [
        item.get("model") or {} for item in models
        if isinstance(item, dict) and (item.get("model") or {}).get("name") == deployment.model
        and (item.get("model") or {}).get("format", "OpenAI") == "OpenAI"
    ]
    match = next((model for model in versions if model.get("version") == deployment.version), None)
    skus = sorted({sku.get("name") for sku in (match or {}).get("skus") or []
                   if isinstance(sku, dict) and sku.get("name")})
    return {
        "model_offered": bool(versions),
        "version_offered": match is not None,
        "sku_offered": deployment.sku in skus,
        "offered_versions": sorted({str(model.get("version")) for model in versions}),
        "offered_skus": skus,
    }


def quota_preflight(
    spec: ProvisioningSpec, quota: dict[str, Any], *,
    existing: dict[str, int] | None = None,
    deployments: tuple[ModelDeploymentSpec, ...] | None = None,
) -> dict[str, Any]:
    """Evaluate requested deployments against regional quota; performs no I/O.

    ``existing`` maps deployment name to capacity already counted in usage, so an in-place
    change or a re-run only needs the delta.
    """
    existing = existing or {}
    requested = spec.model_deployments if deployments is None else deployments
    usages = quota.get("usages") or []
    models = quota.get("models") or []
    rows: list[dict[str, Any]] = []
    pending: dict[str, int] = {}
    for deployment in requested:
        name = _usage_name(deployment.sku, deployment.model)
        usage = _usage(usages, name)
        offered = _offered(models, deployment)
        catalog: list[str] = []
        if not offered["model_offered"]:
            catalog.append(f"{deployment.model} is not offered in {spec.target.location}")
        elif not offered["version_offered"]:
            catalog.append(f"{deployment.model} version {deployment.version} is not offered; "
                           f"offered: {', '.join(offered['offered_versions'])}")
        elif not offered["sku_offered"]:
            catalog.append(f"SKU {deployment.sku} is not offered for {deployment.model} "
                           f"{deployment.version}; offered: {', '.join(offered['offered_skus'])}")
        quota_blockers: list[str] = []
        current = limit = None
        own = existing.get(deployment.name, 0)
        delta = deployment.capacity - own
        if usage is None:
            quota_blockers.append(f"no {name} quota in {spec.target.location}; request quota first")
        else:
            current, limit = int(usage.get("currentValue") or 0), int(usage.get("limit") or 0)
            available = limit - current - pending.get(name, 0)
            if delta > available:
                quota_blockers.append(f"{deployment.name} needs {delta}K more TPM of {name}; "
                                      f"{available}K of {limit}K is available")
            pending[name] = pending.get(name, 0) + max(delta, 0)
        rows.append({
            "role": deployment.role, "deployment": deployment.name,
            "model": deployment.model, "version": deployment.version, "sku": deployment.sku,
            "requested_capacity_k_tpm": deployment.capacity,
            "existing_capacity_k_tpm": own, "quota_name": name,
            "quota_current_k_tpm": current, "quota_limit_k_tpm": limit,
            **offered, "catalog_blockers": catalog, "quota_blockers": quota_blockers,
            "blockers": catalog + quota_blockers, "ok": not (catalog or quota_blockers),
        })
    return {
        "phase": "provision.quota", "location": spec.target.location,
        "evidence": {"origin": "arm_location_usages_and_models", "api_version": API_VERSION},
        "deployments": rows,
        "blocked": any(not row["ok"] for row in rows),
        "note": "Quota is per subscription, region, SKU and model, in thousands of TPM.",
    }


def read_existing_capacity(spec: ProvisioningSpec, *,
                           runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    """Return {name: deployment} for the account; empty when the account is unreadable."""
    try:
        listed = _get(f"{ARM}{_account_id(spec)}/deployments?api-version={API_VERSION}", runner)
    except IdentityError:
        return {}
    if not isinstance(listed, dict):
        raise CapacityError("Azure returned an invalid deployment list")
    return {item["name"]: item for item in listed.get("value") or []
            if isinstance(item, dict) and isinstance(item.get("name"), str)}


def quota_check(spec: ProvisioningSpec, *, tenant_id: str,
                runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    if not spec.model_deployments:
        raise ValueError("quota requires at least one --embedding-deployment or --chat-deployment")
    active_az_identity(tenant_id, spec.target.subscription_id, runner=runner)
    recorder = TelemetryRecorder("provision")
    with recorder.span("quota-preflight", resource="model_deployment") as span:
        quota = read_regional_quota(spec, runner=runner)
        deployed = read_existing_capacity(spec, runner=runner)
        existing = {name: int((item.get("sku") or {}).get("capacity") or 0)
                    for name, item in deployed.items()}
        report = quota_preflight(spec, quota, existing=existing)
        span["counts"] = {"deployments": len(report["deployments"]),
                          "blocked": sum(not row["ok"] for row in report["deployments"])}
    report["tenant_id"] = tenant_id
    report["telemetry"] = recorder.events
    return report


def _current(spec: ProvisioningSpec, name: str, runner: Callable[..., Any]) -> dict[str, Any]:
    try:
        observed = _get(deployment_url(spec, name), runner)
    except IdentityError as error:
        raise CapacityError(f"deployment {name} is missing or unreadable") from error
    sku = (observed or {}).get("sku") or {}
    model = ((observed or {}).get("properties") or {}).get("model") or {}
    if (not isinstance(observed, dict) or observed.get("name") != name
            or not isinstance(sku.get("name"), str) or not isinstance(sku.get("capacity"), int)
            or not model.get("name")):
        raise CapacityError(f"deployment {name} returned an unexpected shape")
    return {"sku": sku["name"], "capacity_k_tpm": sku["capacity"],
            "model": model.get("name"), "version": model.get("version"),
            "provisioning_state": (observed.get("properties") or {}).get("provisioningState")}


def _command(spec: ProvisioningSpec, name: str, sku: str, capacity: int) -> list[str]:
    body = json.dumps({"sku": {"name": sku, "capacity": capacity}}, separators=(",", ":"))
    return ["az", "rest", "--method", "patch", "--url", deployment_url(spec, name),
            "--body", body]


def capacity_plan(spec: ProvisioningSpec, deployment: str, capacity: int, *, tenant_id: str,
                  runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    """Read-only: current vs desired capacity, quota headroom and the exact write."""
    probe = ModelDeploymentSpec("chat", deployment, "probe", "1", capacity=capacity)
    active_az_identity(tenant_id, spec.target.subscription_id, runner=runner)
    current = _current(spec, probe.name, runner)
    if current["sku"] not in ("GlobalStandard", "DataZoneStandard", "Standard"):
        raise CapacityError(f"{current['sku']} is not a token-based SKU; PTU changes are manual")
    target = ModelDeploymentSpec("chat", deployment, current["model"],
                                 str(current["version"]), current["sku"], capacity)
    preflight = quota_preflight(spec, read_regional_quota(spec, runner=runner),
                                existing={deployment: current["capacity_k_tpm"]},
                                deployments=(target,))
    # Update-in-place ignores catalog blockers: the model is already deployed.
    row = preflight["deployments"][0]
    quota_blockers = list(row["quota_blockers"])
    command = _command(spec, deployment, current["sku"], capacity)
    identity = {
        "account_id": _account_id(spec).lower(), "deployment": deployment,
        "current": current, "desired_capacity_k_tpm": capacity,
    }
    return {
        "plan_id": stable_id("capacity-plan", identity),
        "tenant_id": tenant_id,
        "deployment": deployment, "current": current,
        "desired_capacity_k_tpm": capacity,
        "change": "none" if capacity == current["capacity_k_tpm"] else
                  ("increase" if capacity > current["capacity_k_tpm"] else "decrease"),
        "quota": {key: row[key] for key in ("quota_name", "quota_current_k_tpm",
                                            "quota_limit_k_tpm")},
        "blockers": quota_blockers,
        "write": {"requires_approval": True, "command": command},
        "warning": "Only the SKU capacity changes; model, version and policy are untouched. "
                   "A capacity above quota needs a quota request first.",
    }


def capacity_update(spec: ProvisioningSpec, deployment: str, capacity: int, *, tenant_id: str,
                    approved_plan_id: str, confirmed: bool,
                    runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    if not confirmed:
        raise ApprovalRequired("capacity writes require explicit confirmation")
    review = capacity_plan(spec, deployment, capacity, tenant_id=tenant_id, runner=runner)
    if approved_plan_id != review["plan_id"]:
        raise ApprovalRequired(
            f"explicit approval of capacity plan {review['plan_id']} is required; "
            "the deployment may have drifted since review"
        )
    if review["blockers"]:
        raise CapacityError("; ".join(review["blockers"]))
    if review["change"] == "none":
        return {**review, "status": "unchanged"}
    recorder = TelemetryRecorder("provision")
    command = [az_executable(runner), *review["write"]["command"][1:], "--output", "json"]
    with recorder.span("capacity-update", resource="model_deployment") as span:
        try:
            result = runner(command, capture_output=True, text=True, timeout=120, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise CapacityError(f"{deployment}: capacity update outcome uncertain; re-read "
                                "the deployment before retrying") from error
        after = _current(spec, deployment, runner)
        span["counts"] = {"capacity_k_tpm": after["capacity_k_tpm"]}
    if after["capacity_k_tpm"] != capacity:
        if result.returncode != 0:
            raise CapacityError(f"{deployment}: capacity update failed; "
                                "check quota and Cognitive Services Contributor access")
        raise CapacityError(f"{deployment}: capacity is {after['capacity_k_tpm']}K after update; "
                            "re-read before retrying")
    return {**review, "status": "updated", "after": after, "telemetry": recorder.events}
