"""The per-user `current` pointer to the approved ontology.

`approve` and `export` write `<home>/current.json` and copy the flat-owl bytes to
`<home>/ontologies/<schema_id>.owl`, so a consumer can say "use the current approved ontology"
instead of passing a file path. `<home>` is `$ONTOLOGY_HOME`, else `%LOCALAPPDATA%\\ontology` on
Windows, else `$XDG_STATE_HOME/ontology` (default `~/.local/state/ontology`).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ontology_core import hashing
from ontology_core.errors import Blocked

POINTER_SCHEMA = "ontology-current-v1"
KIND = "ontology"
REQUIRED = ("schema", "kind", "path", "sha256", "ontology_iri", "classes", "properties", "source_generation",
            "approved_at", "schema_id", "version", "state_dir")


def _is_windows() -> bool:
    return os.name == "nt"


def home() -> Path:
    override = os.environ.get("ONTOLOGY_HOME")
    if override:
        return Path(override).expanduser()
    if _is_windows():
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ("App" + "Data") / "Local")
        return Path(base) / "ontology"
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "ontology"


def pointer_path() -> Path:
    return home() / "current.json"


def record(*, owl: bytes, ontology_iri: str, classes: int, properties: int, source_generation: str | None,
           approved_at: str, schema_id: str, version: int, state_dir: Path,
           exported_to: str | None = None) -> dict[str, Any]:
    """Copy `owl` into the home dir and point `current.json` at it. Returns the pointer."""
    from ontology_core import state

    target = home() / "ontologies" / f"{schema_id.replace(':', '-')}.owl"
    sha = state.atomic_write(target, owl)
    pointer: dict[str, Any] = {
        "schema": POINTER_SCHEMA, "kind": KIND, "path": str(target), "sha256": sha, "ontology_iri": ontology_iri,
        "classes": classes, "properties": properties, "source_generation": source_generation,
        "approved_at": approved_at, "schema_id": schema_id, "version": version,
        "state_dir": str(Path(state_dir).resolve()), "exported_to": exported_to,
    }
    state.write_json(pointer_path(), pointer, canonical=True)
    return pointer


def load(*, required: bool = True) -> dict[str, Any] | None:
    """Read and verify the pointer. `required=False` returns None when there is no pointer yet.

    Raises:
        Blocked("NO_CURRENT"): no pointer and `required`.
        Blocked("CURRENT_INVALID"): unreadable, incomplete, or the file's bytes no longer match.
    """
    import json

    path = pointer_path()
    if not path.is_file():
        if not required:
            return None
        raise Blocked("NO_CURRENT", f"no approved ontology recorded at {path}")
    try:
        pointer = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Blocked("CURRENT_INVALID", f"{path} is unreadable: {exc}") from exc
    missing = [k for k in REQUIRED if not isinstance(pointer, dict) or k not in pointer]
    if missing or pointer.get("schema") != POINTER_SCHEMA:
        raise Blocked("CURRENT_INVALID", f"{path} is incomplete (missing {', '.join(missing) or 'schema'})")
    owl = Path(pointer["path"])
    if not owl.is_file() or hashing.sha256_bytes(owl.read_bytes()) != pointer["sha256"]:
        raise Blocked("CURRENT_INVALID", f"{owl} is missing or no longer matches sha256 {pointer['sha256'][:12]}…")
    return pointer


def result() -> dict[str, Any]:
    """The `current` verb's `--json` result."""
    pointer = load()
    assert pointer is not None
    return {"status": "ok", **{k: v for k, v in pointer.items() if k != "schema"}, "pointer": str(pointer_path()),
            "next_step": f"load the flat-owl file at {pointer['path']}"}
