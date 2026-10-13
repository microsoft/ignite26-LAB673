"""Durable event envelope and single-publisher offline lock."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from grz_core.contracts import ContractError, canonical_json


class State:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def record(self, operation_id: str, generation_id: str | None, stage: str, state: str,
               expected: dict[str, int] | None = None, observed: dict[str, int] | None = None,
               evidence_ids: list[str] | None = None, error_code: str | None = None) -> dict[str, Any]:
        if state not in {"planned", "running", "verified", "published", "failed", "blocked"}:
            raise ContractError("STATE_INVALID", state)
        event = {
            "operation_id": operation_id, "generation_id": generation_id,
            "stage": stage, "state": state, "timestamp": datetime.now(timezone.utc).isoformat(),
            "expected_counts": expected or {}, "observed_counts": observed or {},
            "evidence_ids": evidence_ids or [], "error_code": error_code,
        }
        path = self.root / "events.jsonl"
        with path.open("a", encoding="utf-8") as stream:
            stream.write(canonical_json(event) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        return event

    def events(self) -> list[dict[str, Any]]:
        path = self.root / "events.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

    def save_generation(self, generation_id: str, record: dict[str, Any]) -> None:
        if len(generation_id) != 64 or any(c not in "0123456789abcdef" for c in generation_id):
            raise ContractError("GENERATION_INVALID", "Expected full SHA-256 generation identity")
        path = self.root / f"{generation_id}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(canonical_json(record), encoding="utf-8")
        os.replace(tmp, path)

    def generation(self, generation_id: str) -> dict[str, Any]:
        path = self.root / f"{generation_id}.json"
        if not path.exists():
            raise ContractError("GENERATION_UNKNOWN", generation_id)
        return json.loads(path.read_text(encoding="utf-8"))


    def record_write(self, plan_id: str, generation_id: str | None, operation: str, phase: str,
                     target: str, *, key_digest: str | None = None,
                     status: str = "intent", error_code: str | None = None,
                     detail: dict[str, Any] | None = None) -> dict[str, Any]:
        if status not in {"intent", "confirmed", "failed", "ambiguous", "reconciled"}:
            raise ContractError("STATE_INVALID", status)
        event = {
            "plan_id": plan_id, "generation_id": generation_id, "operation": operation,
            "phase": phase, "target": target, "key_digest": key_digest,
            "status": status, "error_code": error_code, "detail": detail or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        path = self.root / "writes.jsonl"
        with path.open("a", encoding="utf-8") as stream:
            stream.write(canonical_json(event) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        return event

    def write_events(self) -> list[dict[str, Any]]:
        path = self.root / "writes.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

    def unresolved_writes(self, plan_id: str) -> list[dict[str, Any]]:
        events = [event for event in self.write_events() if event.get("plan_id") == plan_id]
        resolved = {(e.get("phase"), e.get("target"), e.get("key_digest")) for e in events
                    if e.get("status") in {"confirmed", "reconciled"}}
        return [e for e in events if e.get("status") in {"failed", "ambiguous"}
                and (e.get("phase"), e.get("target"), e.get("key_digest")) not in resolved]

    def has_reconcile(self, plan_id: str) -> bool:
        return any(e.get("plan_id") == plan_id and e.get("status") == "reconciled" for e in self.write_events())

    def owns_index(self, plan_id: str, index: str) -> bool:
        return any(e.get("plan_id") == plan_id and e.get("target") == index and e.get("phase") == "create-index"
                   and e.get("status") in {"intent", "confirmed", "reconciled"} for e in self.write_events())

    @contextmanager
    def publisher_lock(self) -> Iterator[None]:
        lock = self.root / "publisher.lock"
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise ContractError("PUBLISHER_BUSY", "Another operation owns the sidecar; inspect its state before recovery") from exc
        try:
            os.write(fd, f"{os.getpid()}\n".encode("ascii"))
            os.close(fd)
            yield
        finally:
            lock.unlink(missing_ok=True)
