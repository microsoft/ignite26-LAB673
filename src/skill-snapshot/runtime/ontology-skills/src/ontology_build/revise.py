"""`revise --from-critique`.

Applies a critique's typed change ops to a version deterministically. No model call, no egress. An op that
names an unknown class/property, a seed item or a name already taken is skipped with a warning, never guessed.

Invariant: revise never writes a version with coverage regressions (a type whose cited passages no other type
of its kind carries). The rules that keep it:

- `rename` moves the type with its evidence, domain/range and every reference. A property rename that only
  adds the domain class as a prefix or suffix (`servesIndustry` -> `organizationServesIndustry`) is skipped
  as `rename_style_only`: properties are already scoped by their domain.
- `drop_property` / `drop_class` of a type with evidence is skipped as `drop_has_evidence` unless its evidence
  has somewhere to go: `merge_into` names an existing type of the same kind, or (properties only) the same
  revision adds a property with the same kind, domain and range. The evidence moves to that replacement.
  A drop waiting for a replacement added later in the list is retried after the other ops.
- Any other op whose result would still lose evidence after hygiene is skipped as `coverage_regression`.
"""

from __future__ import annotations

import copy
from typing import Any

from ontology_build import critique as critique_mod
from ontology_core import hygiene, state
from ontology_core import diff as diff_mod
from ontology_core.errors import Blocked
from ontology_core.journal import Journal, StateLock
from ontology_core.model import ClassDef, EvidenceRecord, HygieneReport, Ontology, PropertyDef, Version
from ontology_core.state import StatePaths

DEFAULT_ACCEPT = ("high", "medium")
RENAME_STYLE_ONLY = "rename_style_only"
DROP_HAS_EVIDENCE = "drop_has_evidence"
COVERAGE_REGRESSION = "coverage_regression"


def accepted_fingerprints(record: dict[str, Any], accept: list[str] | None) -> tuple[set[str], list[str]]:
    """`None` → findings rated high or medium; `["all"]` → every finding; else the given fingerprints.
    Returns `(accepted, warnings)`; a fingerprint the critique does not report is a warning."""
    known = {f["fingerprint"] for f in record["findings"]}
    if accept is None:
        return {f["fingerprint"] for f in record["findings"] if f["severity"] in DEFAULT_ACCEPT}, []
    if [a.lower() for a in accept] == ["all"]:
        return known, []
    return set(accept) & known, [f"--accept {a}: critique {record['critique_id']} has no such finding"
                                 for a in sorted(set(accept) - known)]


class _Work:
    def __init__(self, ontology: Ontology) -> None:
        self.classes = {c.name: copy.deepcopy(c) for c in ontology.classes}
        self.props = {p.name: copy.deepcopy(p) for p in ontology.properties}
        self.added: set[str] = set()

    def taken(self, name: str) -> bool:
        lower = name.lower()
        return any(n.lower() == lower for n in [*self.classes, *self.props])

    def touching(self, cls: str) -> list[PropertyDef]:
        return [p for p in self.props.values() if p.domain == cls or (p.kind == "object" and p.range == cls)]

    def referenced(self, cls: str) -> bool:
        return bool(self.touching(cls)) or any(c.parent == cls for c in self.classes.values())

    def repoint(self, old: str, new: str) -> None:
        for p in self.props.values():
            p.domain = new if p.domain == old else p.domain
            p.range = new if p.kind == "object" and p.range == old else p.range
        for c in self.classes.values():
            c.parent = new if c.parent == old else c.parent
            c.parent = None if c.parent == c.name else c.parent

    def raw(self) -> dict[str, Any]:
        return {"classes": [{"name": c.name, "description": c.description, "evidence": list(c.evidence),
                             "parent": c.parent} for c in self.classes.values()],
                "properties": [{"name": p.name, "kind": p.kind, "domain": p.domain, "range": p.range,
                                "description": p.description, "evidence": list(p.evidence)}
                               for p in self.props.values()]}


def _merge_evidence(into: ClassDef | PropertyDef, source: ClassDef | PropertyDef) -> None:
    into.evidence = sorted(set(into.evidence) | set(source.evidence))


def _style_only(old: str, new: str, domain: str) -> bool:
    """`new` is `old` with the domain class name added as a prefix or suffix (case-insensitive)."""
    o, n, d = old.lower(), new.lower(), domain.lower()
    return n in (d + o, o + d)


def _passages(n: int) -> str:
    return f"{n} passage" + ("" if n == 1 else "s")


def _drop_property(work: _Work, op: dict[str, Any]) -> str | None:
    dropped = work.props.get(op["name"])
    if dropped is None:
        return f"unknown property {op['name']}"
    if dropped.seed:
        return f"{op['name']} is a seed item"
    if dropped.evidence:
        merge = op.get("merge_into")
        if merge:
            target = work.props.get(merge)
            if target is None or target is dropped:
                return f"unknown property {merge}"
            if target.kind != dropped.kind:
                return f"merge_into {merge} is a {target.kind} property, {dropped.name} is {dropped.kind}"
        else:
            target = next((p for n, p in work.props.items() if n in work.added and p.kind == dropped.kind
                           and p.domain == dropped.domain and p.range == dropped.range), None)
            if target is None:
                return (f"{DROP_HAS_EVIDENCE}: {dropped.name} cites {_passages(len(set(dropped.evidence)))}; "
                        f"add a replacement {dropped.domain} -> {dropped.range} or give merge_into")
        _merge_evidence(target, dropped)
    del work.props[op["name"]]
    return None


def _drop_class(work: _Work, target: ClassDef, op: dict[str, Any]) -> str | None:
    merge = op.get("merge_into")
    if merge:
        into = work.classes.get(merge)
        if into is None or into is target:
            return f"unknown class {merge}"
        if any(p.seed for p in work.touching(target.name)):
            return f"{target.name} is used by a seed property"
        _merge_evidence(into, target)
        del work.classes[target.name]
        work.repoint(target.name, into.name)
        return None
    if target.evidence:
        return (f"{DROP_HAS_EVIDENCE}: {target.name} cites {_passages(len(set(target.evidence)))}; "
                "give merge_into to move them")
    if work.referenced(target.name):
        return f"{target.name} is still referenced"
    del work.classes[target.name]
    return None


def _apply(work: _Work, op: dict[str, Any]) -> str | None:
    """Apply one op in place; return a skip reason instead when it cannot apply as written."""
    kind = op["op"]
    if kind in ("add_object_property", "add_datatype_property"):
        needed = [op["domain"], op["range"]] if kind == "add_object_property" else [op["domain"]]
        missing = [n for n in needed if n not in work.classes]
        if missing:
            return f"unknown class {missing[0]}"
        if work.taken(op["name"]):
            return f"name {op['name']} is already used"
        work.props[op["name"]] = PropertyDef(op["name"], "object" if kind == "add_object_property" else "datatype",
                                             op["domain"], op["range"], op["description"], list(op["evidence"]))
        work.added.add(op["name"])
        return None
    if kind == "rename":
        old, new = op["from"], op["to"]
        item: ClassDef | PropertyDef | None = work.classes.get(old) or work.props.get(old)
        if item is None:
            return f"unknown name {old}"
        if item.seed:
            return f"{old} is a seed item"
        if isinstance(item, PropertyDef) and _style_only(old, new, item.domain):
            return (f"{RENAME_STYLE_ONLY}: {new} only adds the domain {item.domain} to {old}; "
                    "properties are already scoped by their domain")
        if work.taken(new) and new.lower() != old.lower():
            return f"name {new} is already used"
        if old in work.classes:
            cls = work.classes.pop(old)
            cls.name = new
            work.classes[new] = cls
            work.repoint(old, new)
        else:
            prop = work.props.pop(old)
            prop.name = new
            work.props[new] = prop
            if old in work.added:
                work.added.discard(old)
                work.added.add(new)
        return None
    if kind == "drop_property":
        return _drop_property(work, op)
    target = work.classes.get(op["name"])
    if target is None:
        return f"unknown class {op['name']}"
    if target.seed:
        return f"{op['name']} is a seed item"
    if kind == "narrow_class":
        target.description = op["description"]
        return None
    if kind == "drop_class":
        return _drop_class(work, target, op)
    return _split(work, target, op)


def _split(work: _Work, cls: ClassDef, op: dict[str, Any]) -> str | None:
    """Replace `cls` by the `into` classes (each inherits its evidence and parent). Properties listed in
    `reassign` move to the named class; the rest, and subclasses, move to the first `into` class."""
    names = [i["name"] for i in op["into"]]
    touching = {p.name: p for p in work.touching(cls.name)}
    if any(p.seed for p in touching.values()):
        return f"{cls.name} is used by a seed property"
    unknown = sorted(set(op["reassign"]) - set(touching))
    if unknown:
        return f"reassign names {unknown[0]}, which is not a property of {cls.name}"
    clash = [n for n in names if n != cls.name and work.taken(n)]
    if clash:
        return f"name {clash[0]} is already used"
    if len({n.lower() for n in names}) != len(names):
        return "the `into` names repeat"
    del work.classes[cls.name]
    for item in op["into"]:
        work.classes[item["name"]] = ClassDef(item["name"], item["description"], list(cls.evidence), cls.parent)
    for prop in touching.values():
        new = op["reassign"].get(prop.name, names[0])
        prop.domain = new if prop.domain == cls.name else prop.domain
        prop.range = new if prop.kind == "object" and prop.range == cls.name else prop.range
    for c in work.classes.values():
        c.parent = names[0] if c.parent == cls.name else c.parent
    return None


def _apply_all(ontology: Ontology, ops: list[dict[str, Any]], accepted: set[str],
               blocked: dict[int, str]) -> tuple[_Work, list[int], dict[int, str]]:
    """Apply ops in order (indices in `blocked` are skipped with that reason). A drop refused only for lack
    of a replacement is retried once after the other ops. Returns `(work, applied indices, skip reasons)`."""
    work = _Work(ontology)
    applied: list[int] = []
    reasons: dict[int, str] = {}
    deferred: list[int] = []
    for i, op in enumerate(ops):
        if op["finding"] not in accepted:
            reasons[i] = "not accepted"
            continue
        if i in blocked:
            reasons[i] = blocked[i]
            continue
        reason = _apply(work, op)
        if reason is None:
            applied.append(i)
        elif reason.startswith(DROP_HAS_EVIDENCE) and op["op"] == "drop_property":
            deferred.append(i)
            reasons[i] = reason
        else:
            reasons[i] = reason
    for i in deferred:
        reason = _apply(work, ops[i])
        if reason is None:
            applied.append(i)
            del reasons[i]
        else:
            reasons[i] = reason
    return work, applied, reasons


def _mentions(op: dict[str, Any]) -> set[str]:
    names = {op.get(k) for k in ("name", "from", "to", "domain", "range", "merge_into")}
    names |= {i["name"] for i in op.get("into", [])}
    return {n for n in names if isinstance(n, str)}


def _result(ops: list[dict[str, Any]], applied: list[int],
            reasons: dict[int, str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return ([ops[i] for i in sorted(applied)],
            [{"op": ops[i], "reason": reasons[i]} for i in sorted(reasons)])


def apply_ops(ontology: Ontology, ops: list[dict[str, Any]],
              accepted: set[str]) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply the ops whose `finding` is in `accepted`, in order. Returns `(raw, applied, skipped)` where `raw`
    is hygiene input and `skipped` items are `{op, reason}` (not accepted, unknown/seed/taken names,
    `rename_style_only`, `drop_has_evidence`). Does not run hygiene; `plan_revision` adds the
    no-coverage-regression guard."""
    work, applied, reasons = _apply_all(ontology, ops, accepted, {})
    return (work.raw(), *_result(ops, applied, reasons))


def plan_revision(ontology: Ontology, ops: list[dict[str, Any]], accepted: set[str], *, version: int
                  ) -> tuple[Ontology | None, HygieneReport | None, list[dict[str, Any]], list[dict[str, Any]]]:
    """`apply_ops` plus hygiene, re-applied without any op whose result loses evidence (`coverage_regression`)
    until the diff from `ontology` has no coverage regressions. Returns `(revised|None, report|None, applied,
    skipped)`; `revised` is None when no op applies.

    Raises: INTERNAL_ERROR (seed violation).
    """
    seeds = Ontology(version=0, classes=[c for c in ontology.classes if c.seed],
                     properties=[p for p in ontology.properties if p.seed])
    blocked: dict[int, str] = {}
    while True:
        work, applied, reasons = _apply_all(ontology, ops, accepted, blocked)
        if not applied:
            return None, None, *_result(ops, applied, reasons)
        revised, report = hygiene.clean(work.raw(), None, seeds if seeds.classes or seeds.properties else None,
                                        version=version, origin="revise")
        lost = diff_mod.diff(ontology, revised).coverage_regressions
        if not lost:
            return revised, report, *_result(ops, applied, reasons)
        names = {r.name for r in lost}
        culprits = [i for i in applied if _mentions(ops[i]) & names] or [applied[-1]]
        for i in culprits:
            blocked[i] = (f"{COVERAGE_REGRESSION}: applying it would lose the evidence of "
                          + ", ".join(sorted(names)))


def describe(op: dict[str, Any]) -> str:
    if op["op"] == "rename":
        return f"rename {op['from']} -> {op['to']}"
    if op["op"] == "split_class":
        return f"split_class {op['name']} -> {', '.join(i['name'] for i in op['into'])}"
    return f"{op['op']} {op['name']}"


def outcome(applied: list[dict[str, Any]], skipped: list[dict[str, Any]]) -> dict[str, Any]:
    """`{applied, applied_ops, skipped, warnings}` for results and refine round summaries."""
    return {"applied": [describe(op) for op in applied], "applied_ops": applied,
            "skipped": [{"op": describe(s["op"]), "finding": s["op"]["finding"], "reason": s["reason"]}
                        for s in skipped],
            "warnings": [f"skipped {describe(s['op'])}: {s['reason']}" for s in skipped
                         if s["reason"] != "not accepted"]}


def revise_version(paths: StatePaths, journal: Journal, base: int, record: dict[str, Any],
                   accepted: set[str]) -> dict[str, Any]:
    """Apply `record`'s accepted ops to v`base` and write v<N+1> (origin `revise`, unapproved). Caller holds the
    lock. Returns `{version|None, schema_id, parent_version, applied, applied_ops, skipped, warnings, classes,
    properties}`; `version` is None when no op applied (nothing is written).

    Raises: EMPTY_ONTOLOGY, INTERNAL_ERROR (seed violation).
    """
    meta, ontology = state.load_version(paths, base)
    n = state.next_version(paths)
    revised, report, applied, skipped = plan_revision(ontology, record["ops"], accepted, version=n)
    out: dict[str, Any] = {"version": None, "schema_id": None, "parent_version": base,
                           **outcome(applied, skipped),
                           "classes": len(ontology.classes), "properties": len(ontology.properties)}
    if revised is None or report is None:
        return out
    changes = diff_mod.diff(ontology, revised)
    if changes.coverage_regressions:  # pragma: no cover - plan_revision guarantees none
        raise Blocked("INTERNAL_ERROR", "revise would lose evidence of "
                      + ", ".join(r.name for r in changes.coverage_regressions))
    cited = {e for item in [*revised.classes, *revised.properties] for e in item.evidence}
    evidence: list[EvidenceRecord] = [r for r in state.load_evidence(paths, base) if r.evidence_id in cited]
    version = Version(version=n, schema_id=revised.schema_id(), origin="revise", tool_version=state.tool_version(),
                      created_at=state.utc_now(), hygiene=report, parent_version=base, plan_id=record["plan_id"],
                      grz_generation_id=meta.grz_generation_id, prompt_sha256=record["prompt_sha256"],
                      model=meta.model)
    state.write_version(paths, journal, version=version, ontology=revised, evidence=evidence, diff=changes)
    out.update(version=n, schema_id=version.schema_id, classes=len(revised.classes),
               properties=len(revised.properties))
    out["warnings"] += [f"hygiene dropped {d.name} ({d.reason})" for d in report.dropped]
    return out


def run(paths: StatePaths, *, from_critique: str, accept: list[str] | None) -> dict[str, Any]:
    """Apply a critique's accepted ops to the latest version and write v<N+1> (origin `revise`). The new version
    needs its own approval.

    Raises: VERSION_NOT_FOUND, EMPTY_ONTOLOGY, STATE_LOCKED.
    """
    critique_mod.load(paths, from_critique)  # VERSION_NOT_FOUND before the lock creates the state dir
    with StateLock(paths, "revise"):
        record = critique_mod.load(paths, from_critique)
        accepted, warnings = accepted_fingerprints(record, accept)
        base = state.resolve_version(paths, None)
        result = revise_version(paths, Journal(paths), base, record, accepted)
    if base != record["version"]:
        warnings.insert(0, f"critique {from_critique} judged v{record['version']}; applied to the latest v{base}")
    result["warnings"] = warnings + result["warnings"]
    result.pop("applied_ops")
    n = result["version"]
    return {"status": "ok", "critique_id": from_critique, **result,
            "next_step": (f"ontology-build review --version {n}" if n is not None else
                          f"ontology-build review --version {base}")}
