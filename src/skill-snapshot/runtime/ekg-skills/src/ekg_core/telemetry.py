"""Structured phase timing events shared by Provision, Build and Consume.

Events are plain JSON objects appended to the existing journals (Build attempt
journal ``telemetry`` array, Provision run journal ``telemetry`` array) or to an
opt-in Consume JSONL log. They never contain credentials, request bodies or
customer content.
"""

from __future__ import annotations

import json
import math
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

TELEMETRY_VERSION = 1
CONSUME_LOG_ENV = "EKG_CONSUME_TELEMETRY_LOG"
_EVENT_KEYS = ("version", "phase", "operation", "status", "started_at", "ended_at",
               "duration_ms", "counts", "bytes", "retries", "throttles", "tokens", "origin")


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def telemetry_event(phase: str, operation: str, *, started_at: str | None,
                    ended_at: str | None,
                    duration_ms: float, status: str = "completed",
                    counts: dict[str, int] | None = None, bytes: int | None = None,
                    retries: int = 0, throttles: int = 0,
                    tokens: dict[str, int] | None = None,
                    origin: str = "local_clock", **detail: Any) -> dict[str, Any]:
    """Return one telemetry event in the shared shape."""
    event: dict[str, Any] = {
        "version": TELEMETRY_VERSION, "phase": phase, "operation": operation,
        "status": status, "started_at": started_at, "ended_at": ended_at,
        "duration_ms": round(max(0.0, float(duration_ms)), 3),
        "counts": dict(counts or {}), "bytes": bytes, "retries": int(retries),
        "throttles": int(throttles), "tokens": dict(tokens) if tokens else None,
        "origin": origin,
    }
    if detail:
        event["detail"] = detail
    return event


def service_window_event(phase: str, operation: str, start: Any, end: Any, *,
                         origin: str, status: str = "completed",
                         counts: dict[str, int] | None = None,
                         **detail: Any) -> dict[str, Any] | None:
    """Build an event from service-reported timestamps; None if they are unusable."""
    began, finished = parse_time(start), parse_time(end)
    if began is None or finished is None or finished < began:
        return None
    return telemetry_event(
        phase, operation, started_at=began.isoformat(), ended_at=finished.isoformat(),
        duration_ms=(finished - began).total_seconds() * 1000, status=status,
        counts=counts, origin=origin, **detail,
    )


class HttpStats:
    """Thread-safe request counters for one adapter; bodies are never retained."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values = {"requests": 0, "retries": 0, "throttles": 0, "server_errors": 0,
                        "bytes_sent": 0, "bytes_received": 0, "prompt_tokens": 0,
                        "total_tokens": 0}

    def observe(self, status_code: int, *, sent: int = 0, received: int = 0,
                retried: bool = False) -> None:
        with self._lock:
            self._values["requests"] += 1
            self._values["retries"] += int(retried)
            self._values["throttles"] += int(status_code == 429)
            self._values["server_errors"] += int(status_code >= 500)
            self._values["bytes_sent"] += max(0, int(sent))
            self._values["bytes_received"] += max(0, int(received))

    def observe_response(self, response: Any) -> None:
        """Count one httpx response."""
        try:
            sent = len(response.request.content or b"")
        except (AttributeError, RuntimeError):
            # Streamed request bodies cannot be re-read; count them as zero.
            sent = 0
        self.observe(response.status_code, sent=sent, received=len(response.content or b""))

    def add_usage(self, usage: Any) -> None:
        """Record model token usage reported by an OpenAI response, when present."""
        if not isinstance(usage, dict):
            return
        with self._lock:
            for key in ("prompt_tokens", "total_tokens"):
                value = usage.get(key)
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    self._values[key] += value

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._values)


def adapter_http_stats(adapter: Any) -> "HttpStats | None":
    """Return an adapter's HttpStats without triggering proxy ``__getattr__`` hooks."""
    stats = getattr(adapter, "__dict__", {}).get("http_stats")
    return stats if isinstance(stats, HttpStats) else None


class TelemetryRecorder:
    """Collects timing events; optional ``HttpStats`` supplies per-span request deltas."""

    def __init__(self, phase: str, stats: HttpStats | None = None) -> None:
        self.phase = phase
        self.stats = stats
        self.events: list[dict[str, Any]] = []

    def add(self, event: dict[str, Any] | None) -> None:
        if event is not None:
            self.events.append(event)

    @contextmanager
    def span(self, operation: str, **detail: Any) -> Iterator[dict[str, Any]]:
        """Time a block; callers may set ``counts``, ``bytes`` or ``tokens`` on the yielded dict."""
        fields: dict[str, Any] = {"counts": {}, "bytes": None, "tokens": None}
        before = self.stats.snapshot() if self.stats else None
        wall, started = time.time(), time.perf_counter()
        status = "completed"
        try:
            yield fields
        except BaseException:
            status = "failed"
            raise
        finally:
            duration = (time.perf_counter() - started) * 1000
            delta = ({key: value - before[key] for key, value in self.stats.snapshot().items()}
                     if self.stats and before is not None else {})
            tokens = fields.get("tokens")
            if tokens is None and delta.get("total_tokens"):
                tokens = {"prompt": delta["prompt_tokens"], "total": delta["total_tokens"]}
            size = fields.get("bytes")
            if size is None and delta.get("bytes_sent"):
                size = delta["bytes_sent"]
            counts = dict(fields.get("counts") or {})
            if delta.get("requests"):
                counts.setdefault("requests", delta["requests"])
            self.events.append(telemetry_event(
                self.phase, operation, started_at=_iso(wall),
                ended_at=_iso(wall + duration / 1000), duration_ms=duration,
                status=status, counts=counts, bytes=size,
                retries=delta.get("retries", 0), throttles=delta.get("throttles", 0),
                tokens=tokens, **{**detail, **fields.get("detail", {})},
            ))


def valid_event(value: Any) -> bool:
    return (isinstance(value, dict) and value.get("version") == TELEMETRY_VERSION
            and all(key in value for key in _EVENT_KEYS)
            and isinstance(value["phase"], str) and isinstance(value["operation"], str)
            and isinstance(value["duration_ms"], (int, float))
            and not isinstance(value["duration_ms"], bool) and value["duration_ms"] >= 0)


def append_consume_event(path: str | Path, event: dict[str, Any]) -> None:
    """Append one Consume event to a local JSONL log (one line, no customer content)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, sort_keys=True) + "\n")


def consume_event(operation: str, result: dict[str, Any], started_at: float) -> dict[str, Any]:
    """Convert a Consume response's ``telemetry`` block into a shared event."""
    measured = result.get("telemetry") or {}
    duration = measured.get("latency_ms") or 0.0
    counts = {"results": len(result.get("provenance") or [])}
    for key in ("search_round_trips", "chunk_lookups"):
        if isinstance(measured.get(key), int):
            counts[key] = measured[key]
    breakdown = {key: value for key, value in measured.items()
                 if key.endswith("_ms") and key != "latency_ms"}
    return telemetry_event(
        "consume", operation, started_at=_iso(started_at),
        ended_at=_iso(started_at + duration / 1000), duration_ms=duration,
        counts=counts, retries=measured.get("retries", 0),
        throttles=measured.get("throttles", 0), tokens=measured.get("tokens"),
        method=measured.get("method"), breakdown_ms=breakdown,
    )


def read_consume_log(path: str | Path) -> list[dict[str, Any]]:
    events = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if valid_event(item) and item["phase"] == "consume":
            events.append(item)
    return events


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return round(ordered[index], 3)


def summarize_phases(events: Iterable[dict[str, Any]], *,
                     wall_ms: float | None = None) -> list[dict[str, Any]]:
    """Per phase/operation breakdown in first-seen order, with share of total wall time."""
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    items = [event for event in events if valid_event(event)]
    for event in items:
        key = (event["phase"], event["operation"])
        row = rows.setdefault(key, {
            "phase": event["phase"], "operation": event["operation"], "events": 0,
            "duration_ms": 0.0, "retries": 0, "throttles": 0, "bytes": 0,
            "counts": {}, "origins": [], "statuses": [],
        })
        row["events"] += 1
        row["duration_ms"] = round(row["duration_ms"] + event["duration_ms"], 3)
        row["retries"] += event.get("retries") or 0
        row["throttles"] += event.get("throttles") or 0
        row["bytes"] += event.get("bytes") or 0
        for name, value in (event.get("counts") or {}).items():
            if isinstance(value, int) and not isinstance(value, bool):
                row["counts"][name] = row["counts"].get(name, 0) + value
        for field, value in (("origins", event.get("origin")), ("statuses", event.get("status"))):
            if value not in row[field]:
                row[field].append(value)
    starts = [parse_time(event["started_at"]) for event in items]
    ends = [parse_time(event["ended_at"]) for event in items]
    starts = [value for value in starts if value]
    ends = [value for value in ends if value]
    wall = ((max(ends) - min(starts)).total_seconds() * 1000) if starts and ends else (wall_ms or 0.0)
    for row in rows.values():
        row["share_of_wall"] = round(row["duration_ms"] / wall, 4) if wall else None
    return list(rows.values())


def summarize_consume(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        if valid_event(event) and event["phase"] == "consume":
            grouped.setdefault(event["operation"], []).append(event)
    summary = []
    for operation, items in grouped.items():
        latencies = [item["duration_ms"] for item in items]
        summary.append({
            "operation": operation, "count": len(items),
            "p50_ms": _percentile(latencies, 0.5), "p95_ms": _percentile(latencies, 0.95),
            "max_ms": round(max(latencies), 3),
            "mean_ms": round(sum(latencies) / len(latencies), 3),
            "throttles": sum(item.get("throttles") or 0 for item in items),
            "retries": sum(item.get("retries") or 0 for item in items),
        })
    return summary


def summary_text(report: dict[str, Any]) -> str:
    """A short human summary of a telemetry report: wall time and the slowest phases."""
    phases = sorted(report.get("phases") or [], key=lambda row: -(row.get("duration_ms") or 0))
    consume = report.get("consume") or []
    lines = [f"{report.get('run_id') or 'telemetry'}: wall {_duration(report.get('wall_ms'))}, "
             f"{len(phases)} phase(s), {sum(row.get('count', 0) for row in consume)} consume "
             "operation(s)"]
    lines += [f"  {row['phase']}/{row['operation']}: {_duration(row['duration_ms'])}"
              for row in phases[:3]]
    return "\n".join(lines)


def _duration(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "-"
    if value < 1000:
        return f"{value:.0f}ms"
    seconds = value / 1000
    if seconds < 120:
        return f"{seconds:.1f}s"
    return f"{int(seconds // 60)}m{int(seconds % 60):02d}s"
