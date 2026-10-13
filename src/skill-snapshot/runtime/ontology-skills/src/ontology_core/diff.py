"""Version diff."""

from __future__ import annotations

from typing import Any

from ontology_core.errors import Blocked
from ontology_core.model import Change, ClassDef, CoverageRegression, Diff, Ontology, PropertyDef, TypeNames

CHANGED_FIELDS = ("description", "domain", "range", "kind")
_CLASS_FIELDS = ("description", "parent")


def _index(ontology: Ontology | None) -> dict[tuple[str, str], ClassDef | PropertyDef]:
    if ontology is None:
        return {}
    items: dict[tuple[str, str], Any] = {("class", c.name): c for c in ontology.classes}
    items.update({("property", p.name): p for p in ontology.properties})
    return items


def diff(prev: Ontology | None, next_: Ontology) -> Diff:
    """Compare two versions, matching types by (kind, name) where kind is `class` or `property`.

    `prev=None` means everything in `next_` is added and `from_version` is None.
    `changed` covers `CHANGED_FIELDS` (and `parent` for classes); `coverage_regressions` lists `prev`
    types with evidence that are missing from `next_` unless one `next_` type of the same kind cites all of
    that evidence (a rename, merge or split carried it); `seed_violations` lists `prev` seed types
    missing from `next_`. Every list is sorted by (kind, name), classes first.

    Raises:
        Blocked("INTERNAL_ERROR"): `seed_violations` would be non-empty.
    """
    before, after = _index(prev), _index(next_)
    removed = sorted(k for k in before if k not in after)
    added = sorted(k for k in after if k not in before)

    seed_violations = sorted(name for kind, name in removed if before[(kind, name)].seed)
    if seed_violations:
        raise Blocked("INTERNAL_ERROR", "seed types are missing from the new version: " + ", ".join(seed_violations),
                      details={"seed_violations": seed_violations})

    changed: list[Change] = []
    for key in sorted(k for k in after if k in before):
        kind, name = key
        fields = _CLASS_FIELDS if kind == "class" else CHANGED_FIELDS
        for field_name in fields:
            old, new = getattr(before[key], field_name), getattr(after[key], field_name)
            if old != new:
                changed.append(Change(kind=kind, name=name, field=field_name, before=old, after=new))

    successors: dict[str, list[set[str]]] = {"class": [], "property": []}
    for (kind, _), item in after.items():
        successors[kind].append(set(item.evidence))

    def carried(kind: str, evidence: list[str]) -> bool:
        return any(set(evidence) <= e for e in successors[kind])

    regressions = [
        CoverageRegression(name=name, kind=kind, had_evidence=len(set(before[(kind, name)].evidence)))
        for kind, name in removed
        if before[(kind, name)].evidence and not carried(kind, before[(kind, name)].evidence)
    ]
    return Diff(
        to_version=next_.version,
        from_version=prev.version if prev is not None else None,
        added=TypeNames(classes=[n for k, n in added if k == "class"],
                        properties=[n for k, n in added if k == "property"]),
        removed=TypeNames(classes=[n for k, n in removed if k == "class"],
                          properties=[n for k, n in removed if k == "property"]),
        changed=changed,
        coverage_regressions=regressions,
        seed_violations=[],
    )
