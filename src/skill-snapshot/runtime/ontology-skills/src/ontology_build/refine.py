"""`ontology-build refine`: lint → judge → revise rounds under one approved plan.

Each round judges its input version (`judge_samples` model calls, reused on resume, scored by their median),
then either stops or applies the high/medium ops as a new `revise` version. Stop reasons, checked in this
order after each judge:

- `converged`: no high findings and no medium lint findings (low findings never block it).
- `causal_repeat`: a finding that an earlier round's applied ops targeted is reported again.
- `no_improvement`: the round's candidate is rejected: its median total is more than `noise_margin` points
  below the previous round's and its question_coverage did not improve. A drop within the margin, or any
  question_coverage gain, keeps the candidate and the loop goes on. The rejected round's ops are not
  applied but stay in its critique record; `rejected` in the result names it so
  `ontology-build revise --from-critique <id>` can apply them by hand.
- `no_changes`: no accepted op could be applied.
- `max_rounds`: the planned number of rounds ran.
- `budget_exhausted`: the next judge call does not fit the approved budget; versions so far are kept.

`runs/<plan>/refine.json` records every finished round, so a rerun resumes after the last one. Each round
lists the ops revise skipped as `warnings` (e.g. `rename_style_only`, `drop_has_evidence`); revise never
writes a version with coverage regressions. The final
version is the newest one, except after `no_improvement`, where it is the best judged version by
question_coverage, then median total (then the newer version).
"""

from __future__ import annotations

from typing import Any

from ontology_build import critique, revise
from ontology_build.critique import RunRequest
from ontology_build.propose import ProposeDeps, _Run
from ontology_core import state
from ontology_core.errors import Blocked
from ontology_core.journal import Journal, StateLock
from ontology_core.model import Plan
from ontology_core.state import StatePaths

STOP_REASONS = ("converged", "causal_repeat", "no_improvement", "no_changes", "max_rounds", "budget_exhausted")


def _save(paths: StatePaths, journal: Journal, record: dict[str, Any]) -> None:
    path = paths.refine_record(record["plan_id"])
    sha = state.write_json(path, record)
    journal.append("artifact_written", path=paths.relative(path), sha256=sha)


def load_record(paths: StatePaths, plan_id: str) -> dict[str, Any] | None:
    path = paths.refine_record(plan_id)
    return state.read_json(path) if path.is_file() else None


def _produced(paths: StatePaths, journal: Journal, plan_id: str, parent: int) -> int | None:
    """A version this plan already revised from v`parent` (a crash after `write_version` left it behind)."""
    for event in journal.events("version_created", plan_id=plan_id):
        n = event["version"]
        if paths.version_json(n).is_file() and state.read_record(paths.version_json(n),
                                                                state.Version).parent_version == parent:
            return int(n)
    return None


def _coverage(value: int | float | None) -> float:
    return -1.0 if value is None else float(value)


def _stop(judged: dict[str, Any], rounds: list[dict[str, Any]], noise_margin: int = 0,
          ) -> tuple[str | None, list[str]]:
    fingerprints = {f["fingerprint"] for f in judged["findings"]}
    high = any(f["severity"] == "high" for f in judged["findings"])
    medium_lint = any(f["severity"] == "medium" for f in judged["lint"])
    if not high and not medium_lint:
        return "converged", []
    targeted = {fp for r in rounds for fp in r["targeted"]}
    repeated = sorted(fingerprints & targeted)
    if repeated:
        return "causal_repeat", repeated
    if rounds:
        previous = rounds[-1]
        worse = judged["total"] < previous["total"] - noise_margin
        covered = _coverage(critique.question_coverage(judged)) > _coverage(previous.get("question_coverage"))
        if worse and not covered:
            return "no_improvement", []
    return None, []


def _round(k: int, judged: dict[str, Any]) -> dict[str, Any]:
    counts = {s: sum(1 for f in judged["findings"] if f["severity"] == s) for s in ("high", "medium", "low")}
    return {"round": k, "critique_id": judged["critique_id"], "version_in": judged["version"],
            "scores": judged["scores"], "total": judged["total"], "max_total": judged["max_total"],
            "question_coverage": critique.question_coverage(judged),
            "sample_totals": [x["total"] for x in judged.get("samples", [])], "rejected_ops": 0,
            "findings": counts, "fingerprints": [f["fingerprint"] for f in judged["findings"]],
            "targeted": [], "applied": [], "skipped": 0, "warnings": list(judged.get("judge_warnings", [])),
            "version_out": None, "stop": None}


def _final(record: dict[str, Any]) -> int:
    rounds = record["rounds"]
    if record["stop"] == "no_improvement" and rounds:
        return max(rounds, key=lambda r: (_coverage(r.get("question_coverage")), r["total"],
                                          r["version_in"]))["version_in"]
    outs = [r["version_out"] for r in rounds if r["version_out"] is not None]
    return outs[-1] if outs else record["start_version"]


def _loop(paths: StatePaths, runner: _Run, plan: Plan, record: dict[str, Any]) -> None:
    assert plan.critique is not None
    journal = runner.journal
    rounds: list[dict[str, Any]] = record["rounds"]
    while record["stop"] is None:
        k = len(rounds) + 1
        if k > plan.critique.max_rounds:
            record["stop"] = "max_rounds"
            break
        version_in = rounds[-1]["version_out"] if rounds else record["start_version"]
        try:
            judged = critique.judge(paths, runner, plan, version_in, k)
        except Blocked as exc:
            if exc.code != "BUDGET_EXHAUSTED":
                raise
            record["stop"] = "budget_exhausted"
            break
        entry = _round(k, judged)
        stop, repeated = _stop(judged, rounds, plan.critique.noise_margin)
        if stop is None:
            accepted, _ = revise.accepted_fingerprints(judged, None)
            existing = _produced(paths, journal, plan.plan_id, version_in)
            if existing is not None:
                meta = state.read_record(paths.version_json(existing), state.Version)
                _, _, applied, skipped = revise.plan_revision(state.load_version(paths, version_in)[1],
                                                              judged["ops"], accepted, version=existing)
                out = {"version": existing, "schema_id": meta.schema_id, **revise.outcome(applied, skipped)}
            else:
                out = revise.revise_version(paths, journal, version_in, judged, accepted)
            entry.update(version_out=out["version"], applied=out["applied"], skipped=len(out["skipped"]),
                         warnings=entry["warnings"] + out["warnings"], targeted=sorted({op["finding"] for op in out["applied_ops"]}))
            if out["version"] is None:
                stop = "no_changes"
            elif k == plan.critique.max_rounds:
                stop = "max_rounds"
        entry["stop"] = stop
        if stop == "no_improvement" and judged["ops"]:
            entry["rejected_ops"] = len(judged["ops"])
            record["rejected"] = {"round": k, "critique_id": judged["critique_id"], "version": version_in,
                                  "ops": len(judged["ops"]),
                                  "next_step": f"ontology-build revise --from-critique {judged['critique_id']}"}
        rounds.append(entry)
        if stop is not None:
            record["stop"] = stop
            record["repeated"] = repeated
        _save(paths, journal, record)


def result(paths: StatePaths, record: dict[str, Any], spent_usd: float,
           approved_budget_usd: float | None) -> dict[str, Any]:
    final = record["final_version"]
    meta = state.read_record(paths.version_json(final), state.Version)
    return {
        "status": "ok", "plan_id": record["plan_id"], "start_version": record["start_version"],
        "final_version": final, "schema_id": meta.schema_id, "stop_reason": record["stop"],
        "repeated": record.get("repeated", []), "rejected": record.get("rejected"),
        "rounds": [{**{k: r[k] for k in ("round", "version_in", "total", "max_total", "findings", "applied",
                                         "version_out", "stop")},
                    **{k: r.get(k) for k in ("question_coverage", "sample_totals", "rejected_ops")},
                    "warnings": r.get("warnings", [])}
                   for r in record["rounds"]],
        "spent_usd": round(spent_usd, 6), "approved_budget_usd": approved_budget_usd,
        "next_step": f"ontology-build review --version {final}",
    }


def run(paths: StatePaths, request: RunRequest, deps: ProposeDeps | None = None) -> dict[str, Any]:
    """Run an approved refine plan (rerun resumes). Budget exhaustion ends cleanly with the versions so far.

    Raises: CONFIG_MISSING, STATE_LOCKED, PLAN_NOT_FOUND, PLAN_ID_MISMATCH, PLAN_STALE, PLAN_ALREADY_EXECUTED,
        APPROVAL_REQUIRED, BUDGET_ABOVE_PLAN_CAP, BUDGET_BELOW_ESTIMATE, RUN_INCOMPLETE, MODEL_*,
        QUERY_FILE_INVALID, EMPTY_ONTOLOGY, AZ_NOT_SIGNED_IN, TENANT_MISMATCH.
    """
    state.load_config(paths)  # CONFIG_MISSING before the lock creates the state dir
    with StateLock(paths, "refine"):
        plan, runner = critique.start(paths, request, "refine", deps)
        assert plan.critique is not None
        record = load_record(paths, plan.plan_id) or {
            "plan_id": plan.plan_id, "start_version": plan.critique.base_version, "rounds": [], "stop": None,
            "repeated": [], "final_version": None}
        if record["final_version"] is not None:
            return result(paths, record, runner.ledger().spent_usd, request.approved_budget_usd)
        try:
            _loop(paths, runner, plan, record)
        except Blocked as exc:
            if exc.code != "RUN_INCOMPLETE" and exc.code.startswith(("MODEL_", "EMPTY_")):
                runner.finish("blocked")
            raise
        record["final_version"] = _final(record)
        _save(paths, runner.journal, record)
        runner.finish("budget_exhausted" if record["stop"] == "budget_exhausted" else "completed")
        spent = runner.ledger().spent_usd
    return result(paths, record, spent, request.approved_budget_usd)
