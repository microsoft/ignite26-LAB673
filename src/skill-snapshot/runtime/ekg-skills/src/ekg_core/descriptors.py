from __future__ import annotations

import os
import re
from pathlib import Path


def ekg_home() -> Path:
    return Path(os.environ.get("EKG_HOME") or Path.home() / ".ekg").expanduser().resolve()


def _clean_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip(".-")
    return cleaned or "descriptor"


def descriptor_name(descriptor: dict) -> str:
    endpoints = descriptor.get("endpoints") if isinstance(descriptor, dict) else None
    candidates = []
    if isinstance(endpoints, dict):
        candidates.extend(str(endpoints.get(key) or "") for key in (
            "knowledge_source", "graph_index", "content_index",
        ))
    candidates.extend(str(descriptor.get(key) or "") for key in (
        "build_id", "deployment_id",
    ) if isinstance(descriptor, dict))
    for candidate in candidates:
        name = _clean_name(candidate)
        if name != "descriptor":
            return name
    return "descriptor"


def default_descriptor_path(name: str) -> Path:
    return (ekg_home() / "descriptors" / f"{_clean_name(name)}.json").resolve()


def current_pointer_path() -> Path:
    return (ekg_home() / "descriptors" / "current").resolve()


def descriptor_file(path: str | Path) -> Path:
    """The descriptor a path names, following the `current` pointer if given it."""
    resolved = Path(path).expanduser().resolve()
    return resolve_current() if resolved == current_pointer_path() else resolved


def write_current(path: str | Path) -> Path:
    resolved = Path(path).expanduser().resolve()
    pointer = current_pointer_path()
    pointer.parent.mkdir(parents=True, exist_ok=True)
    temporary = pointer.with_name(pointer.name + ".tmp")
    temporary.write_text(str(resolved) + "\n", encoding="utf-8")
    os.replace(temporary, pointer)
    return resolved


def resolve_current() -> Path:
    pointer = current_pointer_path()
    try:
        value = pointer.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise FileNotFoundError("no current EKG descriptor is published") from error
    if not value:
        raise FileNotFoundError("no current EKG descriptor is published")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError("current descriptor pointer must contain an absolute path")
    return path.resolve()
