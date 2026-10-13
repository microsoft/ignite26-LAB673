"""Local user state (outside the repo): saved connection, plans, journals, descriptors."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def state_dir() -> Path:
    override = os.environ.get("GROUNDING_HOME")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCAL" + "APP" + "DATA") or Path.home() / ("App" + "Data") / "Local") / "grounding-skills"
    else:
        base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "grounding-skills"
    return base


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path) -> Any | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_connection() -> dict[str, Any] | None:
    return _read_json(state_dir() / "connection.json")


def save_connection(conn: dict[str, Any]) -> Path:
    p = state_dir() / "connection.json"
    _write_json(p, conn)
    return p


def plan_dir(plan_id: str) -> Path:
    return state_dir() / "plans" / plan_id


def save_plan(plan: dict[str, Any]) -> Path:
    p = plan_dir(plan["plan_id"]) / "plan.json"
    _write_json(p, plan)
    return p


def load_plan(plan_id: str) -> dict[str, Any] | None:
    return _read_json(plan_dir(plan_id) / "plan.json")


def save_edges(plan_id: str, edges: list[dict[str, Any]]) -> Path:
    p = plan_dir(plan_id) / "edges.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="\n") as f:
        for e in edges:
            f.write(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n")
    return p


def load_edges(plan_id: str) -> list[dict[str, Any]]:
    p = plan_dir(plan_id) / "edges.jsonl"
    if not p.is_file():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def journal_path(plan_id: str) -> Path:
    return plan_dir(plan_id) / "journal.json"


def load_journal(plan_id: str) -> dict[str, Any] | None:
    return _read_json(journal_path(plan_id))


def save_journal(plan_id: str, journal: dict[str, Any]) -> None:
    _write_json(journal_path(plan_id), journal)


def save_descriptor(index: str, descriptor: dict[str, Any]) -> Path:
    p = state_dir() / "descriptors" / f"{index}.json"
    _write_json(p, descriptor)
    return p


def load_descriptor(index: str) -> dict[str, Any] | None:
    return _read_json(state_dir() / "descriptors" / f"{index}.json")
