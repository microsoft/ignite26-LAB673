"""Read-only services shared by `ontology-consume` and the MCP tools.

Every function returns the `--json` result dict (status "ok") or raises `Blocked`. None take the lock or
write anything; none reach Azure.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ontology_core import diff as diff_mod
from ontology_core import hashing, owl_read, profile, state
from ontology_core.errors import Blocked
from ontology_core.journal import Journal
from ontology_core.model import Config, Version
from ontology_core.state import StatePaths
from ontology_consume import mermaid as mermaid_mod

SHOW_DEFAULT_LIMIT = 50
SHOW_MAX_LIMIT = 200
EVIDENCE_DEFAULT_LIMIT = 10
EVIDENCE_MAX_LIMIT = 50
CONNECT_HINT = ("ontology-build connect --tenant-id <guid> --grz-descriptor <descriptor.json> "
                "--model-endpoint <https://account.openai.azure.com> --model-deployment <name> "
                "--model-input-price-per-1m <usd> --model-output-price-per-1m <usd>")


def _clamp(value: int | None, default: int, maximum: int) -> int:
    if value is None:
        return default
    return max(0, min(int(value), maximum))


def _config(paths: StatePaths) -> Config | None:
    return state.load_config(paths) if paths.config.is_file() else None


def _last_run(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    started = [e for e in entries if e["event"] == "run_started"]
    if not started:
        return None
    last = started[-1]
    plan_id = last["plan_id"]
    finished = [e for e in entries if e["event"] == "run_finished" and e["plan_id"] == plan_id]
    completed = [e for e in entries if e["event"] == "call_completed" and e["plan_id"] == plan_id]
    spent = finished[-1]["spent_usd"] if finished else round(sum(e["usd"] for e in completed), 6)
    return {"plan_id": plan_id, "status": finished[-1]["status"] if finished else "running_or_interrupted",
            "approved_budget_usd": last["approved_budget_usd"], "spent_usd": spent, "calls_completed": len(completed),
            "started_at": last["ts"], "finished_at": finished[-1]["ts"] if finished else None}


def _latest_critique(paths: StatePaths) -> dict[str, Any] | None:
    from ontology_build import critique

    return critique.latest(paths)


def status(paths: StatePaths) -> dict[str, Any]:
    """Connection, generation, versions, approved schema, last run and spend, one `next_step`.
    Shared with `ontology-build status`. Works on an empty/missing state dir (next_step: connect)."""
    config = _config(paths)
    entries = Journal(paths).read() if paths.journal.is_file() else []
    rows = []
    for n in state.list_versions(paths):
        meta = state.read_record(paths.version_json(n), Version)
        approval = state.load_approval(paths, n)
        rows.append({"version": n, "origin": meta.origin, "schema_id": meta.schema_id,
                     "created_at": meta.created_at,
                     "approved": approval is not None and approval.schema_id == meta.schema_id})
    approved = next((r for r in reversed(rows) if r["approved"]), None)
    exports = [e for e in entries if e["event"] == "export_written"]
    last_run = _last_run(entries)
    plans = sorted(p.stem for p in paths.plans_dir.glob("*.json")) if paths.plans_dir.is_dir() else []
    latest = rows[-1] if rows else None

    if config is None and not rows:
        next_step = CONNECT_HINT
    elif last_run and last_run["status"] in ("running_or_interrupted", "blocked"):
        from ontology_build.reconcile import plan_verb

        next_step = (f"rerun the same `ontology-build {plan_verb(paths, last_run['plan_id'])} --plan-id "
                     f"{last_run['plan_id']} --approved-budget-usd <amount> --approve-model-calls` command to resume")
    elif latest and not latest["approved"]:
        next_step = f"ontology-build review --version {latest['version']}"
    elif approved and not any(e["version"] == approved["version"] and e["schema_id"] == approved["schema_id"]
                              for e in exports):
        next_step = f"ontology-build export --version {approved['version']} --output <file.owl>"
    elif approved:
        last_export = [e for e in exports if e["version"] == approved["version"]][-1]
        next_step = f"ontology-consume check {last_export['output']}"
    elif config is not None and not plans:
        next_step = "ontology-build inspect, then ontology-build plan --model-max-spend-usd <usd>"
    else:
        next_step = "ontology-build plan --model-max-spend-usd <usd>"

    connection = None
    if config is not None:
        connection = {"tenant_id": config.tenant_id, "tenant_name": config.tenant_name,
                      "generation_id": config.grz.generation_id, "physical_index": config.grz.physical_index,
                      "model_deployment": config.model.deployment, "model_name": config.model.model_name,
                      "model_version": config.model.model_version}
    return {
        "status": "ok",
        "state_dir": str(paths.root),
        "connected": config is not None,
        "connection": connection,
        "versions": rows,
        "approved": approved,
        "exports": [{"version": e["version"], "output": e["output"], "sha256": e["sha256"]} for e in exports[-5:]],
        "plans": len(plans),
        "latest_critique": _latest_critique(paths),
        "last_run": last_run,
        "next_step": next_step,
    }


def show(paths: StatePaths, *, version: int | None = None, limit: int = SHOW_DEFAULT_LIMIT, offset: int = 0,
         mermaid: bool = False) -> dict[str, Any]:
    """`{status, version, schema_id, approved, total:{classes, properties}, classes:[...], properties:[...],
    mermaid?}` paged over classes then properties.

    Raises: VERSION_NOT_FOUND, SCHEMA_ID_MISMATCH.
    """
    meta, ontology = state.load_version(paths, version)
    limit = _clamp(limit, SHOW_DEFAULT_LIMIT, SHOW_MAX_LIMIT)
    offset = max(0, int(offset or 0))
    approval = state.load_approval(paths, meta.version)
    items: list[tuple[str, dict[str, Any]]] = []
    for c in sorted(ontology.classes, key=lambda c: c.name):
        items.append(("class", {"name": c.name, "description": c.description, "parent": c.parent,
                                "evidence": len(c.evidence), "seed": c.seed}))
    for p in sorted(ontology.properties, key=lambda p: (p.name, p.domain)):
        items.append(("property", {"name": p.name, "kind": p.kind, "domain": p.domain, "range": p.range,
                                   "description": p.description, "evidence": len(p.evidence), "seed": p.seed}))
    page = items[offset:offset + limit]
    end = offset + len(page)
    result: dict[str, Any] = {
        "status": "ok",
        "version": meta.version,
        "schema_id": meta.schema_id,
        "origin": meta.origin,
        "approved": approval is not None and approval.schema_id == meta.schema_id,
        "total": {"classes": len(ontology.classes), "properties": len(ontology.properties)},
        "offset": offset,
        "limit": limit,
        "classes": [row for kind, row in page if kind == "class"],
        "properties": [row for kind, row in page if kind == "property"],
        "next_offset": end if end < len(items) else None,
    }
    if mermaid:
        result["mermaid"] = mermaid_mod.class_diagram(ontology)
    first = next((row["name"] for kind, row in items if kind == "class"), None)
    if result["next_offset"] is not None:
        result["next_step"] = f"ontology-consume show --version {meta.version} --offset {end}"
    elif first:
        result["next_step"] = f"ontology-consume evidence {first} --version {meta.version}"
    return result


def diagram(paths: StatePaths, *, version: int | None = None, with_datatype: bool = False,
            output: Path | None = None) -> dict[str, Any]:
    """`{status, version, schema_id, classes, edges, mermaid, output?}`: the exact `mermaid.full_diagram` of a
    version. With `output`, writes the diagram there (UTF-8) as the verb's only write.

    Raises: VERSION_NOT_FOUND, SCHEMA_ID_MISMATCH.
    """
    meta, ontology = state.load_version(paths, version)
    text = mermaid_mod.full_diagram(ontology, with_datatype=with_datatype)
    result: dict[str, Any] = {
        "status": "ok",
        "version": meta.version,
        "schema_id": meta.schema_id,
        "classes": len(ontology.classes),
        "edges": len({(p.domain, p.range) for p in ontology.properties if p.kind == "object"}),
        "mermaid": text,
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8", newline="\n")
        result["output"] = str(output)
    return result


def evidence(paths: StatePaths, type_name: str, *, version: int | None = None,
             limit: int = EVIDENCE_DEFAULT_LIMIT) -> dict[str, Any]:
    """Cited passages for a class or property: `{status, type, kind, passages:[{evidence_id, chunk_id,
    source_id, community_id, excerpt}]}`.

    Raises: VERSION_NOT_FOUND, and VERSION_NOT_FOUND with a "no type <name>" error for an unknown type.
    """
    meta, ontology = state.load_version(paths, version)
    n = meta.version
    limit = _clamp(limit, EVIDENCE_DEFAULT_LIMIT, EVIDENCE_MAX_LIMIT)
    cls = ontology.find_class(type_name)
    props = [p for p in ontology.properties if p.name == type_name]
    if cls is None and not props:
        raise Blocked("VERSION_NOT_FOUND", f"no type {type_name} in v{n}",
                      next_step=f"ontology-consume show --version {n}")
    ids: list[str] = []
    for item in ([cls] if cls else []) + props:
        ids.extend(i for i in item.evidence if i not in ids)
    by_id = {e.evidence_id: e for e in state.load_evidence(paths, n)}
    passages = []
    for evidence_id in ids:
        record = by_id.get(evidence_id)
        if record is None:
            passages.append({"evidence_id": evidence_id, "missing": True})
            continue
        passages.append({"evidence_id": record.evidence_id, "chunk_id": record.chunk_id,
                         "source_id": record.source_id, "community_id": record.community_id,
                         "level": record.level, "excerpt": record.excerpt})
    kind = "class" if cls else "property"
    definition = cls.description if cls else props[0].description
    return {"status": "ok", "version": n, "type": type_name, "kind": kind, "description": definition,
            "seed": bool(cls.seed if cls else props[0].seed), "total": len(ids), "passages": passages[:limit]}


def diff(paths: StatePaths, a: int, b: int) -> dict[str, Any]:
    """`{status, diff: Diff.to_dict()}` computed with `ontology_core.diff.diff`.

    Raises: VERSION_NOT_FOUND.
    """
    _, first = state.load_version(paths, state.resolve_version(paths, a))
    _, second = state.load_version(paths, state.resolve_version(paths, b))
    return {"status": "ok", "a": a, "b": b, "diff": diff_mod.diff(first, second).to_dict()}


def check(file: Path) -> dict[str, Any]:
    """Profile-check any OWL file: `{status:"ok", file, owl_sha256, violations:[]}`.

    Raises: PROFILE_VIOLATION (file=...), IMPORT_INVALID (unreadable or over 5 MB).
    """
    target = Path(file).expanduser()
    if not target.is_file():
        raise Blocked("IMPORT_INVALID", f"{target} does not exist or is not a file",
                      next_step="pass the path of an exported .owl file")
    size = target.stat().st_size
    if size > owl_read.MAX_BYTES:
        raise Blocked("IMPORT_INVALID", f"{target} is {size} bytes, over the 5 MB limit")
    try:
        data = target.read_bytes()
    except OSError as exc:
        raise Blocked("IMPORT_INVALID", f"cannot read {target}: {exc.strerror or exc}") from exc
    violations = profile.validate(data)
    if violations:
        shown = "; ".join(str(v) for v in violations[:profile.MAX_REPORTED])
        more = f" (+{len(violations) - profile.MAX_REPORTED} more)" if len(violations) > profile.MAX_REPORTED else ""
        raise Blocked("PROFILE_VIOLATION", f"{len(violations)} profile violation(s): {shown}{more}",
                      details={"violations": [str(v) for v in violations]}, file=str(target))
    return {"status": "ok", "file": str(target), "owl_sha256": hashing.sha256_bytes(data), "violations": []}
