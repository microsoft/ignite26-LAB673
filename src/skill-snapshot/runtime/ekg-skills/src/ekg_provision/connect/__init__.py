import subprocess
from typing import Any, Callable
from ekg_core.execution import ApprovalRequired
from ekg_core.telemetry import TelemetryRecorder
from .output import _binding, connection_spec, public_payload
from .resources import _capacity, _openai, _search, _storage
from .roles import _principal_roles, _rbac
from .setup import setup_plan
from .spec import DEFAULT_RUNNER, EMBEDDING_DIMENSIONS, ConnectError, ConnectSpec, _candidates, _resource_id
from ekg_core.az_identity import active_az_identity, az_executable
def _resource_ids(spec: ConnectSpec) -> dict[str, str | None]:
    ids = {kind: _resource_id(spec, kind, getattr(spec, kind))
           for kind in ("search", "storage", "openai")}
    if spec.search_identity_resource_id:
        _resource_id(spec, "identity", spec.search_identity_resource_id)
    return ids
def _discover_resources(
    spec: ConnectSpec, ids: dict[str, str | None], checks: list[dict[str, Any]],
    candidates: dict[str, Any], runner: Callable[..., Any], recorder: TelemetryRecorder,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None, dict[str, Any]]:
    selected: dict[str, Any] = {}
    search = storage = openai = None
    with recorder.span("discover", resource="arm_and_data_plane") as span:
        for kind in ("search", "storage", "openai"):
            if ids[kind] is None:
                candidates[f"{kind}"] = _candidates(spec, kind, runner)
        if ids["search"]:
            search = _search(spec, ids["search"], checks, runner, selected, candidates)
        if ids["storage"]:
            storage = _storage(spec, ids["storage"], checks, runner, candidates)
        if ids["openai"]:
            openai = _openai(spec, ids["openai"], checks, runner, candidates)
        span["counts"] = {"checks": len(checks)}
    return search, storage, openai, selected
def _capacity_report(
    spec: ConnectSpec, ids: dict[str, str | None], openai: dict[str, Any] | None,
    checks: list[dict[str, Any]], runner: Callable[..., Any], recorder: TelemetryRecorder,
) -> dict[str, Any]:
    if not (openai and openai["deployments"]):
        return {}
    with recorder.span("capacity", resource="model_deployment"):
        return _capacity(spec, ids["openai"], openai, checks, runner)
def _embedding_dimensions(spec: ConnectSpec, openai: dict[str, Any] | None,
                          candidates: dict[str, Any]) -> int | None:
    dimensions = spec.embedding_dimensions
    embedding = (openai or {}).get("deployments", {}).get("embedding")
    if embedding and dimensions is None:
        dimensions = EMBEDDING_DIMENSIONS.get(str(embedding["model"]))
        if dimensions is None:
            candidates["embedding_dimensions"] = "unknown for this model; pass it explicitly"
    return dimensions
def _role_review(
    spec: ConnectSpec, ids: dict[str, str | None], selected: dict[str, Any],
    operator: dict[str, str], recorder: TelemetryRecorder, runner: Callable[..., Any],
) -> list[dict[str, Any]]:
    if not (all(ids.values()) and spec.storage_container):
        return []
    with recorder.span("rbac-check", resource="role_assignment") as span:
        roles = _rbac(spec, operator, ids, selected.get("search_identity"), runner)
        span["counts"] = {"roles": len(roles),
                          "unverified": sum(row["status"] != "assigned" for row in roles)}
    return roles
def _connect_status(
    ids: dict[str, str | None], spec: ConnectSpec, checks: list[dict[str, Any]],
    candidates: dict[str, Any], role_plan: dict[str, Any] | None, uai: dict[str, Any] | None,
    dimensions: int | None, search: dict[str, Any] | None, storage: dict[str, Any] | None,
    openai: dict[str, Any] | None,
) -> tuple[str, list[str], bool]:
    failed = [check["id"] for check in checks if check["status"] == "fail"]
    planned = set((openai or {}).get("missing_deployments") or ())
    complete = (all(ids.values()) and spec.storage_container and uai and dimensions
                and openai and set(openai["deployments"]) == {"embedding", "chat"}
                and search and storage and not (storage or {}).get("missing_container"))
    covered = (all(ids.values()) and spec.storage_container and uai and openai
               and set(openai["deployments"]) | planned == {"embedding", "chat"}
               and search and storage)
    status = ("blocked" if failed else
              "needs_setup" if role_plan and not complete and covered and not candidates else
              "incomplete" if not complete or candidates else
              "unverified" if role_plan or any(c["status"] == "unverified" for c in checks)
              else "ready")
    return status, failed, bool(complete)
def connect(spec: ConnectSpec, *, runner: Callable[..., Any] | None = None) -> dict[str, Any]:
    """Discover and validate existing resources. Makes Azure reads only."""
    runner = runner or DEFAULT_RUNNER
    recorder = TelemetryRecorder("connect")
    checks: list[dict[str, Any]] = []
    candidates: dict[str, Any] = {}
    with recorder.span("identity"):
        operator = active_az_identity(spec.tenant_id, spec.subscription_id, runner=runner)
    ids = _resource_ids(spec)
    search, storage, openai, selected = _discover_resources(
        spec, ids, checks, candidates, runner, recorder,
    )
    capacity = _capacity_report(spec, ids, openai, checks, runner, recorder)
    dimensions = _embedding_dimensions(spec, openai, candidates)
    roles = _role_review(spec, ids, selected, operator, recorder, runner)
    for row in roles:
        if row.get("permission_coverage") is not None and row["status"] != "assigned":
            checks.append({"id": f"openai.roles.{row['principal']}",
                           "status": "fail" if row["effective_access"] == "denied" else "unverified",
                           "detail": row["detail"], "evidence": row})
    role_plan = setup_plan(spec, ids, storage, openai, roles, checks, runner)
    status, failed, complete = _connect_status(
        ids, spec, checks, candidates, role_plan, selected.get("search_identity"),
        dimensions, search, storage, openai,
    )
    binding = (_binding(spec, ids, search, storage, openai, selected["search_identity"], dimensions)
               if complete and not failed else None)
    payload = {
        "phase": "provision.connect", "status": status,
        "tenant_id": spec.tenant_id, "subscription_id": spec.subscription_id,
        "operator": operator, "resources": {kind: ids[kind] for kind in ids},
        "checks": checks, "blocked_by": failed, "candidates": candidates,
        "capacity": {key: value for key, value in capacity.items()
                     if key != "model_deployments"},
        "roles": roles, "setup_plan": role_plan,
        # Older callers read role_plan; it is the same plan.
        "role_plan": role_plan, "build_binding": binding,
        "evidence": {"origin": "arm_and_data_plane_reads", "writes": 0},
        "uncertainty": [
            "Role checks see direct and inherited assignments to each principal only; "
            "group, PIM-eligible and conditional grants are reported as unverified.",
            "Data-plane probes run from this host; the Search service's own network path "
            "to Storage and Azure OpenAI is not exercised until Build.",
        ],
        "telemetry": recorder.events,
    }
    payload["_model_deployments"] = capacity.get("model_deployments", ())
    return payload
def _run_resource(operation: dict[str, Any], runner: Callable[..., Any]) -> None:
    command = [az_executable(runner), *operation["command"][1:], "--output", "json"]
    try:
        done = runner(command, capture_output=True, text=True, timeout=900, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ConnectError(f"{operation['name']}: create outcome uncertain; re-run connect "
                           "before any retry") from error
    if getattr(done, "returncode", 0) != 0:
        detail = str(getattr(done, "stderr", "") or "").strip().splitlines()[-1:] or [""]
        raise ConnectError(f"{operation['name']}: create failed ({detail[0]}). Nothing was "
                           "retried or cleaned up; re-run connect before any retry.")


def _run_grant(spec: ConnectSpec, operation: dict[str, Any],
               runner: Callable[..., Any]) -> dict[str, Any]:
    command = [az_executable(runner), *operation["command"][1:], "--output", "json"]
    try:
        runner(command, capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ConnectError(f"{operation['role']}: assignment outcome uncertain; re-run "
                           "connect before any retry") from error
    reread = _principal_roles(spec, operation["principal_object_id"],
                              operation["principal_type"], operation["scope"],
                              (operation["role"],), operation["principal"], runner)[0]
    if reread["status"] != "assigned":
        raise ConnectError(
            f"{operation['role']}: assignment not visible after create; it may have "
            "failed (roleAssignments/write needed) or still be propagating. Re-run "
            "connect before any retry.")
    return {**{key: operation[key] for key in ("role", "scope", "principal")},
            "status": reread["status"]}


def connect_apply(spec: ConnectSpec, *, approved_plan_id: str, confirmed: bool,
                  runner: Callable[..., Any] | None = None) -> dict[str, Any]:
    """Run the reviewed setup plan: the only writes in this module."""
    if not confirmed:
        raise ApprovalRequired("connect setup writes require explicit confirmation")
    runner = runner or DEFAULT_RUNNER
    review = connect(spec, runner=runner)
    plan = review["setup_plan"]
    if plan is None:
        return {**public_payload(review), "grant": {"status": "nothing_to_do"}}
    if approved_plan_id != plan["plan_id"]:
        raise ApprovalRequired(
            f"explicit approval of connect setup plan {plan['plan_id']} is required; "
            "resources or assignments may have changed since review")
    recorder = TelemetryRecorder("connect")
    created, results = [], []
    with recorder.span("connect-apply", resource="setup") as span:
        for operation in plan["operations"]:
            if "kind" in operation:
                _run_resource(operation, runner)
                created.append({key: operation[key] for key in ("kind", "name")})
            else:
                results.append(_run_grant(spec, operation, runner))
        span["counts"] = {"resources": len(created), "assignments": len(results)}
    final = connect(spec, runner=runner)
    return {**public_payload(final), "grant": {"status": "applied", "plan_id": plan["plan_id"],
                                               "created": created, "assignments": results},
            "evidence": {**final["evidence"], "writes": len(created) + len(results)},
            "telemetry": final["telemetry"] + recorder.events}


def connect_grant(spec: ConnectSpec, *, approved_plan_id: str, confirmed: bool,
                  runner: Callable[..., Any] | None = None) -> dict[str, Any]:
    """Alias of connect_apply, kept for existing callers."""
    return connect_apply(spec, approved_plan_id=approved_plan_id, confirmed=confirmed,
                         runner=runner)
