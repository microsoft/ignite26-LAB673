"""Read-only attribution of managed Knowledge Source synchronization time.

The managed pipeline runs cracking, chunking, embedding and graph extraction on
the Search service, so the EKG client cannot time those steps directly. This
module joins the service's own records for one synchronization: generated
indexer status, the generated skillset's extraction settings, Azure Monitor
metrics for the model account and Search service, and the model deployments'
capacity. From those it estimates where the time went. It never writes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from ekg_core.telemetry import parse_time

TRIPLE_SKILL = "TripleExtractionSkill"
# Service default when the Knowledge Source omits graphExtraction.pageDegreeOfParallelism.
SERVICE_DEFAULT_PAGE_DOP = 128
AOAI_METRICS = ("AzureOpenAIRequests", "AzureOpenAITTLTInMS", "TokenTransaction",
                "GeneratedTokens", "ProcessedPromptTokens")
SEARCH_METRICS = ("SkillExecutionCount",)

MetricReader = Callable[[str, tuple[str, ...], datetime, datetime, str], dict[str, Any]]
DeploymentReader = Callable[[str, str], dict[str, Any] | None]


def _model(ingestion: dict[str, Any], key: str) -> dict[str, Any]:
    params = ((ingestion.get(key) or {}).get("azureOpenAIParameters") or {})
    return {"deployment": params.get("deploymentId"), "model": params.get("modelName")}


def _triple_skill(skillset: dict[str, Any] | None) -> dict[str, Any]:
    for skill in (skillset or {}).get("skills") or []:
        if isinstance(skill, dict) and TRIPLE_SKILL in str(skill.get("@odata.type", "")):
            return skill
    return {}


def extraction_settings(knowledge_source: dict[str, Any], skillset: dict[str, Any] | None,
                        indexer: dict[str, Any] | None = None) -> dict[str, Any]:
    """Settings that bound extraction throughput, from the live resources."""
    ingestion = ((knowledge_source.get("azureBlobParameters") or {})
                 .get("ingestionParameters") or {})
    graph = ingestion.get("graphExtraction") or {}
    skill = _triple_skill(skillset)
    extraction = skill.get("extraction") or {}
    requested = graph.get("pageDegreeOfParallelism")
    effective = skill.get("pageDegreeOfParallelism", requested)
    return {
        "chat": _model(ingestion, "chatCompletionModel"),
        "embedding": _model(ingestion, "embeddingModel"),
        "page_degree_of_parallelism": effective if effective is not None else SERVICE_DEFAULT_PAGE_DOP,
        "page_degree_of_parallelism_source": (
            "generated_skillset" if "pageDegreeOfParallelism" in skill else
            "knowledge_source" if requested is not None else "service_default"),
        "reasoning_effort": extraction.get("reasoningEffort",
                                           (graph.get("extraction") or {}).get("reasoningEffort")),
        "max_tokens": extraction.get("maxTokens"),
        "temperature": extraction.get("temperature"),
        "max_concurrent_chunks": (skill.get("extractionTokens") or {}).get("maxConcurrentChunks"),
        "grounding_degree_of_parallelism": skill.get("groundingDegreeOfParallelism"),
        "indexer_batch_size": ((indexer or {}).get("parameters") or {}).get("batchSize"),
        "indexer_schedule_interval": ((indexer or {}).get("schedule") or {}).get("interval"),
    }


def _run_key(item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        item.get("startTime"), item.get("endTime"), item.get("status"),
        item.get("itemsProcessed"), item.get("itemsFailed"),
    )


def _finished_runs(status: dict[str, Any]) -> list[dict[str, Any]]:
    history = [item for item in status.get("executionHistory") or [] if isinstance(item, dict)]
    latest = status.get("lastResult")
    candidates = ([latest] if isinstance(latest, dict) else []) + history
    finished: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for item in candidates:
        key = _run_key(item)
        if key not in seen and parse_time(item.get("startTime")) and parse_time(item.get("endTime")):
            seen.add(key)
            finished.append(item)
    return finished


def _processed(item: dict[str, Any]) -> int:
    value = item.get("itemsProcessed")
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _execution(status: dict[str, Any]) -> dict[str, Any] | None:
    finished = _finished_runs(status)
    if not finished:
        return None
    productive = [item for item in finished if _processed(item) > 0]
    if productive:
        runs = sorted(productive, key=lambda item: parse_time(item["startTime"]))
        return _span_execution(runs)
    return max(finished, key=lambda item: parse_time(item["startTime"]) or datetime.min.replace(
        tzinfo=timezone.utc))


def _span_execution(runs: list[dict[str, Any]]) -> dict[str, Any]:
    start = min(parse_time(item["startTime"]) for item in runs)
    end = max(parse_time(item["endTime"]) for item in runs)
    latest = max(runs, key=lambda item: parse_time(item["startTime"]))
    warnings: list[Any] = []
    errors: list[Any] = []
    for item in runs:
        warnings.extend(item.get("warnings") or [])
        errors.extend(item.get("errors") or [])
    return {
        **latest,
        "startTime": start.isoformat().replace("+00:00", "Z"),
        "endTime": end.isoformat().replace("+00:00", "Z"),
        "itemsProcessed": sum(_processed(item) for item in runs),
        "itemsFailed": sum(value for item in runs
                           if isinstance((value := item.get("itemsFailed")), int)
                           and not isinstance(value, bool)),
        "status": latest.get("status"),
        "warnings": warnings,
        "errors": errors,
        "runs": len(runs),
    }


def _warning_groups(execution: dict[str, Any]) -> dict[str, int]:
    groups: dict[str, int] = {}
    for item in (execution.get("warnings") or []) + (execution.get("errors") or []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "unnamed")
        key = ("graph_index_projection" if name.startswith("Projection.") else
               "triple_extraction" if TRIPLE_SKILL in name or "Triple" in name else
               name.split(".", 1)[0][:40])
        text = f"{item.get('message', '')} {item.get('details', '')}".casefold()
        if "429" in text or "throttl" in text or "rate limit" in text:
            key = "throttling"
        groups[key] = groups.get(key, 0) + 1
    return groups


def _series(payload: dict[str, Any]) -> list[tuple[str, dict[str, str], list[dict[str, Any]]]]:
    rows = []
    for metric in (payload or {}).get("value") or []:
        name = (metric.get("name") or {}).get("value")
        for series in metric.get("timeseries") or []:
            dims = {str((item.get("name") or {}).get("value", "")).casefold(): str(item.get("value"))
                    for item in series.get("metadatavalues") or []}
            rows.append((name, dims, series.get("data") or []))
    return rows


def _model_metrics(payload: dict[str, Any], deployment: str | None) -> dict[str, Any]:
    requests = throttles = errors = 0
    tokens_per_minute: dict[str, float] = {}
    totals = {"GeneratedTokens": 0.0, "ProcessedPromptTokens": 0.0, "TokenTransaction": 0.0}
    ttlt_weighted = ttlt_weight = ttlt_max = 0.0
    per_minute: dict[str, float] = {}
    for name, dims, points in _series(payload):
        if deployment and dims.get("modeldeploymentname") not in (None, deployment):
            continue
        for point in points:
            value = point.get("total") or 0.0
            if name == "AzureOpenAIRequests":
                code = dims.get("statuscode", "")
                requests += int(value)
                throttles += int(value) if code == "429" else 0
                errors += int(value) if code.startswith("5") else 0
                if code == "200":
                    per_minute[point["timeStamp"]] = per_minute.get(point["timeStamp"], 0) + value
            elif name in totals:
                totals[name] += value
                if name == "TokenTransaction":
                    tokens_per_minute[point["timeStamp"]] = value
            elif name == "AzureOpenAITTLTInMS" and point.get("average"):
                ttlt_max = max(ttlt_max, point.get("maximum") or 0.0)
    for name, dims, points in _series(payload):
        if name != "AzureOpenAITTLTInMS" or (
                deployment and dims.get("modeldeploymentname") not in (None, deployment)):
            continue
        for point in points:
            count = per_minute.get(point.get("timeStamp"), 0)
            if point.get("average") and count:
                ttlt_weighted += point["average"] * count
                ttlt_weight += count
    return {
        "requests": requests, "throttles_429": throttles, "server_errors": errors,
        "mean_latency_ms": round(ttlt_weighted / ttlt_weight, 1) if ttlt_weight else None,
        "max_latency_ms": ttlt_max or None,
        "generated_tokens": int(totals["GeneratedTokens"]),
        "prompt_tokens": int(totals["ProcessedPromptTokens"]),
        "peak_tokens_per_minute": int(max(tokens_per_minute.values(), default=0)),
        "peak_requests_per_minute": int(max(per_minute.values(), default=0)),
    }


def _skill_activity(payload: dict[str, Any], indexer: str) -> dict[str, Any]:
    skills: dict[str, dict[str, Any]] = {}
    for name, dims, points in _series(payload):
        if name != "SkillExecutionCount" or dims.get("indexername") not in (None, indexer):
            continue
        skill = dims.get("skillname", "unknown")
        active = [point for point in points if point.get("total")]
        row = skills.setdefault(skill, {"invocations": 0, "first": None, "last": None})
        row["invocations"] += int(sum(point["total"] for point in active))
        if active:
            row["first"] = min(filter(None, [row["first"], active[0]["timeStamp"]]))
            row["last"] = max(filter(None, [row["last"], active[-1]["timeStamp"]]))
    return skills


def _minute_floor(value: datetime) -> datetime:
    return value.replace(second=0, microsecond=0)


def attribute(*, knowledge_source: dict[str, Any], indexer: dict[str, Any] | None,
              indexer_status: dict[str, Any], skillset: dict[str, Any] | None,
              model_metrics: dict[str, Any] | None = None,
              search_metrics: dict[str, Any] | None = None,
              deployments: dict[str, dict[str, Any] | None] | None = None) -> dict[str, Any]:
    """Pure attribution from already-read service records."""
    uncertainty: list[str] = []
    execution = _execution(indexer_status)
    settings = extraction_settings(knowledge_source, skillset, indexer)
    report: dict[str, Any] = {
        "phase": "build.attribution", "knowledge_source": knowledge_source.get("name"),
        "evidence": {"origin": "live_service_records", "writes": "none"},
        "settings": settings, "window": None, "segments": [], "models": {},
        "skills": {}, "warnings": {}, "limits": indexer_status.get("limits"),
        "bottleneck": None, "uncertainty": uncertainty,
    }
    if execution is None:
        uncertainty.append("The generated indexer has no finished execution to attribute.")
        return report
    start, end = parse_time(execution["startTime"]), parse_time(execution["endTime"])
    scheduled = parse_time(((indexer or {}).get("schedule") or {}).get("startTime"))
    processing_ms = (end - start).total_seconds() * 1000
    report["window"] = {
        "scheduled_at": scheduled.isoformat() if scheduled else None,
        "started_at": start.isoformat(), "ended_at": end.isoformat(),
        "processing_ms": round(processing_ms, 1),
        "items_processed": execution.get("itemsProcessed"),
        "items_failed": execution.get("itemsFailed"), "status": execution.get("status"),
    }
    report["warnings"] = _warning_groups(execution)
    segments = report["segments"]
    if scheduled and scheduled <= start:
        segments.append({"segment": "queue_and_scheduling",
                         "duration_ms": round((start - scheduled).total_seconds() * 1000, 1),
                         "basis": "indexer schedule start to execution start"})
    dop = settings["page_degree_of_parallelism"] or 1
    concurrency = 1.0
    for role in ("chat", "embedding"):
        deployment = settings[role]["deployment"]
        metrics = _model_metrics(model_metrics or {}, deployment) if model_metrics else None
        live = (deployments or {}).get(role) or {}
        capacity = (live.get("sku") or {}).get("capacity")
        entry: dict[str, Any] = {**settings[role], "sku": (live.get("sku") or {}).get("name"),
                                 "capacity_thousand_tpm": capacity, "metrics": metrics}
        if metrics and capacity:
            entry["peak_tpm_utilization"] = round(
                metrics["peak_tokens_per_minute"] / (capacity * 1000), 3)
        report["models"][role] = entry
        if metrics and metrics["requests"] and metrics["mean_latency_ms"]:
            call_ms = metrics["requests"] * metrics["mean_latency_ms"]
            if role == "chat":
                # Observed, not configured: summed call time over the processing window.
                # Page parallelism only applies within a document, so it can exceed this.
                concurrency = max(1.0, call_ms / processing_ms) if processing_ms else 1.0
                entry["observed_concurrency"] = round(call_ms / processing_ms, 2) \
                    if processing_ms else None
            busy = call_ms / (concurrency if role == "chat" else 1)
            segments.append({
                "segment": "llm_extraction" if role == "chat" else "embedding",
                "duration_ms": round(min(busy, processing_ms), 1),
                "basis": f"{metrics['requests']} requests x {metrics['mean_latency_ms']} ms mean"
                         + (f" / observed concurrency {round(concurrency, 2)}"
                            if role == "chat" else ""),
            })
    if not model_metrics:
        uncertainty.append("Model account metrics were not read; extraction time is unattributed.")
    report["skills"] = _skill_activity(search_metrics or {}, (indexer or {}).get("name", ""))
    attributed = sum(item["duration_ms"] for item in segments
                     if item["segment"] in {"llm_extraction", "embedding"})
    segments.append({"segment": "cracking_chunking_indexing_and_other",
                     "duration_ms": round(max(0.0, processing_ms - attributed), 1),
                     "basis": "processing window minus attributed model time"})
    total = sum(item["duration_ms"] for item in segments) or 1.0
    for item in segments:
        item["share"] = round(item["duration_ms"] / total, 3)
    chat = report["models"].get("chat") or {}
    llm = next((item for item in segments if item["segment"] == "llm_extraction"), None)
    throttles = sum(((entry.get("metrics") or {}).get("throttles_429") or 0)
                    for entry in report["models"].values())
    utilization = chat.get("peak_tpm_utilization")
    if llm and llm["share"] >= 0.5:
        report["bottleneck"] = {
            "kind": "throttled_llm_extraction" if throttles else
                    "serial_llm_extraction" if concurrency < 1.5 else "llm_extraction_latency",
            "page_degree_of_parallelism": dop,
            "observed_concurrency": chat.get("observed_concurrency"),
            "page_parallelism_engaged": concurrency >= min(1.5, float(dop)),
            "throttles_429": throttles,
            "peak_tpm_utilization": utilization,
            "tpm_bound": bool(throttles) or (utilization is not None and utilization >= 0.8),
        }
    if (indexer_status.get("limits") or {}).get("maxRunTime") and execution.get("itemsProcessed"):
        per_item = processing_ms / max(1, execution["itemsProcessed"])
        report["projected_items_within_max_run_time"] = _items_within(
            indexer_status["limits"]["maxRunTime"], per_item)
    uncertainty.append("Segment durations are estimates from service metrics at one-minute "
                       "or coarser granularity; they are not per-call traces.")
    return report


def _items_within(duration: str, per_item_ms: float) -> int | None:
    # ISO-8601 durations the indexer reports, such as PT2H or P1D.
    import re
    match = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", duration or "")
    if not match or per_item_ms <= 0:
        return None
    days, hours, minutes, seconds = (int(value or 0) for value in match.groups())
    total_ms = ((days * 24 + hours) * 60 + minutes) * 60_000 + seconds * 1000
    return int(total_ms // per_item_ms)


def metric_window(indexer_status: dict[str, Any]) -> tuple[datetime, datetime] | None:
    execution = _execution(indexer_status)
    if execution is None:
        return None
    start, end = parse_time(execution["startTime"]), parse_time(execution["endTime"])
    return _minute_floor(start) - timedelta(minutes=5), _minute_floor(end) + timedelta(minutes=2)


def collect(adapter: Any, knowledge_source_name: str, *, openai_resource_id: str | None,
            search_resource_id: str | None, tenant_id: str | None) -> dict[str, Any]:
    """Read every record attribution needs; GET requests only."""
    from .managed_pipeline import generated

    live = adapter.get_knowledge_source(knowledge_source_name)
    if not live:
        raise ValueError("managed Knowledge Source was not found")
    resources = generated(live)
    indexer = adapter.get_resource("indexers", resources["indexer"])
    status = adapter.indexer_status(resources["indexer"])
    skillset = adapter.get_resource("skillsets", resources["skillset"])
    window = metric_window(status)
    notes: list[str] = []
    model_metrics = search_metrics = None
    deployments: dict[str, dict[str, Any] | None] = {}
    if window and tenant_id and openai_resource_id:
        settings = extraction_settings(live, skillset, indexer)
        model_metrics = _merged(adapter, openai_resource_id, window, tenant_id, (
            (AOAI_METRICS[:1], "ModelDeploymentName,StatusCode"),
            (AOAI_METRICS[1:], "ModelDeploymentName"),
        ))
        for role in ("chat", "embedding"):
            deployment = settings[role]["deployment"]
            deployments[role] = (adapter.arm_read(
                f"{openai_resource_id}/deployments/{deployment}", "2024-10-01",
                tenant_id=tenant_id) if deployment else None)
    else:
        notes.append("Provide the tenant and model account ARM ID to read model metrics.")
    if window and tenant_id and search_resource_id:
        search_metrics = _merged(adapter, search_resource_id, window, tenant_id, (
            (SEARCH_METRICS, "IndexerName,SkillName"),
        ))
    report = attribute(knowledge_source=live, indexer=indexer, indexer_status=status,
                       skillset=skillset, model_metrics=model_metrics,
                       search_metrics=search_metrics, deployments=deployments)
    report["uncertainty"][:0] = notes
    return report


def _merged(adapter: Any, resource_id: str, window: tuple[datetime, datetime], tenant_id: str,
            groups: tuple[tuple[tuple[str, ...], str], ...]) -> dict[str, Any]:
    # Azure Monitor rejects a dimension filter a metric does not define, so read per dimension set.
    values: list[Any] = []
    for names, split in groups:
        payload = adapter.monitor_metrics(resource_id, names, *window, "PT1M",
                                          tenant_id=tenant_id, split=split)
        values.extend((payload or {}).get("value") or [])
    return {"value": values}
