from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ekg_core.models import Plan, ProvisioningSpec, stable_id

_SETTLED = frozenset({"create_response_verified", "existing", "verified"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def journal_spec(spec: ProvisioningSpec) -> dict[str, Any]:
    """Journal spec shape; omits empty optional fields so older records still compare."""
    value = asdict(spec)
    if spec.public_data is None:
        value.pop("public_data")
    if not spec.model_deployments:
        value.pop("model_deployments")
    if spec.build_access is None:
        value.pop("build_access")
    return value


class ProvisioningJournal:
    """Local write-ahead record; it does not establish Azure deletion ownership."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, run_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", run_id):
            raise ValueError("invalid provisioning run ID")
        return self.root / f"{run_id}.json"

    def path(self, run_id: str) -> Path:
        return self._path(run_id)

    def read(self, run_id: str) -> dict[str, Any]:
        record = json.loads(self._path(run_id).read_text(encoding="utf-8"))
        if record.get("run_id") != run_id or record.get("version") != 1:
            raise ValueError(f"invalid provisioning journal for run {run_id}")
        return record

    def begin(self, spec: ProvisioningSpec, desired: Plan, inspection: dict[str, Any],
              *, resume_from: dict[str, str] | None = None) -> str:
        run_id = uuid4().hex
        record = {
            "version": 1,
            "run_id": run_id,
            "started_at": _now(),
            "plan_id": desired.plan_id,
            "spec": journal_spec(spec),
            "operations": {
                operation.id: {
                    "resource_id": inspection["resources"][operation.id]["resource_id"],
                    "preflight": inspection["resources"][operation.id]["status"],
                    "status": "pending",
                    "depends_on": list(operation.depends_on),
                }
                for operation in desired.operations
            },
        }
        if resume_from is not None:
            record["resume_from"] = resume_from
        _write_json(self._path(run_id), record)
        return run_id

    def record_connection(self, spec: ProvisioningSpec, desired: Plan, plan_id: str,
                          connection: dict[str, Any]) -> str:
        """Record a completed read-only connect in the Provision run shape.

        ``desired`` supplies the same operation IDs Provision would use. Every operation is
        ``existing``: connect created nothing, so cleanup review never offers deletion.
        """
        run_id = uuid4().hex
        now = _now()
        resources = connection["resources"]
        ids = {"search_service": resources["search"], "storage_account": resources["storage"],
               "openai_resource": resources["openai"]}
        prefixes = {"search_service": "search.", "storage_account": "storage.",
                    "openai_resource": "openai."}

        def entry(operation: Any) -> dict[str, Any]:
            if operation.resource == "model_deployment":
                resource_id = f"{resources['openai']}/deployments/{operation.name}"
                role = operation.id.split("-")[1]
                prefix = f"openai.{role}_deployment"
            else:
                resource_id, prefix = ids[operation.resource], prefixes[operation.resource]
            return {
                "resource_id": resource_id, "preflight": "present", "status": "existing",
                "depends_on": list(operation.depends_on), "updated_at": now,
                "evidence": {"checks": [item for item in connection.get("checks", [])
                                        if item["id"].startswith(prefix)]},
            }

        record = {
            "version": 1, "run_id": run_id, "mode": "connect",
            "started_at": now, "finished_at": now, "completed": True,
            "plan_id": plan_id, "spec": journal_spec(spec),
            "operations": {operation.id: entry(operation) for operation in desired.operations},
            "connection": {key: connection.get(key) for key in (
                "status", "build_binding", "roles", "role_plan", "capacity")},
            "telemetry": list(connection.get("telemetry") or []),
        }
        _write_json(self._path(run_id), record)
        return run_id
    def update(self, run_id: str, operation_id: str, status: str, **evidence: Any) -> None:
        record = self.read(run_id)
        operation = record["operations"][operation_id]
        # A verified outcome supersedes the "outcome not confirmed" reason.
        if status in _SETTLED and "reason" not in evidence:
            operation.pop("reason", None)
        operation.update(status=status, updated_at=_now(), **evidence)
        _write_json(self._path(run_id), record)

    def record_telemetry(self, run_id: str, event: dict[str, Any]) -> None:
        """Append one shared-shape timing event (see ekg_core.telemetry) to the run."""
        record = self.read(run_id)
        record.setdefault("telemetry", []).append(event)
        _write_json(self._path(run_id), record)

    def finish(self, run_id: str, completed: bool) -> None:
        record = self.read(run_id)
        record.update(completed=completed, finished_at=_now())
        _write_json(self._path(run_id), record)

    def cleanup_plan(self, run_id: str) -> dict[str, Any]:
        record = self.read(run_id)
        operations = []
        for operation_id, item in record["operations"].items():
            status = item["status"]
            reason = (
                "resource-group ownership and emptiness are unproven; do not delete"
                if operation_id == "create-resource-group" else
                "pre-existing or concurrently created; do not delete"
                if status == "existing" else
                "creation outcome uncertain; do not infer ownership from a later GET"
                if status == "uncertain" else
                "creation response recorded, but conditional deletion is not verified"
                if status == "create_response_verified" else
                "no confirmed create; do not delete"
            )
            operations.append({
                "operation_id": operation_id,
                "resource_id": item["resource_id"],
                "preflight": item["preflight"],
                "status": status,
                "evidence": item.get("evidence", {}),
                "depends_on": item.get("depends_on", []),
                "blocked_reason": reason,
                "action": "manual_review_only",
            })
        snapshot = {
            "run_id": run_id,
            "source_plan_id": record["plan_id"],
            "target": record["spec"]["target"],
            "operations": operations,
            "completed": record.get("completed"),
        }
        return {
            "plan_id": stable_id("cleanup-plan", record),
            **snapshot,
            "requires_approval": True,
            "blocked_by": [
                "Automated deletion is unavailable: create/GET does not prove "
                "conditional deletion, ownership after timeout, or group emptiness."
            ],
            "manual_steps": [
                "Review each operation and its original run evidence independently.",
                "Before any separate manual deletion, confirm ownership, current "
                "resource version, dependencies, and (for groups) emptiness.",
                "Review dependent endpoint zone groups, endpoints, DNS links, "
                "subnets and VNets before considering parent resources.",
                "Approval acknowledges this plan only; it performs no Azure deletion.",
            ],
        }

    def approve_cleanup(self, run_id: str, approved_plan_id: str) -> dict[str, Any]:
        from ekg_core.execution import ApprovalRequired

        plan = self.cleanup_plan(run_id)
        if not approved_plan_id or approved_plan_id != plan["plan_id"]:
            raise ApprovalRequired(f"explicit approval of cleanup plan {plan['plan_id']} is required")
        # Reject a record that changed while the approval was being prepared.
        if self.cleanup_plan(run_id)["plan_id"] != approved_plan_id:
            raise ApprovalRequired("cleanup plan changed; review the new snapshot")
        receipt = {
            "run_id": run_id,
            "approved_plan_id": approved_plan_id,
            "approved_at": _now(),
            "status": "manual_review_approved_no_deletion",
        }
        _write_json(self.root / f"{run_id}.approval.json", receipt)
        return receipt
