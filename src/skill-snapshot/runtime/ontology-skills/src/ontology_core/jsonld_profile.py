"""Validator for the deterministic inline JSON-LD profile written by `jsonld_write`."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from ontology_core import hashing, jsonld_write, owl_write
from ontology_core.errors import Blocked
from ontology_core.hygiene import normalize_text

MAX_CHARS = 65_536
MAX_DEPTH = 32
MAX_GRAPH_OBJECTS = 128
MAX_TRIPLES = 512

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_XSD = jsonld_write.XSD_NS
_CONTEXT = {
    "owl": jsonld_write.OWL_NS,
    "rdfs": jsonld_write.RDFS_NS,
    "xsd": _XSD,
}
_XSD_TYPES = frozenset(_XSD + value for value in ("string", "double", "decimal", "integer",
                                                    "boolean", "date", "dateTime"))


@dataclass(frozen=True)
class Violation:
    rule: str
    subject: str
    message: str

    def __str__(self) -> str:
        return f"{self.rule}: " + " ".join(part for part in (self.subject, self.message) if part)


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON member {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant {value}")


def _depth(value: Any) -> int:
    maximum = 0
    pending = [(value, 0)]
    while pending:
        item, parent_depth = pending.pop()
        if isinstance(item, (dict, list)):
            depth = parent_depth + 1
            maximum = max(maximum, depth)
            children = item.values() if isinstance(item, dict) else item
            pending.extend((child, depth) for child in children)
    return maximum


def _violation(rule: str, subject: str, message: str) -> Violation:
    return Violation(rule, subject, message)


def validate(data: bytes) -> list[Violation]:
    """Return all violations for the inline JSON-LD export profile."""
    if not isinstance(data, (bytes, bytearray)):
        return [_violation("invalid_json", "", "input is not bytes")]
    raw = bytes(data)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return [_violation("invalid_json", "", f"input is not UTF-8 ({exc})")]
    char_count = len(text.encode("utf-16-le")) // 2
    if char_count > MAX_CHARS:
        return [_violation("character_limit", "", f"has {char_count} UTF-16 code units; maximum is {MAX_CHARS}")]
    try:
        document = json.loads(text, object_pairs_hook=_object_without_duplicates, parse_constant=_reject_constant)
    except (json.JSONDecodeError, ValueError, RecursionError) as exc:
        return [_violation("invalid_json", "", str(exc))]
    if _depth(document) > MAX_DEPTH:
        return [_violation("depth_limit", "", f"exceeds JSON depth {MAX_DEPTH}")]
    return _validate_document(document, raw)


def _validate_document(document: Any, raw: bytes) -> list[Violation]:
    if not isinstance(document, dict) or set(document) != {"@context", "@graph"}:
        return [_violation("document_shape", "", "root must contain only @context and @graph")]
    context = document["@context"]
    if not isinstance(context, dict) or context != _CONTEXT:
        return [_violation("context", "", "must be the fixed embedded owl, rdfs and xsd prefix map")]
    graph = document["@graph"]
    if not isinstance(graph, list):
        return [_violation("graph_shape", "", "@graph must be an array")]
    if not 1 <= len(graph) <= MAX_GRAPH_OBJECTS:
        return [_violation("graph_object_limit", "", f"has {len(graph)} objects; allowed range is 1..{MAX_GRAPH_OBJECTS}")]

    out: list[Violation] = []
    headers = [node for node in graph if isinstance(node, dict) and node.get("@type") == "owl:Ontology"]
    if len(headers) != 1:
        out.append(_violation("ontology_header_count", "", f"has {len(headers)} ontology headers; expected one"))
        return out
    header = headers[0]
    if graph[0] is not header:
        out.append(_violation("graph_order", "", "ontology header must be first"))
    if set(header) != {"@id", "@type", "owl:versionInfo"}:
        out.append(_violation("ontology_header_shape", "", "header must contain only @id, @type and owl:versionInfo"))
    base = header.get("@id")
    if not isinstance(base, str):
        out.append(_violation("ontology_iri", "", "header @id must be an IRI string"))
        return out
    try:
        owl_write.validate_base_iri(base)
        base.encode("utf-8")
    except Blocked as exc:
        out.append(_violation("ontology_iri", "", str(exc)))
        return out
    except UnicodeEncodeError:
        out.append(_violation("ontology_iri", "", "header @id must be valid UTF-8"))
        return out
    version_info = header.get("owl:versionInfo")
    if not isinstance(version_info, str):
        out.append(_violation("ontology_version", "", "owl:versionInfo must be a string"))
    elif normalize_text(version_info) != version_info:
        out.append(_violation("ontology_version", "", "owl:versionInfo must be whitespace-normalized"))

    class_ids: set[str] = set()
    class_names: set[str] = set()
    edge_names: set[str] = set()
    subjects: set[str] = set()
    declarations: list[tuple[int, str, str, dict[str, Any]]] = []
    for index, node in enumerate(graph[1:], start=1):
        if not isinstance(node, dict):
            out.append(_violation("declaration_shape", str(index), "graph entries must be objects"))
            continue
        kind = node.get("@type")
        if kind not in ("owl:Class", "owl:ObjectProperty", "owl:DatatypeProperty"):
            out.append(_violation("declaration_type", str(node.get("@id", index)),
                                  "must be owl:Class, owl:ObjectProperty or owl:DatatypeProperty"))
            continue
        identifier = node.get("@id")
        if not isinstance(identifier, str) or not identifier.startswith(base):
            out.append(_violation("declaration_iri", str(identifier or index), "must be an IRI under the ontology base"))
            continue
        if identifier in subjects:
            out.append(_violation("duplicate_subject", identifier, "declaration subject is repeated"))
        subjects.add(identifier)
        name = identifier[len(base):]
        if not _IDENTIFIER.fullmatch(name):
            out.append(_violation("invalid_name", name, "does not match the ASCII identifier profile"))
        if node.get("rdfs:label") != name or not isinstance(node.get("rdfs:label"), str):
            out.append(_violation("label", name, "rdfs:label must be the identifier string"))
        for field in ("rdfs:label", "rdfs:comment"):
            value = node.get(field)
            if not isinstance(value, str):
                out.append(_violation("annotation", name, f"{field} must be one plain string"))
            elif normalize_text(value) != value:
                out.append(_violation("annotation", name, f"{field} must be whitespace-normalized"))
        if kind == "owl:Class":
            expected = {"@id", "@type", "rdfs:label", "rdfs:comment"}
            if set(node) != expected:
                out.append(_violation("class_shape", name, "class contains unsupported or missing fields"))
            if identifier in class_ids:
                out.append(_violation("duplicate_class", name, "class IRI is repeated"))
            class_ids.add(identifier)
            folded = name.lower()
            if folded in class_names:
                out.append(_violation("duplicate_class", name, "class identifier collides case-insensitively"))
            class_names.add(folded)
            declarations.append((0, name, identifier, node))
        else:
            expected = {"@id", "@type", "rdfs:label", "rdfs:comment", "rdfs:domain", "rdfs:range"}
            if set(node) != expected:
                out.append(_violation("property_shape", name, "property contains unsupported or missing fields"))
            folded = name.lower()
            if folded in edge_names:
                out.append(_violation("duplicate_property", name, "property identifier collides case-insensitively"))
            edge_names.add(folded)
            declarations.append((1 if kind == "owl:ObjectProperty" else 2, name, identifier, node))

    classes = [node for node in graph if isinstance(node, dict) and node.get("@type") == "owl:Class"]
    properties = [node for node in graph if isinstance(node, dict)
                  and node.get("@type") in ("owl:ObjectProperty", "owl:DatatypeProperty")]
    if not classes:
        out.append(_violation("class_required", "", "at least one named class is required"))
    if not properties:
        out.append(_violation("property_required", "", "at least one named property is required"))
    declared_class_iris = {node.get("@id") for node in classes if isinstance(node.get("@id"), str)}
    for node in properties:
        name = str(node.get("rdfs:label", node.get("@id", "")))
        domain = node.get("rdfs:domain")
        range_ = node.get("rdfs:range")
        if (not isinstance(domain, dict) or set(domain) != {"@id"}
                or not isinstance(domain.get("@id"), str) or domain["@id"] not in declared_class_iris):
            out.append(_violation("property_domain", name, "domain must reference one declared class IRI"))
        if not isinstance(range_, dict) or set(range_) != {"@id"}:
            out.append(_violation("property_range", name, "range must be one @id object"))
        elif node.get("@type") == "owl:ObjectProperty":
            if not isinstance(range_["@id"], str) or range_["@id"] not in declared_class_iris:
                out.append(_violation("property_range", name, "object range must reference one declared class IRI"))
        elif not isinstance(range_["@id"], str) or range_["@id"] not in _XSD_TYPES:
            out.append(_violation("datatype_range", name, "range is not one of the supported XML Schema datatypes"))

    if declarations:
        expected_order = sorted(declarations, key=lambda item: (item[0], item[1]))
        if [(item[0], item[1]) for item in declarations] != [(item[0], item[1]) for item in expected_order]:
            out.append(_violation("graph_order", "", "declarations must be grouped by kind and sorted by identifier"))

    triples = 2 + 3 * len(classes) + 5 * len(properties)
    if triples > MAX_TRIPLES:
        out.append(_violation("triple_limit", "", f"emits {triples} RDF triples; maximum is {MAX_TRIPLES}"))
    if not out:
        try:
            canonical = hashing.canonical_bytes(document)
        except (UnicodeEncodeError, ValueError) as exc:
            out.append(_violation("invalid_json", "", f"document cannot be canonically encoded ({exc})"))
        else:
            if canonical != raw:
                out.append(_violation("not_canonical", "", "bytes differ from canonical JSON serialization"))
    return out


def require_valid(data: bytes, *, file: str = "<output>") -> None:
    """Raise `JSONLD_PROFILE_VIOLATION` when an inline-compatible document is invalid."""
    violations = validate(data)
    if not violations:
        return
    shown = "; ".join(str(item) for item in violations[:5])
    if len(violations) > 5:
        shown += f"; and {len(violations) - 5} more"
    raise Blocked("JSONLD_PROFILE_VIOLATION", shown,
                  details={"violations": [str(item) for item in violations]}, file=file)
