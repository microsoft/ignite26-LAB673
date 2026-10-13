"""Deterministic whole-ontology lints (stage A of `ontology-build critique`). Pure: no I/O, no model call.

Each finding has a stable fingerprint `kind:target`, so a later round can tell whether an issue that an
earlier round's changes targeted came back.

| Kind | Fires when | Severity |
|---|---|---|
| `orphan_class` | no object property has the class as domain or range | high |
| `datatype_only_class` | the class has datatype properties but no object property touches it | medium |
| `broad_class` | one sentence of the description lists >= `BROAD_ITEMS` top-level alternatives (see below) | medium |
| `overlapping_properties` | >= `OVERLAP_MIN` object properties share one domain and range | low |
| `hub_concentration` | one class is the domain of > `HUB_SHARE` of the object properties (>= `HUB_MIN_PROPS`) | low |

`datatype_only_class` replaces `orphan_class` for the same class, so each class gets at most one of them.

`broad_class` rule: a list of examples of one kind is not broadness. Text introduced by an example marker
(`such as`, `including`, `like`, `e.g.`, `i.e.`, `for example`, `for instance`, `especially`, `notably`,
`namely`) up to the end of its clause is ignored; the rest of each sentence is split on commas, `;`, `/`,
`or` and `and`, and the class fires only when one sentence still has >= `BROAD_ITEMS` parts. So "An
individual human actor such as a founder, executive, ..." counts 1, while "A security weakness,
vulnerability, malware threat, ..., dispute, investigation, legal controversy, ... or business challenge"
fires. Subtler heterogeneity (an Organization that also covers sports clubs) is left to the judge, which
sees the evidence.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from typing import Literal

from ontology_core.model import Ontology

Severity = Literal["high", "medium", "low"]
SEVERITIES: tuple[Severity, ...] = ("high", "medium", "low")
KINDS = ("orphan_class", "datatype_only_class", "broad_class", "overlapping_properties", "hub_concentration")

BROAD_ITEMS = 10
"""Top-level alternatives (examples excluded) in one sentence that make a class a catch-all."""
OVERLAP_MIN = 3
"""Object properties with the same domain and range that suggest overlapping meanings."""
HUB_SHARE = 0.40
"""Share of all object properties one domain may own before it is a hub."""
HUB_MIN_PROPS = 5
"""Below this many object properties, hub concentration is not meaningful."""

_SPLIT = re.compile(r",|;|/|\bor\b|\band\b", re.IGNORECASE)
_EXAMPLES = re.compile(r"\b(?:such as|including|like|e\.g\.|i\.e\.|for example|for instance|especially|notably|namely)"
                       r"(?![\w])[^;:!?()]*?(?=[.!?](?:\s|$)|[;:()]|$)", re.IGNORECASE)


@dataclass(frozen=True)
class Finding:
    fingerprint: str
    kind: str
    target: str
    severity: Severity
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _finding(kind: str, target: str, severity: Severity, message: str) -> Finding:
    return Finding(f"{kind}:{target}", kind, target, severity, message)


def enumerated_items(description: str) -> int:
    """How many top-level alternatives the longest sentence of `description` lists (1 when it lists nothing).
    Example clauses (`such as ...`, `including ...`, `e.g. ...`) are removed first."""
    best = 1
    for sentence in re.split(r"(?<=[.!?])\s+|\(|\)", _EXAMPLES.sub("", description)):
        parts = [p for p in _SPLIT.split(sentence) if p.strip()]
        best = max(best, len(parts))
    return best


def lint(ontology: Ontology) -> list[Finding]:
    """All findings, sorted by severity then fingerprint."""
    objects = [p for p in ontology.properties if p.kind == "object"]
    datatypes = [p for p in ontology.properties if p.kind == "datatype"]
    touched = {p.domain for p in objects} | {p.range for p in objects}
    with_datatype = {p.domain for p in datatypes}
    found: list[Finding] = []
    for cls in ontology.classes:
        if cls.name not in touched:
            if cls.name in with_datatype:
                found.append(_finding("datatype_only_class", cls.name, "medium",
                                      f"{cls.name} has only datatype properties; nothing links it to other classes"))
            else:
                found.append(_finding("orphan_class", cls.name, "high",
                                      f"{cls.name} is not the domain or range of any object property"))
        items = enumerated_items(cls.description)
        if items >= BROAD_ITEMS:
            found.append(_finding("broad_class", cls.name, "medium",
                                  f"{cls.name}'s description lists {items} alternatives; it may be a catch-all"))
    pairs: dict[tuple[str, str], list[str]] = defaultdict(list)
    for p in objects:
        pairs[(p.domain, p.range)].append(p.name)
    for (domain, range_), group in sorted(pairs.items()):
        if len(group) >= OVERLAP_MIN:
            found.append(_finding("overlapping_properties", f"{domain}->{range_}", "low",
                                  f"{len(group)} properties link {domain} to {range_}: {', '.join(sorted(group))}"))
    if len(objects) >= HUB_MIN_PROPS:
        for domain, n in sorted(Counter(p.domain for p in objects).items()):
            if n / len(objects) > HUB_SHARE:
                found.append(_finding("hub_concentration", domain, "low",
                                      f"{domain} is the domain of {n} of {len(objects)} object properties"))
    return sorted(found, key=lambda f: (SEVERITIES.index(f.severity), f.fingerprint))


def counts(findings: list[Finding]) -> dict[str, int]:
    """`{high, medium, low}` finding counts."""
    tally = Counter(f.severity for f in findings)
    return {s: tally.get(s, 0) for s in SEVERITIES}
