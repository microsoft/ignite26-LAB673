"""Mermaid rendering: the capped `classDiagram` of `show --mermaid` and the exact `flowchart` of
`ontology-consume diagram`."""

from __future__ import annotations

from ontology_core.model import Ontology

MAX_CLASSES = 60


def class_diagram(ontology: Ontology, *, max_classes: int = MAX_CLASSES) -> str:
    """A `classDiagram` with object properties as labeled edges only (no datatype attributes). When capped,
    keeps the classes with the most evidence (ties by name) and appends a `%% showing N of M classes` note."""
    ranked = sorted(ontology.classes, key=lambda c: (-len(c.evidence), c.name))
    kept = sorted(c.name for c in ranked[:max_classes])
    keep = set(kept)
    lines = ["classDiagram"]
    lines.extend(f"  class {name}" for name in kept)
    for c in sorted(ontology.classes, key=lambda c: c.name):
        if c.parent and c.name in keep and c.parent in keep:
            lines.append(f"  {c.parent} <|-- {c.name}")
    edges = sorted({(p.domain, p.range, p.name) for p in ontology.properties
                    if p.kind == "object" and p.domain in keep and p.range in keep})
    lines.extend(f"  {domain} --> {range_} : {name}" for domain, range_, name in edges)
    total = len(ontology.classes)
    if total > len(kept):
        lines.append(f"  %% showing {len(kept)} of {total} classes")
    return "\n".join(lines) + "\n"


NO_RELATIONSHIPS = "No relationships"


def _node(name: str) -> str:
    return f"c_{name}"


def _text(text: str) -> str:
    return text.replace('"', "#quot;").replace("<", "#lt;").replace(">", "#gt;")


def full_diagram(ontology: Ontology, *, with_datatype: bool = False) -> str:
    """An exact, uncapped Mermaid `flowchart` of `ontology` (`ontology-consume diagram`): every class is a node;
    every object property is a `domain --> range` edge, with the properties that share a domain/range pair
    joined into one label by ", " (self-loops included); subclasses are dotted `subClassOf` edges; classes
    that are neither the domain nor the range of an object property sit in a "No relationships" subgraph.
    `with_datatype` lists each class's datatype properties (`name: Range`) inside its node."""
    classes = sorted(c.name for c in ontology.classes)
    objects = [p for p in ontology.properties if p.kind == "object"]
    edges: dict[tuple[str, str], list[str]] = {}
    for p in sorted(objects, key=lambda p: (p.domain, p.range, p.name)):
        names = edges.setdefault((p.domain, p.range), [])
        if p.name not in names:
            names.append(p.name)
    related = {p.domain for p in objects} | {p.range for p in objects}
    members: dict[str, list[str]] = {}
    if with_datatype:
        for p in sorted(ontology.properties, key=lambda p: (p.domain, p.name)):
            if p.kind == "datatype":
                members.setdefault(p.domain, []).append(f"{p.name}: {p.range}")

    def node(name: str, indent: str = "  ") -> str:
        label = "<br/>".join([f"<b>{_text(name)}</b>" if name in members else _text(name)]
                             + [_text(m) for m in members.get(name, [])])
        return f'{indent}{_node(name)}["{label}"]'

    lines = ["flowchart LR"]
    lines.extend(node(name) for name in classes if name in related)
    lonely = [name for name in classes if name not in related]
    if lonely:
        lines.append(f'  subgraph no_relationships["{NO_RELATIONSHIPS}"]')
        lines.extend(node(name, "    ") for name in lonely)
        lines.append("  end")
    for (domain, range_), names in sorted(edges.items()):
        lines.append(f'  {_node(domain)} -->|"{_text(", ".join(names))}"| {_node(range_)}')
    for c in sorted(ontology.classes, key=lambda c: c.name):
        if c.parent:
            lines.append(f'  {_node(c.name)} -.->|"subClassOf"| {_node(c.parent)}')
    return "\n".join(lines) + "\n"
