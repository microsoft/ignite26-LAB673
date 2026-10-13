"""The per-user record of the last published build, so browsing needs no paths or environment variables."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from grz_core.contracts import ContractError, canonical_json


def grz_home() -> Path:
    """GRZ_HOME wins; otherwise a per-user state folder (LOCALAPPDATA on Windows, XDG state elsewhere)."""
    override = os.environ.get("GRZ_HOME")
    if override:
        return Path(override)
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "grz"
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "grz"


def current_path() -> Path:
    return grz_home() / "current.json"


def record_current(descriptor: dict[str, Any], *, endpoint: str, auth: str, tenant_id: str) -> dict[str, Any]:
    """Copy the published descriptor into the user folder and point current.json at it. Never a key or token."""
    home = grz_home()
    copy = home / "descriptors" / f"{descriptor['generation_id']}.json"
    copy.parent.mkdir(parents=True, exist_ok=True)
    copy.write_text(canonical_json(descriptor), encoding="utf-8")
    pointer = {"descriptor": str(copy.resolve()), "endpoint": endpoint, "auth": auth, "tenant_id": tenant_id,
               "generation_id": descriptor["generation_id"], "physical_index": descriptor["physical_index"]}
    current_path().write_text(canonical_json(pointer), encoding="utf-8")
    return {**pointer, "pointer": str(current_path().resolve())}


def read_current() -> dict[str, Any] | None:
    path = current_path()
    if not path.is_file():
        return None
    try:
        pointer = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError("CURRENT_INVALID", f"Cannot read the current-build record {path}") from exc
    if not isinstance(pointer, dict) or not all(isinstance(pointer.get(k), str) and pointer[k]
                                                for k in ("descriptor", "endpoint", "auth", "tenant_id")):
        raise ContractError("CURRENT_INVALID", f"The current-build record {path} is incomplete")
    return pointer
