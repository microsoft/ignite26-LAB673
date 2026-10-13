"""Deterministic ontology hygiene.

Input is the raw model/import JSON shape:
`{"classes":[{name, description, evidence?, parent?}], "properties":[{name, kind, domain, range, description, evidence?}]}`
(extra keys ignored; missing lists treated as empty). Seed types come from `seed` (an `Ontology` whose
items all have `seed=True`) and are merged in first; they are never dropped or renamed.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal

from ontology_core import names
from ontology_core.errors import Blocked
from ontology_core.model import ClassDef, Drop, HygieneReport, Ontology, PropertyDef

MAX_DESCRIPTION = 400
DATATYPE_ALIASES: dict[str, str] = {
    "string": "String", "text": "String", "str": "String",
    "number": "Double", "float": "Double", "double": "Double", "integer": "Double", "int": "Double",
    "decimal": "Double",
    "bool": "Boolean", "boolean": "Boolean",
    "date": "DateTime", "datetime": "DateTime", "timestamp": "DateTime", "time": "DateTime",
}
DROP_REASONS = (
    "invalid_name", "no_description", "no_valid_evidence", "dangling_domain", "dangling_range",
    "unsupported_datatype",
)
Origin = Literal["propose", "import", "revise"]

_EVIDENCE = re.compile(r"^E[0-9a-f]{10,12}$")
_XSD_PREFIXES = ("http://www.w3.org/2001/xmlschema#", "xsd:")


def normalize_text(text: str) -> str:
    """Drop control characters (whitespace aside) and XML-illegal code points; collapse whitespace; trim.

    The same normalization `owl_write.escape` applies, so a cleaned description round-trips through OWL.
    """
    kept = "".join(ch for ch in text if ch.isspace() or not _illegal(ch))
    return " ".join(kept.split())


def _illegal(ch: str) -> bool:
    return unicodedata.category(ch) in ("Cc", "Cs") or ch in ("\ufffe", "\uffff")


def map_datatype(value: str) -> str | None:
    """Case-insensitive `DATATYPE_ALIASES` lookup; canonical names map to themselves; else None.

    An `xsd:` prefix or the full XML Schema namespace is ignored, so `xsd:dateTime` maps to `DateTime`.
    """
    if not isinstance(value, str):
        return None
    key = value.strip().lower()
    for prefix in _XSD_PREFIXES:
        key = key.removeprefix(prefix)
    return DATATYPE_ALIASES.get(key)


def truncate_description(text: str, limit: int = MAX_DESCRIPTION) -> tuple[str, bool]:
    """Whitespace-collapse; cut at the last word boundary within `limit`. Returns (text, truncated)."""
    text = normalize_text(text)
    if len(text) <= limit:
        return text, False
    cut = text[:limit + 1].rfind(" ")
    return (text[:cut] if cut > 0 else text[:limit]).rstrip(), True


@dataclass
class _Class:
    name: str
    description: str
    evidence: list[str]
    parent: str | None
    seed: bool
    order: int


@dataclass
class _Prop:
    name: str
    kind: str
    domain: str
    range: str
    description: str
    evidence: list[str]
    seed: bool
    order: int


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _items(raw: Any, key: str) -> list[dict[str, Any]]:
    values = raw.get(key) if isinstance(raw, dict) else None
    if not isinstance(values, list):
        return []
    return [v if isinstance(v, dict) else {} for v in values]


def _evidence(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [e for e in value if isinstance(e, str) and _EVIDENCE.match(e)]


def _kind(value: Any, range_: str) -> str:
    text = _text(value).strip().lower()
    if text.startswith(("obj", "rel")):
        return "object"
    if text.startswith(("data", "attr", "lit")):
        return "datatype"
    return "datatype" if map_datatype(range_) else "object"


def _union(*lists: list[str]) -> list[str]:
    return sorted({e for values in lists for e in values})


def _pascal_tail(name: str) -> str:
    return name[:1].upper() + name[1:]


class _Cleaner:
    def __init__(self, evidence_ids: set[str] | None, seed: Ontology | None) -> None:
        self.evidence_ids = evidence_ids
        self.report = HygieneReport()
        self.seed_classes = [
            _Class(c.name, c.description, list(c.evidence), c.parent, True, -1) for c in (seed.classes if seed else [])]
        self.seed_props = [
            _Prop(p.name, p.kind, p.domain, p.range, p.description, list(p.evidence), True, -1)
            for p in (seed.properties if seed else [])]
        self.seed_class_by_lower = {c.name.lower(): c for c in self.seed_classes}
        self.seed_prop_by_lower = {p.name.lower(): p for p in self.seed_props}

    def drop(self, name: str, reason: str) -> None:
        self.report.dropped.append(Drop(name=name, reason=reason))

    def _name(self, raw_name: str, normalize: Any) -> str:
        name = normalize(raw_name)
        if name and name != raw_name:
            self.report.renamed.append({"from": raw_name, "to": name})
        return name

    def _filter_evidence(self, evidence: list[str]) -> list[str]:
        if self.evidence_ids is None:
            return evidence
        return [e for e in evidence if e in self.evidence_ids]

    def _description(self, name: str, item: dict[str, Any]) -> str | None:
        description, truncated = truncate_description(_text(item.get("description")))
        if not description:
            self.drop(name, "no_description")
            return None
        if truncated:
            self.report.warnings.append(f"truncated_description:{name}")
        return description

    # ------------------------------------------------------------------ classes (steps 1-4, 8)

    def classes(self, items: list[dict[str, Any]]) -> list[_Class]:
        candidates: list[_Class] = []
        for order, item in enumerate(items):
            raw_name = _text(item.get("name"))
            name = self._name(raw_name, names.normalize_class)
            if not names.is_valid(name):
                self.drop(raw_name or name, "invalid_name")
                continue
            evidence = self._filter_evidence(_evidence(item.get("evidence")))
            seed = self.seed_class_by_lower.get(name.lower())
            if seed is not None:
                seed.evidence = _union(seed.evidence, evidence)
                continue
            description = self._description(name, item)
            if description is None:
                continue
            if self.evidence_ids is not None and not evidence:
                self.drop(name, "no_valid_evidence")
                continue
            parent = names.normalize_class(_text(item.get("parent"))) or None
            candidates.append(_Class(name, description, evidence, parent, False, order))

        merged = self._merge_classes(candidates)
        survivors: list[_Class] = []
        for cls in merged:
            if cls.name.lower() in self.seed_prop_by_lower:
                self.drop(cls.name, "invalid_name")
                continue
            survivors.append(cls)
        everything = self.seed_classes + survivors
        lookup = {c.name.lower(): c.name for c in everything}
        for cls in survivors:
            if cls.parent is None:
                continue
            parent = lookup.get(cls.parent.lower())
            if parent is None or parent == cls.name:
                self.report.warnings.append(f"dangling_parent:{cls.name}")
            cls.parent = parent if parent != cls.name else None
        return everything

    def _merge_classes(self, candidates: list[_Class]) -> list[_Class]:
        groups: dict[str, list[_Class]] = {}
        for cls in candidates:
            groups.setdefault(cls.name.lower(), []).append(cls)
        merged: list[_Class] = []
        for group in groups.values():
            survivor = min(group, key=lambda c: (-len(set(c.evidence)), c.name, c.order))
            survivor.evidence = _union(*(c.evidence for c in group))
            if survivor.parent is None:
                survivor.parent = next((c.parent for c in group if c.parent), None)
            for other in sorted({c.name for c in group} - {survivor.name}):
                self.report.warnings.append(f"merged:{other}:{survivor.name}")
            merged.append(survivor)
        return merged

    # ------------------------------------------------------------------ properties (steps 1-3, 5-8)

    def properties(self, items: list[dict[str, Any]], classes: list[_Class]) -> list[_Prop]:
        lookup = {c.name.lower(): c.name for c in classes}
        candidates: list[_Prop] = []
        for order, item in enumerate(items):
            raw_name = _text(item.get("name"))
            name = self._name(raw_name, names.normalize_property)
            if not names.is_valid(name):
                self.drop(raw_name or name, "invalid_name")
                continue
            evidence = self._filter_evidence(_evidence(item.get("evidence")))
            seed = self.seed_prop_by_lower.get(name.lower())
            if seed is not None:
                seed.evidence = _union(seed.evidence, evidence)
                continue
            description = self._description(name, item)
            if description is None:
                continue
            if self.evidence_ids is not None and not evidence:
                self.drop(name, "no_valid_evidence")
                continue
            raw_range = _text(item.get("range"))
            kind = _kind(item.get("kind"), raw_range)
            domain = lookup.get(names.normalize_class(_text(item.get("domain"))).lower())
            if domain is None:
                self.drop(name, "dangling_domain")
                continue
            if kind == "object":
                range_ = lookup.get(names.normalize_class(raw_range).lower())
                if range_ is None:
                    self.drop(name, "dangling_range")
                    continue
            else:
                range_ = map_datatype(raw_range)
                if range_ is None:
                    self.drop(name, "unsupported_datatype")
                    continue
            candidates.append(_Prop(name, kind, domain, range_, description, evidence, False, order))
        props = self._qualify_overloads(candidates, classes)
        self._prefix_class_collisions(props, classes)
        return self.seed_props + props

    def _qualify_overloads(self, candidates: list[_Prop], classes: list[_Class]) -> list[_Prop]:
        groups: dict[str, dict[tuple[str, str, str], list[_Prop]]] = {}
        for prop in candidates:
            groups.setdefault(prop.name.lower(), {}).setdefault((prop.kind, prop.domain, prop.range), []).append(prop)
        pairs_by_group: list[list[_Prop]] = []
        for name_lower in sorted(groups):
            pairs: list[_Prop] = []
            for same in groups[name_lower].values():
                survivor = min(same, key=lambda p: (-len(set(p.evidence)), p.name, p.order))
                survivor.evidence = _union(*(p.evidence for p in same))
                pairs.append(survivor)
            pairs.sort(key=lambda p: (-len(p.evidence), p.domain, p.range, p.kind, p.name))
            pairs_by_group.append(pairs)
        taken = {p.name.lower() for p in self.seed_props} | {pairs[0].name.lower() for pairs in pairs_by_group}
        result: list[_Prop] = []
        for pairs in pairs_by_group:
            result.append(pairs[0])
            for prop in pairs[1:]:
                new = _unique(names.to_lower_camel(prop.domain) + _pascal_tail(prop.name), taken)
                self.report.qualified.append({"from": prop.name, "to": new})
                prop.name = new
                result.append(prop)
        return result

    def _prefix_class_collisions(self, props: list[_Prop], classes: list[_Class]) -> None:
        class_names = {c.name.lower() for c in classes}
        taken = class_names | {p.name.lower() for p in self.seed_props + props}
        for prop in sorted(props, key=lambda p: (p.name, p.domain, p.range)):
            if prop.name.lower() not in class_names:
                continue
            taken.discard(prop.name.lower())
            new = _unique("has" + _pascal_tail(prop.name), taken)
            self.report.renamed.append({"from": prop.name, "to": new})
            prop.name = new


def _unique(candidate: str, taken: set[str]) -> str:
    name, n = candidate, 1
    while name.lower() in taken:
        n += 1
        name = f"{candidate}{n}"
    taken.add(name.lower())
    return name


def clean(raw: dict[str, Any], evidence_ids: set[str] | None, seed: Ontology | None, *, version: int,
          origin: Origin) -> tuple[Ontology, HygieneReport]:
    """Run the hygiene steps and return the canonical `Ontology` (version `version`) and its report.

    - `evidence_ids`: IDs in this run's `sample.json`; `None` (import/revise) skips step 3 and keeps
      evidence as given (IDs that do not look like evidence IDs are always discarded).
    - Report: `dropped[{name, reason}]` with reason in `DROP_REASONS`, `renamed[{from,to}]` (step 1 and 7),
      `qualified[{from,to}]` (step 6), `warnings` (`truncated_description:<name>`,
      `merged:<from>:<to>` for step 4, `dangling_parent:<name>` when a parent is not a surviving class).

    Raises:
        Blocked("MODEL_OUTPUT_INVALID"): no classes survive and `origin == "propose"`.
        Blocked("EMPTY_ONTOLOGY"): no classes survive and origin is `import` or `revise`.
    """
    cleaner = _Cleaner(evidence_ids, seed)
    classes = cleaner.classes(_items(raw, "classes"))
    if not classes:
        dropped = len(cleaner.report.dropped)
        details = {"dropped": [{"name": d.name, "reason": d.reason} for d in cleaner.report.dropped]}
        if origin == "propose":
            raise Blocked("MODEL_OUTPUT_INVALID", f"no valid classes survived hygiene ({dropped} dropped)",
                          details=details)
        raise Blocked("EMPTY_ONTOLOGY", f"no valid classes survived hygiene ({dropped} dropped)", details=details)
    props = cleaner.properties(_items(raw, "properties"), classes)
    ontology = Ontology(
        version=version,
        classes=[ClassDef(c.name, c.description, sorted(set(c.evidence)), c.parent, c.seed) for c in classes],
        properties=[PropertyDef(p.name, p.kind, p.domain, p.range, p.description,  # type: ignore[arg-type]
                                sorted(set(p.evidence)), p.seed) for p in props],
    ).canonical()
    return ontology, cleaner.report
