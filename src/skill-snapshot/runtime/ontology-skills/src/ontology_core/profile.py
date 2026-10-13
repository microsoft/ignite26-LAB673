"""flat-owl profile validator.

This is an independent re-implementation of the rules a simple ElementTree consumer relies on. It reads the
XML directly and only uses `owl_read`/`owl_write` for the final determinism check.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from ontology_core import names
from ontology_core.errors import Blocked

MAX_REPORTED = 5

_RDF = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"
_RDFS = "{http://www.w3.org/2000/01/rdf-schema#}"
_OWL = "{http://www.w3.org/2002/07/owl#}"
_XSD = "http://www.w3.org/2001/XMLSchema#"
_DATATYPES = {_XSD + t for t in ("string", "double", "boolean", "dateTime")}
_ENTITIES = {_OWL + "Class": "class", _OWL + "ObjectProperty": "object", _OWL + "DatatypeProperty": "datatype"}
_ALLOWED_CHILDREN = {
    "class": {_RDFS + "label", _RDFS + "comment", _RDFS + "subClassOf"},
    "object": {_RDFS + "label", _RDFS + "comment", _RDFS + "domain", _RDFS + "range"},
    "datatype": {_RDFS + "label", _RDFS + "comment", _RDFS + "domain", _RDFS + "range"},
}
_DECL_SCAN = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)


@dataclass(frozen=True)
class Violation:
    rule: str
    """Short rule id, e.g. `not_well_formed`, `imports`, `doctype`, `ontology_count`, `invalid_name`,
    `duplicate_name`, `domain_count`, `range_count`, `dangling_domain`, `dangling_range`,
    `datatype_range`, `dangling_parent`, `unsupported_element`, `label_order`, `not_canonical`."""
    subject: str
    """The offending local name or element, or `""` for document-level rules."""
    message: str

    def __str__(self) -> str:
        return f"{self.rule}: " + " ".join(part for part in (self.subject, self.message) if part)


def _local(iri: str) -> str:
    if "#" in iri:
        return iri.rsplit("#", 1)[1]
    return iri.rstrip("/").rsplit("/", 1)[-1]


def _short(tag: str) -> str:
    for ns, prefix in ((_RDF, "rdf:"), (_RDFS, "rdfs:"), (_OWL, "owl:")):
        if tag.startswith(ns):
            return prefix + tag[len(ns):]
    return tag


def validate(owl_bytes: bytes) -> list[Violation]:
    """All profile violations in document order (empty list means valid). Never raises for bad input."""
    try:
        return _validate(owl_bytes)
    except Exception as exc:  # the validator must report, never crash
        return [Violation("not_well_formed", "", f"cannot be validated: {type(exc).__name__}: {exc}")]


def _validate(data: bytes) -> list[Violation]:
    if not isinstance(data, (bytes, bytearray)):
        return [Violation("not_well_formed", "", "input is not bytes")]
    data = bytes(data)
    if _DECL_SCAN.search(data):
        return [Violation("doctype", "", "DOCTYPE and ENTITY declarations are not allowed")]
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        return [Violation("not_well_formed", "", f"is not well-formed XML ({exc})")]
    if root.tag != _RDF + "RDF":
        return [Violation("not_well_formed", "", f"root element is {_short(root.tag)}, expected rdf:RDF")]

    out: list[Violation] = []
    ontologies = [el for el in root if el.tag == _OWL + "Ontology"]
    if len(ontologies) != 1:
        out.append(Violation("ontology_count", "", f"has {len(ontologies)} owl:Ontology elements, expected 1"))
    if any(el.tag == _OWL + "imports" for el in root.iter()):
        out.append(Violation("imports", "", "owl:imports is not allowed"))

    entities: list[tuple[str, str, ET.Element]] = []
    for el in root:
        if el.tag == _OWL + "Ontology":
            continue
        kind = _ENTITIES.get(el.tag)
        about = el.get(_RDF + "about")
        if kind is None:
            out.append(Violation("unsupported_element", _short(el.tag), "is not allowed at the top level"))
        elif not about:
            out.append(Violation("invalid_name", _short(el.tag), "has no rdf:about"))
        else:
            entities.append((kind, _local(about), el))

    classes = {name for kind, name, _ in entities if kind == "class"}
    seen: dict[str, str] = {}
    for kind, name, el in entities:
        if not names.is_valid(name):
            out.append(Violation("invalid_name", name, "is not a valid local name"))
        folded = name.lower()
        if folded in seen:
            out.append(Violation("duplicate_name", name, f"collides with {seen[folded]} (case-insensitive)"))
        else:
            seen[folded] = name
        out.extend(_check_entity(kind, name, el, classes))

    if not out:
        out.extend(_check_canonical(data, ontologies[0]))
    return out


def _check_entity(kind: str, name: str, el: ET.Element, classes: set[str]) -> list[Violation]:
    out: list[Violation] = []
    children = list(el)
    for child in children:
        if child.tag not in _ALLOWED_CHILDREN[kind]:
            out.append(Violation("unsupported_element", name, f"contains {_short(child.tag)}"))
    if not children or children[0].tag != _RDFS + "label" or children[-1].tag != _RDFS + "comment" \
            or sum(c.tag == _RDFS + "label" for c in children) != 1 \
            or sum(c.tag == _RDFS + "comment" for c in children) != 1:
        out.append(Violation("label_order", name, "must have one rdfs:label first and one rdfs:comment last"))
    if kind == "class":
        for parent in (c for c in children if c.tag == _RDFS + "subClassOf"):
            target = _local(parent.get(_RDF + "resource") or "")
            if target not in classes:
                out.append(Violation("dangling_parent", name, f"parent {target or '(none)'} is not a declared class"))
        return out

    domains = [c.get(_RDF + "resource") or "" for c in children if c.tag == _RDFS + "domain"]
    ranges = [c.get(_RDF + "resource") or "" for c in children if c.tag == _RDFS + "range"]
    if len(domains) != 1:
        out.append(Violation("domain_count", name, f"has {len(domains)} rdfs:domain, expected 1"))
    if len(ranges) != 1:
        out.append(Violation("range_count", name, f"has {len(ranges)} rdfs:range, expected 1"))
    for domain in domains:
        if _local(domain) not in classes or domain.startswith(_XSD):
            out.append(Violation("dangling_domain", name, f"domain {domain or '(none)'} is not a declared class"))
    for range_ in ranges:
        if kind == "object" and (_local(range_) not in classes or range_.startswith(_XSD)):
            out.append(Violation("dangling_range", name, f"range {range_ or '(none)'} is not a declared class"))
        elif kind == "datatype" and range_ not in _DATATYPES:
            out.append(Violation("datatype_range", name, f"range {range_ or '(none)'} is not a supported xsd type"))
    return out


def _check_canonical(data: bytes, ontology: ET.Element) -> list[Violation]:
    from ontology_core import owl_read, owl_write  # noqa: PLC0415 - avoid import cycles at module load

    about = ontology.get(_RDF + "about") or ""
    version = ontology.find(_OWL + "versionInfo")
    base = about + "#"
    try:
        again = owl_write.write(owl_read.read(data), base_iri=base,
                                version_info=version.text or "" if version is not None else "")
    except Exception as exc:  # any failure to reproduce the bytes is a determinism failure
        return [Violation("not_canonical", "", f"cannot be re-serialized ({type(exc).__name__}: {exc})")]
    if again != data:
        return [Violation("not_canonical", "", "differs from the canonical serialization of its own content")]
    return []


def require_valid(owl_bytes: bytes, *, file: str = "<output>") -> None:
    """Raises:
        Blocked("PROFILE_VIOLATION", file=file): with the first `MAX_REPORTED` violations in `error` and
        all of them (as strings) in `details["violations"]`.
    """
    violations = validate(owl_bytes)
    if not violations:
        return
    shown = "; ".join(str(v) for v in violations[:MAX_REPORTED])
    more = len(violations) - MAX_REPORTED
    if more > 0:
        shown += f"; and {more} more"
    raise Blocked("PROFILE_VIOLATION", shown, details={"violations": [str(v) for v in violations]}, file=file)
