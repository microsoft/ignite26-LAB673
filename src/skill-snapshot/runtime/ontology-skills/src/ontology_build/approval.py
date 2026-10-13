"""`review` and `approve`."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from typing import Any

from ontology_core import hashing, state
from ontology_core.errors import Blocked
from ontology_core.journal import Journal, StateLock
from ontology_core.model import Approval, Diff, Ontology, Version
from ontology_core.state import StatePaths

TOP_CLASSES = 10


def approve_command(n: int, schema_id: str) -> str:
    return f"ontology-build approve --version {n} --schema-id {schema_id}"


def diff_summary(diff: Diff | None) -> dict[str, Any] | None:
    if diff is None:
        return None
    return {
        "from_version": diff.from_version,
        "added": {"classes": len(diff.added.classes), "properties": len(diff.added.properties)},
        "removed": {"classes": len(diff.removed.classes), "properties": len(diff.removed.properties)},
        "changed": len(diff.changed),
        "coverage_regressions": [c.name for c in diff.coverage_regressions],
        "seed_violations": list(diff.seed_violations),
    }


def _class_row(ontology: Ontology, name: str) -> dict[str, Any]:
    c = ontology.find_class(name)
    assert c is not None
    return {"name": c.name, "evidence": len(c.evidence), "description": c.description}


def refinement(paths: StatePaths, meta: Version) -> dict[str, Any] | None:
    """For a version written by `refine` (or `revise --from-critique`): per-round scores, findings fixed vs
    remaining, the stop reason and the diff from the version refine started from. None otherwise."""
    if meta.origin != "revise" or not meta.plan_id:
        return None
    from ontology_build import critique, refine
    from ontology_core import diff as diff_mod

    record = refine.load_record(paths, meta.plan_id)
    if record is None:
        cid = critique.critique_id_for_plan(meta.plan_id)
        path = paths.critique(cid)
        return {"critique": critique.summary(state.read_json(path))} if path.is_file() else None
    rounds = record["rounds"]
    if not rounds:
        return None
    first, last = set(rounds[0]["fingerprints"]), set(rounds[-1]["fingerprints"])
    start = record["start_version"]
    _, before = state.load_version(paths, start)
    _, after = state.load_version(paths, meta.version)
    return {
        "start_version": start, "final_version": record.get("final_version"), "stop_reason": record["stop"],
        "repeated": record.get("repeated", []),
        "rounds": [{k: r[k] for k in ("round", "version_in", "scores", "total", "max_total", "findings",
                                      "applied", "version_out", "stop")} for r in rounds],
        "fixed": sorted(first - last), "remaining": sorted(last),
        "diff_from_start": diff_summary(diff_mod.diff(before, after)),
    }


def review(paths: StatePaths, version: int | None = None, *, details: bool = False) -> dict[str, Any]:
    """Counts, top classes by evidence, diff vs parent, hygiene drops, coverage regressions; `details` lists
    every type. Returns `{status:"ok", version, schema_id, approved, classes, properties, diff, hygiene,
    next_step}` (next_step: the approve command with the schema ID).

    Raises: VERSION_NOT_FOUND, SCHEMA_ID_MISMATCH, STATE_INCOMPATIBLE.
    """
    meta, ontology = state.load_version(paths, version)
    n = meta.version
    approval = state.load_approval(paths, n)
    approved = approval is not None and approval.schema_id == meta.schema_id
    ranked = sorted(ontology.classes, key=lambda c: (-len(c.evidence), c.name))
    classes: dict[str, Any] = {"count": len(ontology.classes),
                               "top": [_class_row(ontology, c.name) for c in ranked[:TOP_CLASSES]]}
    kinds = Counter(p.kind for p in ontology.properties)
    properties: dict[str, Any] = {"count": len(ontology.properties), "object": kinds.get("object", 0),
                                  "datatype": kinds.get("datatype", 0)}
    if details:
        classes["all"] = [{"name": c.name, "parent": c.parent, "evidence": len(c.evidence), "seed": c.seed,
                           "description": c.description} for c in sorted(ontology.classes, key=lambda c: c.name)]
        properties["all"] = [{"name": p.name, "kind": p.kind, "domain": p.domain, "range": p.range,
                              "evidence": len(p.evidence), "seed": p.seed, "description": p.description}
                             for p in sorted(ontology.properties, key=lambda p: (p.name, p.domain))]
    diff = state.load_diff(paths, n)
    hygiene = meta.hygiene
    dropped = Counter(d.reason for d in hygiene.dropped)
    if approved:
        next_step = f"ontology-build export --version {n} --output <file.owl>"
    else:
        next_step = approve_command(n, meta.schema_id)
    return {
        "status": "ok",
        "version": n,
        "schema_id": meta.schema_id,
        "origin": meta.origin,
        "parent_version": meta.parent_version,
        "approved": approved,
        "classes": classes,
        "properties": properties,
        "diff": diff_summary(diff),
        "coverage_regressions": [asdict(c) for c in (diff.coverage_regressions if diff else [])],
        "hygiene": {
            "dropped": dict(sorted(dropped.items())),
            "dropped_names": [d.name for d in hygiene.dropped][:50] if details else [],
            "renamed": len(hygiene.renamed),
            "qualified": len(hygiene.qualified),
            "warnings": list(hygiene.warnings),
        },
        "refinement": refinement(paths, meta),
        "next_step": next_step,
    }


def approve(paths: StatePaths, version: int, schema_id: str) -> dict[str, Any]:
    """Recompute `schema_id` from bytes, then write `approval.json` and journal `artifact_written` +
    `schema_approved` under the lock. Idempotent for an already-approved identical version.

    Raises: VERSION_NOT_FOUND, SCHEMA_ID_MISMATCH (disk bytes or `--schema-id` differ), STATE_LOCKED.
    """
    n = state.resolve_version(paths, version)
    with StateLock(paths, "approve"):
        meta: Version
        meta, ontology = state.load_version(paths, n)  # verifies the bytes still hash to schema_id
        actual = hashing.schema_id_of_bytes(paths.ontology(n).read_bytes())
        if schema_id != actual:
            raise Blocked("SCHEMA_ID_MISMATCH", f"v{n} has schema ID {actual}, not {schema_id}",
                          details={"version": n, "schema_id": actual},
                          next_step=f"`ontology-build review --version {n}`, then approve the schema ID it prints")
        existing = state.load_approval(paths, n)
        base = {"status": "ok", "version": n, "schema_id": actual,
                "diff": diff_summary(state.load_diff(paths, n)), "warnings": list(meta.hygiene.warnings),
                "next_step": f"ontology-build export --version {n} --output <file.owl>"}
        if existing is not None and existing.schema_id == actual:
            pointer = _record_current(paths, n, meta, ontology, existing.approved_at)
            return {**base, "already_approved": True, "approved_at": existing.approved_at, "actor": existing.actor,
                    "current": pointer}
        record = Approval(version=n, schema_id=actual, approved_at=state.utc_now(), actor=state.actor())
        journal = Journal(paths)
        sha = state.write_record(paths.approval(n), record)
        journal.append("artifact_written", path=paths.relative(paths.approval(n)), sha256=sha)
        journal.append("schema_approved", version=n, schema_id=actual, actor=record.actor)
        pointer = _record_current(paths, n, meta, ontology, record.approved_at)
    return {**base, "already_approved": False, "approved_at": record.approved_at, "actor": record.actor,
            "current": pointer}


def _record_current(paths: StatePaths, n: int, meta: Version, ontology: Ontology, approved_at: str) -> str:
    from ontology_build import export

    return export.record_current(paths, n, meta, ontology, approved_at)["path"]
