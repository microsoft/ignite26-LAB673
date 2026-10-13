"""Append-only journal and the state lock.

The journal holds hashes and numbers only: never passage text, prompts or tokens.
Every entry is `{seq, ts, event, ...extras}` with exactly the extra fields listed in `EVENTS`.
"""

from __future__ import annotations

import json
import os
import socket
import sys
from collections.abc import Iterator
from pathlib import Path
from types import TracebackType
from typing import Any

from ontology_core import hashing
from ontology_core.errors import Blocked
from ontology_core.model import LockInfo, SchemaError
from ontology_core.state import StatePaths, ensure_dir, utc_now

EVENTS: dict[str, tuple[str, ...]] = {
    "connected": ("tenant_id", "generation_id", "model_deployment"),
    "plan_saved": ("plan_id", "estimate_usd", "max_spend_usd"),
    "run_started": ("plan_id", "approved_budget_usd", "actor"),
    "call_requested": ("plan_id", "call", "request_sha256", "reserve_tokens", "reserve_usd"),
    "call_completed": ("plan_id", "call", "response_sha256", "prompt_tokens", "completion_tokens", "usd",
                       "finish_reason"),
    "call_failed": ("plan_id", "call", "http_status", "billed"),
    "call_unknown": ("plan_id", "call", "reserve_usd"),
    "artifact_written": ("path", "sha256"),
    "version_created": ("version", "schema_id", "origin", "plan_id"),
    "schema_approved": ("version", "schema_id", "actor"),
    "export_written": ("version", "schema_id", "format", "output", "sha256"),
    "run_finished": ("plan_id", "status", "spent_usd"),
    "lock_released_stale": ("pid", "host"),
}
BASE_FIELDS = ("seq", "ts", "event")
RUN_STATUSES = ("completed", "blocked", "budget_exhausted")
VERSION_ORIGINS = ("propose", "import", "revise")
UNBILLED_HTTP = frozenset({400, 401, 403, 404, 429})


def validate_event(entry: dict[str, Any]) -> None:
    """Raise `ValueError` unless `entry` has exactly the base fields plus its event's extras."""
    event = entry.get("event")
    if event not in EVENTS:
        raise ValueError(f"unknown journal event {event!r}")
    expected = set(BASE_FIELDS) | set(EVENTS[event])
    actual = set(entry)
    if actual != expected:
        missing, extra = sorted(expected - actual), sorted(actual - expected)
        raise ValueError(f"{event}: missing {missing} extra {extra}")
    if not isinstance(entry["seq"], int) or isinstance(entry["seq"], bool) or entry["seq"] < 1:
        raise ValueError(f"{event}: seq must be a positive integer")
    if event == "run_finished" and entry["status"] not in RUN_STATUSES:
        raise ValueError(f"run_finished: bad status {entry['status']!r}")
    if event == "version_created" and entry["origin"] not in VERSION_ORIGINS:
        raise ValueError(f"version_created: bad origin {entry['origin']!r}")
    if event == "call_failed" and not isinstance(entry["billed"], bool):
        raise ValueError("call_failed: billed must be a bool")


class Journal:
    """`journal.jsonl` in a state dir. Appends require the caller to hold `StateLock`."""

    def __init__(self, paths: StatePaths) -> None:
        self.paths = paths
        self.path = paths.journal
        self._last_seq: int | None = None

    def read(self) -> list[dict[str, Any]]:
        """All entries. A bad line, unknown event or non-increasing `seq` is `JOURNAL_DRIFT`."""
        if not self.path.is_file():
            self._last_seq = 0
            return []
        entries: list[dict[str, Any]] = []
        last = 0
        for number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                if not isinstance(entry, dict):
                    raise ValueError("entry is not an object")
                validate_event(entry)
            except ValueError as exc:
                raise Blocked("JOURNAL_DRIFT", f"journal line {number}: {exc}",
                              details={"path": str(self.path), "line": number}) from exc
            if entry["seq"] <= last:
                raise Blocked("JOURNAL_DRIFT", f"journal line {number}: seq {entry['seq']} after {last}",
                              details={"path": str(self.path), "line": number})
            last = entry["seq"]
            entries.append(entry)
        self._last_seq = last
        return entries

    def events(self, *names: str, **match: Any) -> Iterator[dict[str, Any]]:
        """Entries whose event is in `names` (all when empty) and whose fields equal `match`."""
        for entry in self.read():
            if names and entry["event"] not in names:
                continue
            if all(entry.get(k) == v for k, v in match.items()):
                yield entry

    def append(self, event: str, **fields: Any) -> dict[str, Any]:
        """Validate, assign `seq`/`ts`, append one canonical line with O_APPEND, flush and fsync."""
        if self._last_seq is None:
            self.read()
        assert self._last_seq is not None
        entry = {"seq": self._last_seq + 1, "ts": utc_now(), "event": event, **fields}
        try:
            validate_event(entry)
        except ValueError as exc:
            raise Blocked("INTERNAL_ERROR", f"invalid journal entry: {exc}") from exc
        ensure_dir(self.path.parent)
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_BINARY", 0)
        fd = os.open(self.path, flags, 0o600)
        try:
            os.write(fd, hashing.canonical_bytes(entry))
            os.fsync(fd)
        finally:
            os.close(fd)
        self._last_seq = entry["seq"]
        return entry


# --------------------------------------------------------------------------- lock


def pid_alive(pid: int) -> bool:
    """Whether a process with `pid` is running on this host."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        process_query_limited_information, still_active = 0x1000, 259
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5  # access denied: exists but not ours
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def this_host() -> str:
    return socket.gethostname()


def read_lock(paths: StatePaths) -> LockInfo | None:
    """The current lock, or None. An unreadable lock file is reported as pid 0 on host '?'."""
    if not paths.lock.is_file():
        return None
    try:
        return LockInfo.from_dict(json.loads(paths.lock.read_text(encoding="utf-8")))
    except (ValueError, SchemaError):
        return LockInfo(pid=0, host="?", verb="?", started_at="?")


def _locked(info: LockInfo) -> Blocked:
    return Blocked("STATE_LOCKED", f"state is locked by {info.verb} (pid {info.pid} on {info.host})",
                   pid=info.pid, host=info.host, details=info.to_dict())


class StateLock:
    """`with StateLock(paths, "propose"):` creates `.lock` with O_CREAT|O_EXCL or raises STATE_LOCKED."""

    def __init__(self, paths: StatePaths, verb: str) -> None:
        self.paths = paths
        self.verb = verb
        self.info: LockInfo | None = None

    def acquire(self) -> LockInfo:
        ensure_dir(self.paths.root)
        info = LockInfo(pid=os.getpid(), host=this_host(), verb=self.verb, started_at=utc_now())
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        try:
            fd = os.open(self.paths.lock, flags, 0o600)
        except FileExistsError:
            current = read_lock(self.paths) or info
            raise _locked(current) from None
        try:
            os.write(fd, hashing.canonical_bytes(info.to_dict()))
            os.fsync(fd)
        finally:
            os.close(fd)
        self.info = info
        return info

    def release(self) -> None:
        if self.info is None:
            return
        current = read_lock(self.paths)
        if current is not None and current.pid == self.info.pid and current.host == self.info.host:
            Path(self.paths.lock).unlink(missing_ok=True)
        self.info = None

    def __enter__(self) -> StateLock:
        self.acquire()
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 tb: TracebackType | None) -> None:
        self.release()


def release_stale(paths: StatePaths, journal: Journal, *, force: bool = False) -> LockInfo | None:
    """Remove a stale lock and journal `lock_released_stale`. Returns the removed lock, or None if
    there was none. Same host + dead pid is removed automatically; another host needs `force`
    (`reconcile --release-lock`). A live lock on this host is `STATE_LOCKED` even with `force`."""
    info = read_lock(paths)
    if info is None:
        return None
    same_host = info.host == this_host()
    if same_host and pid_alive(info.pid):
        raise _locked(info)
    if not same_host and not force:
        raise _locked(info)
    paths.lock.unlink(missing_ok=True)
    journal.append("lock_released_stale", pid=info.pid, host=info.host)
    return info
