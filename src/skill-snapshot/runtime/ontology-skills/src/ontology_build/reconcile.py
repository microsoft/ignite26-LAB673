"""`reconcile`. Read-only except stale-lock release; never deletes artifacts."""

from __future__ import annotations

import re

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ontology_build import budget
from ontology_core import hashing, journal as journal_mod, state
from ontology_core.errors import Blocked
from ontology_core.journal import Journal
from ontology_core.model import Approval, ExportManifest, Plan, Version
from ontology_core.state import StatePaths


@dataclass
class OpenRun:
    plan_id: str
    calls_left: list[str]
    spent_usd: float


@dataclass
class ReconcileReport:
    drift: list[str] = field(default_factory=list)
    """State-relative paths that are missing or no longer hash to the journaled value."""
    open_runs: list[OpenRun] = field(default_factory=list)
    lock_released: dict[str, Any] | None = None


def check(paths: StatePaths) -> ReconcileReport:
    """All reconcile checks without side effects (doctor's `journal` check uses this too)."""
    entries = list(Journal(paths).read()) if paths.journal.is_file() else []
    drift: set[str] = set()
    written: dict[str, str] = {}
    for entry in entries:
        if entry["event"] == "artifact_written":
            written[entry["path"]] = entry["sha256"]
    for rel, sha in written.items():
        if not _matches(paths.root / rel, sha):
            drift.add(rel)
    drift.update(_version_drift(paths))
    drift.update(_export_drift(paths))
    drift.update(_response_drift(paths, entries))
    return ReconcileReport(drift=sorted(drift), open_runs=_open_runs(paths, entries))


def run(paths: StatePaths, *, release_lock: bool = False) -> dict[str, Any]:
    """Release a stale lock (same host, dead pid; another host only with `release_lock`), then `check`.

    Returns `{status:"ok", drift:[], open_runs:[...], lock_released, next_step}`.

    Raises: JOURNAL_DRIFT (drift non-empty, paths in `details`), STATE_LOCKED (live lock).
    """
    released = journal_mod.release_stale(paths, Journal(paths), force=release_lock)
    report = check(paths)
    report.lock_released = released.to_dict() if released is not None else None
    open_runs = [asdict(r) for r in report.open_runs]
    if report.drift:
        raise Blocked("JOURNAL_DRIFT", f"{len(report.drift)} state file(s) no longer match the journal: "
                      + ", ".join(report.drift),
                      details={"paths": report.drift, "open_runs": open_runs,
                               "lock_released": report.lock_released})
    if open_runs:
        plan_id = open_runs[0]["plan_id"]
        next_step = f"rerun `ontology-build {plan_verb(paths, plan_id)} --plan-id {plan_id} ...` to resume"
    else:
        next_step = "ontology-build status"
    return {"status": "ok", "drift": [], "open_runs": open_runs, "lock_released": report.lock_released,
            "next_step": next_step}


def _matches(path: Path, sha256: str) -> bool:
    return path.is_file() and hashing.sha256_file(path) == sha256


def _version_drift(paths: StatePaths) -> list[str]:
    drift = []
    if not paths.versions_dir.is_dir():
        return drift
    for child in sorted(paths.versions_dir.iterdir()):
        name = child.name
        if not (child.is_dir() and name.startswith("v") and name[1:].isdigit()):
            continue
        n = int(name[1:])
        meta_path, onto_path = paths.version_json(n), paths.ontology(n)
        if not meta_path.is_file():
            drift.append(paths.relative(meta_path))
            continue
        try:
            meta = state.read_record(meta_path, Version)
        except (Blocked, ValueError, KeyError, TypeError):
            drift.append(paths.relative(meta_path))
            continue
        if not onto_path.is_file() or hashing.schema_id_of_bytes(onto_path.read_bytes()) != meta.schema_id:
            drift.append(paths.relative(onto_path))
        approval_path = paths.approval(n)
        if approval_path.is_file():
            try:
                approval = state.read_record(approval_path, Approval)
            except (Blocked, ValueError, KeyError, TypeError):
                drift.append(paths.relative(approval_path))
                continue
            if approval.schema_id != meta.schema_id or approval.version != n:
                drift.append(paths.relative(approval_path))
    return drift


def _export_drift(paths: StatePaths) -> list[str]:
    drift = []
    if not paths.exports_dir.is_dir():
        return drift
    for manifest_path in sorted(paths.exports_dir.glob("export-manifest.*.json")):
        try:
            manifest = state.read_record(manifest_path, ExportManifest)
        except (Blocked, ValueError, KeyError, TypeError):
            drift.append(paths.relative(manifest_path))
            continue
        output = Path(manifest.output)
        if output.is_file() and hashing.sha256_file(output) != manifest.owl_sha256:
            drift.append(output.as_posix())
    return drift


def _response_path(paths: StatePaths, plan_id: str, call: str) -> Path | None:
    if call == "audit":
        return paths.audit_response(plan_id)
    if call.startswith("shard-") and call[6:].isdigit():
        return paths.shard_response(plan_id, int(call[6:]))
    judge = re.fullmatch(r"judge-([1-9][0-9]*)(?:-s([1-9][0-9]*))?", call)
    if judge:
        return paths.judge_response(plan_id, int(judge[1]), int(judge[2] or 1))
    return None


def plan_verb(paths: StatePaths, plan_id: str) -> str:
    """The verb that runs `plan_id`: `propose`, `critique` or `refine`."""
    path = paths.plan(plan_id)
    if not path.is_file():
        return "propose"
    critique = state.read_record(path, Plan).critique
    return critique.kind if critique is not None else "propose"


def _response_drift(paths: StatePaths, entries: list[dict[str, Any]]) -> list[str]:
    latest: dict[tuple[str, str], str] = {}
    for entry in entries:
        if entry["event"] == "call_completed":
            latest[(entry["plan_id"], entry["call"])] = entry["response_sha256"]
    drift = []
    for (plan_id, call), sha in latest.items():
        path = _response_path(paths, plan_id, call)
        if path is not None and not _matches(path, sha):
            drift.append(paths.relative(path))
    return drift


def _open_runs(paths: StatePaths, entries: list[dict[str, Any]]) -> list[OpenRun]:
    started: list[str] = []
    finished: set[str] = set()
    for entry in entries:
        if entry["event"] == "run_started" and entry["plan_id"] not in started:
            started.append(entry["plan_id"])
        elif entry["event"] == "run_finished":
            finished.add(entry["plan_id"])
    runs = []
    for plan_id in started:
        if plan_id in finished:
            continue
        ledger = budget.Ledger.from_journal(entries, plan_id)
        calls = _planned_calls(paths, plan_id)
        runs.append(OpenRun(plan_id=plan_id, calls_left=[c for c in calls if c not in ledger.completed],
                            spent_usd=round(ledger.spent_usd, 6)))
    return runs


def _planned_calls(paths: StatePaths, plan_id: str) -> list[str]:
    path = paths.plan(plan_id)
    if not path.is_file():
        return ["audit"]
    plan = state.read_record(path, Plan)
    if plan.critique is not None:
        return [state.judge_call(k, j) for k in range(1, plan.critique.max_rounds + 1)
                for j in range(1, plan.critique.judge_samples + 1)]
    assert plan.sampling is not None
    return [*(f"shard-{k}" for k in range(plan.sampling.shards)), "audit"]
