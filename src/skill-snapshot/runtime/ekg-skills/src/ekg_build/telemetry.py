"""Read-only phase breakdown for one Build attempt plus a Consume latency summary."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ekg_core.telemetry import (
    read_consume_log, summarize_consume, summarize_phases, telemetry_event, valid_event, parse_time,
)

# Journals written before telemetry events existed only carry aggregate phase timings.
_TIMING_OPERATIONS = {
    "stage_ms": "stage", "ontology_ms": "ontology_index",
    "synchronization_ms": "wait_for_synchronization", "verify_ms": "verify",
}


def _timings_events(timings: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        telemetry_event("build", operation, started_at=None, ended_at=None,
                        duration_ms=timings[key], origin="journal_timings_ms")
        for key, operation in _TIMING_OPERATIONS.items()
        if isinstance(timings.get(key), (int, float)) and not isinstance(timings.get(key), bool)
    ]


def build_telemetry(journal_path: str | None = None, run_id: str | None = None, *,
                    consume_log: str | None = None) -> dict[str, Any]:
    """Summarize local telemetry; never contacts Azure and never writes."""
    if not journal_path and not consume_log:
        raise ValueError("telemetry requires a build journal, a consume log, or both")
    report: dict[str, Any] = {
        "phase": "build.telemetry", "run_id": run_id, "plan_id": None, "state": None,
        "evidence": {"origin": "local_telemetry"}, "wall_ms": None,
        "phases": [], "consume": [], "uncertainty": [],
    }
    if journal_path:
        try:
            record = json.loads(Path(journal_path).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("build journal must be a readable JSON file") from error
        if not isinstance(record, dict):
            raise ValueError("build journal is malformed")
        recorded = record.get("run_id")
        if run_id is not None and recorded is not None and recorded != run_id:
            raise ValueError("build journal run ID differs from --run-id")
        report.update(run_id=recorded or run_id, plan_id=record.get("plan_id"),
                      state=record.get("state"))
        raw = record.get("telemetry")
        events = [event for event in raw if valid_event(event)] if isinstance(raw, list) else []
        if not events and isinstance(record.get("timings_ms"), dict):
            events = _timings_events(record["timings_ms"])
            report["uncertainty"].append(
                "Journal predates telemetry events; only aggregate phase timings are available.")
        if not any(event.get("origin") == "live_knowledge_source_status" for event in events):
            report["uncertainty"].append(
                "No service-side synchronization window recorded; run `ekg-build reconcile` "
                "after synchronization finishes to capture it.")
        timed = [(parse_time(event["started_at"]), parse_time(event["ended_at"])) for event in events]
        timed = [(start, end) for start, end in timed if start and end]
        if timed:
            report["wall_ms"] = round(
                (max(end for _, end in timed) - min(start for start, _ in timed))
                .total_seconds() * 1000, 3)
        elif isinstance((record.get("timings_ms") or {}).get("time_to_build_ms"), (int, float)):
            report["wall_ms"] = record["timings_ms"]["time_to_build_ms"]
        report["phases"] = summarize_phases(events, wall_ms=report["wall_ms"])
    if consume_log:
        try:
            report["consume"] = summarize_consume(read_consume_log(consume_log))
        except (OSError, UnicodeError) as error:
            raise ValueError("consume telemetry log must be a readable file") from error
        if not report["consume"]:
            report["uncertainty"].append("Consume telemetry log has no events.")
    report["uncertainty"].append("Local records do not attest current remote state.")
    return report
