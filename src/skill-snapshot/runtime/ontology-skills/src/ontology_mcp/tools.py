"""MCP tool specs and dispatch.

The specs are final: 8 tools, all `readOnlyHint: true`; `openWorldHint` only where Azure is reached.
Every tool accepts an optional absolute `state_dir`. Handlers call `ontology_consume.service`,
`ontology_core.doctor` and `ontology_build.connection` (the estimate never saves a plan).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ontology_core.errors import Blocked

_STATE_DIR = {"type": "string", "description": "absolute path of the state directory (optional)"}


def _schema(properties: dict[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    return {"type": "object", "properties": {**properties, "state_dir": _STATE_DIR},
            "required": list(required), "additionalProperties": False}


def _tool(name: str, description: str, schema: dict[str, Any], *, open_world: bool = False) -> dict[str, Any]:
    return {"name": name, "description": description, "inputSchema": schema,
            "annotations": {"readOnlyHint": True, "openWorldHint": open_world}}


TOOLS: list[dict[str, Any]] = [
    _tool("ontology_doctor", "Check install, state dir, sign-in, GRZ and model access. Sends no completions.",
          _schema({}), open_world=True),
    _tool("ontology_status", "Connection, versions, approved schema, last run, latest critique and the next step.", _schema({})),
    _tool("ontology_show", "Classes and properties of an ontology version, optionally as a Mermaid diagram.",
          _schema({"version": {"type": "integer", "minimum": 0},
                   "limit": {"type": "integer", "minimum": 0, "maximum": 200},
                   "offset": {"type": "integer", "minimum": 0},
                   "mermaid": {"type": "boolean"}})),
    _tool("ontology_evidence", "Corpus passages cited as evidence for a class or property.",
          _schema({"type": {"type": "string"}, "version": {"type": "integer", "minimum": 0},
                   "limit": {"type": "integer", "minimum": 0, "maximum": 50}}, ("type",))),
    _tool("ontology_diff", "What changed between two ontology versions.",
          _schema({"a": {"type": "integer", "minimum": 0}, "b": {"type": "integer", "minimum": 0}}, ("a", "b"))),
    _tool("ontology_check", "Validate an OWL file against the flat-owl profile.",
          _schema({"path": {"type": "string", "description": "absolute path of the OWL file"}}, ("path",))),
    _tool("ontology_plan_estimate", "Estimate passages, calls and cost for a proposal run. Does not save a plan.",
          _schema({"max_spend_usd": {"type": "number", "minimum": 0},
                   "seed": {"type": "string", "description": "absolute path of a seed ontology"},
                   "level": {"type": "integer", "minimum": 0},
                   "passages": {"type": "integer", "minimum": 1},
                   "excerpt_chars": {"type": "integer", "minimum": 1},
                   "shard_chars": {"type": "integer", "minimum": 1},
                   "reasoning_effort": {"type": "string", "enum": ["minimal", "low", "medium", "high"]},
                   "max_output_tokens": {"type": "integer", "minimum": 1},
                   "max_tokens": {"type": "integer", "minimum": 1}}, ("max_spend_usd",)),
          open_world=True),
    _tool("ontology_current", "The current approved ontology for this user: flat-owl path, sha256, IRI, "
          "class and property counts, source generation and approval time.", _schema({})),
]
TOOL_NAMES = tuple(t["name"] for t in TOOLS)

Handler = Callable[[Path, dict[str, Any]], dict[str, Any]]
"""`handler(state_dir, arguments_without_state_dir) -> result dict`, raising `Blocked`."""


def not_implemented(state_dir: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    raise Blocked("NOT_IMPLEMENTED", "this tool is not implemented in this build")


def _paths(state_dir: Path) -> Any:
    from ontology_core import state

    return state.paths_for(state_dir)


def _int(arguments: dict[str, Any], key: str, default: int | None, maximum: int | None = None) -> int | None:
    value = arguments.get(key, default)
    if value is None:
        return None
    value = max(0, int(value))
    return min(value, maximum) if maximum is not None else value


def doctor(state_dir: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    from ontology_build import connection
    from ontology_core import doctor as checks

    paths = _paths(state_dir)
    return checks.report(connection.run_doctor(connection.doctor_context(paths), paths))


def current(state_dir: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    from ontology_core import current as pointer

    return pointer.result()


def status(state_dir: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    from ontology_consume import service

    return service.status(_paths(state_dir))


def show(state_dir: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    from ontology_consume import service

    return service.show(_paths(state_dir), version=_int(arguments, "version", None),
                        limit=_int(arguments, "limit", service.SHOW_DEFAULT_LIMIT, 200) or 0,
                        offset=_int(arguments, "offset", 0) or 0, mermaid=bool(arguments.get("mermaid", False)))


def evidence(state_dir: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    from ontology_consume import service

    return service.evidence(_paths(state_dir), str(arguments["type"]), version=_int(arguments, "version", None),
                            limit=_int(arguments, "limit", service.EVIDENCE_DEFAULT_LIMIT, 50) or 0)


def diff(state_dir: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    from ontology_consume import service

    return service.diff(_paths(state_dir), int(arguments["a"]), int(arguments["b"]))


def check(state_dir: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    from ontology_consume import service

    path = Path(str(arguments["path"]))
    if not path.is_absolute():
        raise Blocked("IMPORT_INVALID", f"path must be an absolute path, got {str(path)!r}",
                      next_step="pass the OWL file as an absolute path")
    return service.check(path)


def plan_estimate(state_dir: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    from ontology_build import connection

    request = connection.plan_request(
        max_spend_usd=float(arguments["max_spend_usd"]), seed=arguments.get("seed"),
        level=_int(arguments, "level", None), passages=_int(arguments, "passages", None),
        excerpt_chars=_int(arguments, "excerpt_chars", 1200) or 1200,
        shard_chars=_int(arguments, "shard_chars", 60000) or 60000,
        reasoning_effort=str(arguments.get("reasoning_effort", "low")),
        max_output_tokens=_int(arguments, "max_output_tokens", 8000) or 8000,
        max_tokens=_int(arguments, "max_tokens", None))
    return connection.estimate(_paths(state_dir), request)


HANDLERS: dict[str, Handler] = {
    "ontology_doctor": doctor, "ontology_status": status, "ontology_show": show, "ontology_evidence": evidence,
    "ontology_diff": diff, "ontology_check": check, "ontology_plan_estimate": plan_estimate,
    "ontology_current": current,
}


def resolve_state_dir(arguments: dict[str, Any], default: Path) -> Path:
    """The tool's `state_dir` if given (must be absolute), else the server's bound dir.

    Raises:
        Blocked("STATE_DIR_UNWRITABLE"): `state_dir` is relative.
    """
    value = arguments.get("state_dir")
    if value is None:
        return default
    path = Path(str(value))
    if not path.is_absolute():
        raise Blocked("STATE_DIR_UNWRITABLE", f"state_dir must be an absolute path, got {value!r}")
    return path
