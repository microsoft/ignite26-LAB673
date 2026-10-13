"""Offline Build plan estimates for managed graph extraction; never part of the plan ID.

Per-call constants are measured on gpt-5-mini GlobalStandard for small single-chunk
documents (see docs/performance.md). They are planning figures, not guarantees.
"""

from __future__ import annotations

import math
from typing import Any

from ekg_core.models import BuildSpec, ingestion_interval_minutes
from ekg_core.pricing import token_cost_range_usd

# reasoning effort -> (seconds per extraction call, total tokens per call)
MEASURED_CALL = {"low": (4.8, 1_100), "medium": (12.8, 2_100)}
MAX_RUN_SECONDS = 2 * 60 * 60  # skillset indexer limits.maxRunTime on Basic/serverless
# A schedule at or below this keeps a multi-run build moving without someone starting runs.
UNATTENDED_INTERVAL_MINUTES = 15
TPM_HEADROOM = 0.8  # leave room for embedding and alignment calls on the same account


def schedule_note(spec: BuildSpec, runs: int) -> dict[str, Any]:
    """How a build that needs ``runs`` 2-hour indexer runs continues between runs."""
    interval = spec.ingestion_interval or "P1D"
    minutes = ingestion_interval_minutes(interval)
    unattended = runs <= 1 or minutes <= UNATTENDED_INTERVAL_MINUTES
    if runs <= 1:
        note = "Extraction fits in one 2-hour indexer run."
    elif unattended:
        note = (f"Extraction needs about {runs} 2-hour indexer runs; with schedule {interval} "
                f"each next run starts within {minutes} min, so the build finishes unattended.")
    else:
        note = (f"Extraction needs about {runs} 2-hour indexer runs, but schedule {interval}"
                f"{' (the service default)' if spec.ingestion_interval is None else ''} starts "
                f"the next run about {_duration(minutes)} later. Plan with "
                "--ingestion-interval PT5M to finish unattended.")
    return {"interval": interval, "interval_minutes": minutes, "unattended": unattended,
            "note": note}


def _duration(minutes: int) -> str:
    return "1 day" if minutes == 1440 else f"{minutes // 60} h" if minutes % 60 == 0 else f"{minutes} min"


def extraction_estimate(spec: BuildSpec, documents: int | None, *,
                        chat_capacity_k_tpm: int | None = None) -> dict[str, Any]:
    from .managed_pipeline import extraction_settings

    settings = extraction_settings(spec)
    effort = settings["extraction"]["reasoningEffort"]
    parallelism = settings["pageDegreeOfParallelism"]
    result: dict[str, Any] = {
        "origin": "measured_rates", "reasoning_effort": effort,
        "page_parallelism": parallelism, "documents": documents,
        "chat_capacity_k_tpm": chat_capacity_k_tpm,
        "assumptions": [
            "One extraction call per document (documents up to four 2,000-character chunks).",
            "The indexer enriches one document at a time; page parallelism only overlaps "
            "chunks of a multi-chunk document.",
        ],
        "uncertainty": [],
    }
    measured = MEASURED_CALL.get(effort)
    if documents is None:
        result["uncertainty"].append("Document count is unknown without a source manifest.")
    if measured is None:
        result["uncertainty"].append(f"No measured per-call rate for reasoning effort {effort}.")
    if documents is None or measured is None:
        return result
    seconds, tokens = measured
    calls = documents
    total_tokens = calls * tokens
    serial_tpm = round(60 / seconds * tokens)
    latency_seconds = calls * seconds
    result.update(
        extraction_calls=calls, estimated_tokens=total_tokens,
        serial_tokens_per_minute=serial_tpm,
        latency_bound_seconds=round(latency_seconds),
    )
    wall = latency_seconds
    if chat_capacity_k_tpm is not None:
        usable = chat_capacity_k_tpm * 1000 * TPM_HEADROOM
        tpm_seconds = total_tokens / usable * 60
        wall = max(latency_seconds, tpm_seconds)
        result.update(
            capacity_bound_seconds=round(tpm_seconds),
            tpm_bound=tpm_seconds > latency_seconds,
            max_page_parallelism_for_capacity=max(1, math.floor(usable / serial_tpm)),
        )
        if tpm_seconds > latency_seconds:
            result["uncertainty"].append(
                f"{chat_capacity_k_tpm}K TPM is below the ~{math.ceil(serial_tpm / 1000 / TPM_HEADROOM)}K "
                "needed for serial extraction; expect 429 retries. Raise capacity."
            )
        if parallelism > result["max_page_parallelism_for_capacity"]:
            result["uncertainty"].append(
                f"Page parallelism {parallelism} can exceed {chat_capacity_k_tpm}K TPM on "
                "multi-chunk documents; lower it or raise capacity."
            )
    result.update(
        minimum_wall_seconds=round(wall),
        indexer_runs=max(1, math.ceil(wall / MAX_RUN_SECONDS)),
    )
    if result["indexer_runs"] > 1:
        result["uncertainty"].append(schedule_note(spec, result["indexer_runs"])["note"])
    cost = token_cost_range_usd(spec.chat_model, total_tokens)
    result["extraction_cost_usd"] = (None if cost is None else
                                     {"low": round(cost[0], 4), "high": round(cost[1], 4)})
    return result


def trial_estimate(spec: BuildSpec, trial_report: dict[str, Any]) -> dict[str, Any]:
    """Replace plan-time rates with a GO trial report's measured extrapolation."""
    sample = trial_report.get("sample") or {}
    extrapolation = trial_report.get("extrapolation") or {}
    wall, cost = extrapolation.get("wall_minutes"), extrapolation.get("cost_usd")
    documents = len(spec.source_manifest.items) if spec.source_manifest else None
    if trial_report.get("status") != "go" or not wall:
        raise ValueError("--trial-report must be a GO `ekg-build trial-report --json` result "
                         "with a measured wall time")
    if spec.trial is not None:
        raise ValueError("--trial-report estimates the full build; drop --sample")
    digest = sample.get("corpus_digest")
    if (sample.get("corpus_documents") != documents or
            (digest and spec.source_manifest and digest != spec.source_manifest.digest)):
        raise ValueError("--trial-report was measured on a different corpus than this plan")
    runs = extrapolation.get("indexer_runs") or 1
    schedule = schedule_note(spec, runs)
    notes = [note for note in extrapolation.get("notes") or []
             if not note.startswith("The full build needs more than one 2-hour")]
    return {
        "origin": "trial_report", "documents": documents,
        "wall_minutes": {"low": wall["low"], "high": wall["high"]},
        "indexer_runs": extrapolation.get("indexer_runs"),
        "schedule": schedule,
        "extraction_cost_usd": cost,
        "basis": extrapolation.get("basis"),
        "uncertainty": notes + ([schedule["note"]] if runs > 1 else []),
    }


def plan_estimates(spec: BuildSpec, *, chat_capacity_k_tpm: int | None = None) -> dict[str, Any]:
    """Extraction estimates for the planned documents and, for a trial, the full corpus."""
    documents = len(spec.source_manifest.items) if spec.source_manifest else None
    estimates: dict[str, Any] = {"extraction": extraction_estimate(
        spec, documents, chat_capacity_k_tpm=chat_capacity_k_tpm)}
    if spec.trial is not None:
        full = extraction_estimate(spec, spec.trial.corpus_documents,
                                   chat_capacity_k_tpm=chat_capacity_k_tpm)
        estimates["trial"] = {
            "sample_documents": spec.trial.size,
            "corpus_documents": spec.trial.corpus_documents,
            "full_build": full,
            "basis": "Plan-time rates measured on small documents; `ekg-build trial-report` "
                     "replaces them with this trial's measured tokens and wall time.",
        }
    return estimates
