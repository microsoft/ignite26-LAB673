from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from xml.etree import ElementTree

from .models import Ontology, OntologyMode, OntologyProperty
from .schema_org_profiles import (
    PROFILE_NAME, PROFILE_VERSION, PROFILES, canonical_profile_bytes, profile_properties,
)


def _sha256(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


_OWL = "http://www.w3.org/2002/07/owl#"
_RDFS = "http://www.w3.org/2000/01/rdf-schema#"
_XSD = "http://www.w3.org/2001/XMLSchema#"
_RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
_JSONLD_TYPES = {
    _OWL + "Ontology": "ontology",
    _OWL + "Class": "class",
    _RDFS + "Class": "class",
    _OWL + "ObjectProperty": "object_property",
    _OWL + "DatatypeProperty": "datatype_property",
}
_JSONLD_PREDICATES = {
    _RDFS + "domain": "domain",
    _RDFS + "range": "range",
    _RDFS + "label": "label",
    _RDFS + "comment": "comment",
    _RDFS + "seeAlso": "metadata",
    _RDFS + "isDefinedBy": "metadata",
    _OWL + "versionInfo": "metadata_text",
    _OWL + "versionIRI": "metadata",
}
_XSD_RANGES = {"string", "double", "decimal", "integer", "boolean", "date", "dateTime"}
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_PREFIX = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*\Z")


def _jsonld_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"inline JSON-LD contains duplicate key {key!r}")
        result[key] = value
    return result


def _jsonld_depth(value: object, depth: int = 0) -> int:
    if depth > 32:
        raise ValueError("inline JSON-LD exceeds the maximum JSON depth of 32")
    if isinstance(value, dict):
        for child in value.values():
            _jsonld_depth(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _jsonld_depth(child, depth + 1)
    return depth


def _expand_jsonld_iri(value: object, context: dict[str, str]) -> str:
    if not isinstance(value, str) or not value or value.startswith("_:"):
        raise ValueError("inline JSON-LD identifiers must be named IRIs")
    if value in context:
        return context[value]
    prefix, separator, suffix = value.partition(":")
    if separator and prefix in context:
        return context[prefix] + suffix
    if separator and re.fullmatch(r"[A-Za-z][A-Za-z0-9+.-]*", prefix):
        return value
    raise ValueError(f"inline JSON-LD identifier is not an absolute IRI: {value!r}")


def _jsonld_local_name(iri: str) -> str:
    name = iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    if not _IDENTIFIER.fullmatch(name):
        raise ValueError(f"inline JSON-LD IRI has no supported simple name: {iri!r}")
    return name


def _jsonld_text(value: object, field: str) -> str:
    if isinstance(value, str):
        return value.strip()
    if (isinstance(value, dict) and set(value) == {"@value", "@language"}
            and isinstance(value["@value"], str)
            and isinstance(value["@language"], str) and value["@language"].strip()):
        return value["@value"].strip()
    raise ValueError(f"inline JSON-LD {field} must be a string or one language-tagged string")


def _load_inline_jsonld(data: bytes, reference: str) -> Ontology:
    try:
        text = data.decode("utf-8")
        if len(text.encode("utf-16-le")) // 2 > 65536:
            raise ValueError("inline JSON-LD exceeds the 65,536 UTF-16 code-unit limit")
        document = json.loads(text, object_pairs_hook=_jsonld_object)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError("inline ontology must be valid UTF-8 JSON") from error
    _jsonld_depth(document)
    if not isinstance(document, dict) or set(document) != {"@context", "@graph"}:
        raise ValueError("inline JSON-LD must contain only @context and @graph")
    raw_context = document["@context"]
    if not isinstance(raw_context, dict):
        raise ValueError("inline JSON-LD @context must be a local object")
    context: dict[str, str] = {}
    for prefix, iri in raw_context.items():
        if prefix == "@version":
            if iri != 1.1:
                raise ValueError("inline JSON-LD supports only @version 1.1")
            continue
        if not _PREFIX.fullmatch(prefix) or not isinstance(iri, str):
            raise ValueError("inline JSON-LD context entries must be flat prefix-to-IRI strings")
        expanded = _expand_jsonld_iri(iri, {})
        if expanded.startswith("_:"):
            raise ValueError("inline JSON-LD context IRIs must be absolute")
        context[prefix] = expanded
    if not context:
        raise ValueError("inline JSON-LD @context must define at least one prefix")
    graph = document["@graph"]
    if not isinstance(graph, list):
        raise ValueError("inline JSON-LD @graph must be an array")
    if not 1 <= len(graph) <= 128:
        raise ValueError("inline JSON-LD exceeds the 128 declaration limit")

    subjects: dict[str, dict] = {}
    triple_set: set[tuple[str, str, str]] = set()
    for entry in graph:
        if not isinstance(entry, dict):
            raise ValueError("inline JSON-LD declarations must be objects")
        if not isinstance(entry.get("@type"), (str, list)):
            raise ValueError("inline JSON-LD declarations must be typed objects")
        identifier = _expand_jsonld_iri(entry.get("@id"), context)
        raw_type = entry["@type"]
        types = raw_type if isinstance(raw_type, list) else [raw_type]
        if not types or any(not isinstance(value, str) for value in types):
            raise ValueError("inline JSON-LD declarations require one supported type")
        expanded_types = {_expand_jsonld_iri(value, context) for value in types}
        if len(expanded_types) != 1:
            raise ValueError("inline JSON-LD subjects must have exactly one distinct type")
        kind = _JSONLD_TYPES.get(next(iter(expanded_types)))
        if kind is None:
            raise ValueError(f"unsupported inline JSON-LD type: {raw_type!r}")
        triple_set.add((identifier, _RDF_TYPE, next(iter(expanded_types))))
        normalized = {"@id": identifier, "@type": kind}
        for predicate, value in entry.items():
            if predicate in {"@id", "@type"}:
                continue
            expanded_predicate = _expand_jsonld_iri(predicate, context)
            semantic = _JSONLD_PREDICATES.get(expanded_predicate)
            if semantic is None:
                raise ValueError(f"unsupported inline JSON-LD predicate: {predicate!r}")
            if semantic in {"domain", "range", "metadata"}:
                if not isinstance(value, dict) or set(value) != {"@id"}:
                    raise ValueError(f"inline JSON-LD {predicate} must be one named IRI reference")
                value = {"@id": _expand_jsonld_iri(value["@id"], context)}
            elif semantic in {"label", "comment"}:
                label_or_comment = _jsonld_text(value, predicate)
                language = value.get("@language") if isinstance(value, dict) else None
                value = (label_or_comment, language)
            elif semantic == "metadata_text":
                value = _jsonld_text(value, predicate)
            triple_set.add((
                identifier, expanded_predicate,
                json.dumps(value, sort_keys=True, ensure_ascii=False),
            ))
            if semantic in {"metadata", "metadata_text"}:
                continue
            if semantic in normalized:
                if normalized[semantic] != value:
                    raise ValueError(f"inline JSON-LD has multiple values for {predicate!r}")
            else:
                normalized[semantic] = value
        prior = subjects.get(identifier)
        if prior is None:
            subjects[identifier] = normalized
        elif prior["@type"] != kind:
            raise ValueError(f"inline JSON-LD subject {identifier!r} has multiple types")
        else:
            for predicate, value in normalized.items():
                if predicate in {"@id", "@type"}:
                    continue
                if predicate in prior and prior[predicate] != value:
                    raise ValueError(f"inline JSON-LD has multiple values for {predicate!r}")
                prior[predicate] = value
    if len(graph) > 128 or len(subjects) > 128:
        raise ValueError("inline JSON-LD exceeds the 128 declaration limit")
    if len(triple_set) > 512:
        raise ValueError("inline JSON-LD exceeds the 512 triple limit")

    header_count = sum(entry["@type"] == "ontology" for entry in subjects.values())
    if header_count > 1:
        raise ValueError("inline JSON-LD allows at most one ontology header")
    entries = [(iri, entry["@type"], entry) for iri, entry in subjects.items()]
    classes: dict[str, tuple[str, str]] = {}
    node_names: dict[str, str] = {}
    edge_names: dict[str, str] = {}

    def register(iri: str, entry: dict, registry: dict[str, str],
                 prefix: str = "") -> str:
        label = entry.get("label", ("", None))[0]
        name = label if _IDENTIFIER.fullmatch(label) else _jsonld_local_name(iri)
        key = (prefix + name).casefold()
        if key in registry:
            raise ValueError(f"inline JSON-LD has a case-insensitive identifier collision: {name!r}")
        registry[key] = iri
        return name

    for iri, kind, entry in entries:
        if kind != "class":
            continue
        if "domain" in entry or "range" in entry:
            raise ValueError("inline JSON-LD class declarations cannot have domain or range")
        name = register(iri, entry, node_names)
        comment = entry.get("comment", ("", None))[0]
        classes[iri] = (name, comment)
    if not classes:
        raise ValueError("inline JSON-LD requires at least one named class")

    properties: list[OntologyProperty] = []
    edges: list[tuple[str, str, str]] = []
    descriptions = [(name, "NodeType", comment) for name, comment in classes.values() if comment]

    def class_reference(value: object, field: str) -> str | None:
        if value is None:
            return None
        if not isinstance(value, dict) or set(value) != {"@id"}:
            raise ValueError(f"inline JSON-LD {field} must be one named class reference")
        iri = value["@id"]
        if iri not in classes:
            raise ValueError(f"inline JSON-LD {field} references an undeclared class")
        return classes[iri][0]

    property_count = 0
    for iri, kind, entry in entries:
        if kind == "ontology":
            if "domain" in entry or "range" in entry:
                raise ValueError("inline JSON-LD ontology header cannot have domain or range")
            continue
        if kind not in {"object_property", "datatype_property"}:
            continue
        property_count += 1
        is_datatype = kind == "datatype_property"
        name = register(iri, entry, edge_names, "prop:" if is_datatype else "")
        domain = class_reference(entry.get("domain"), "domain")
        description = entry.get("comment", ("", None))[0]
        if kind == "object_property":
            range_name = class_reference(entry.get("range"), "range")
            properties.append(OntologyProperty(
                name=name, domain=domain, range=range_name, value_kind="entity",
                description=description,
            ))
            if domain and range_name:
                edges.append((domain, name, range_name))
                if description:
                    descriptions.append((name, "EdgeType", description))
        else:
            range_value = entry.get("range")
            if not isinstance(range_value, dict) or set(range_value) != {"@id"}:
                raise ValueError("inline JSON-LD datatype property requires one xsd range")
            range_iri = range_value["@id"]
            if not range_iri.startswith(_XSD):
                raise ValueError("inline JSON-LD datatype range must use the fixed xsd namespace")
            datatype = range_iri[len(_XSD):]
            if datatype not in _XSD_RANGES:
                raise ValueError(f"unsupported inline JSON-LD datatype: {datatype!r}")
            properties.append(OntologyProperty(
                name=name, domain=domain, range=f"xsd:{datatype}",
                value_kind="literal", description=description,
            ))
    if property_count == 0:
        raise ValueError("inline JSON-LD requires at least one supported property")
    return Ontology(
        schema_id=_sha256(data),
        source_kind="inline_jsonld",
        source_reference=reference,
        node_types=tuple(sorted(name for name, _ in classes.values())),
        edge_types=tuple(sorted(edges)),
        properties=tuple(sorted(properties, key=lambda item: item.name)),
        descriptions=tuple(sorted(descriptions)),
        inline_jsonld=text,
    )


def load_ontology(
    mode: OntologyMode,
    *,
    path: str | None = None,
    schema_org_profile: str | None = None,
    schema_org_version: str | None = None,
    resolve_imports: bool = False,
) -> Ontology | None:
    if mode is OntologyMode.NONE:
        return None
    if mode is OntologyMode.SCHEMA_ORG:
        # One bundled profile; older specs may still name it explicitly.
        schema_org_profile = schema_org_profile or PROFILE_NAME
        schema_org_version = schema_org_version or PROFILE_VERSION
        profile = PROFILES.get(schema_org_version)
        if profile is None or schema_org_profile != profile["name"]:
            raise ValueError(
                f"unsupported Schema.org profile/version: {schema_org_profile}:{schema_org_version}"
            )
        source = f"schema_org:{schema_org_profile}:{schema_org_version}"
        properties = profile_properties(schema_org_version)
        entities = [item for item in properties
                    if item.value_kind == "entity" and item.domain and item.range]
        edges = tuple(sorted((item.domain, item.name, item.range) for item in entities))
        edge_text = {item.name: item.description for item in entities}
        descriptions = (
            *((name, "NodeType", text) for name, text in profile["classes"].items()),
            *((name, "EdgeType", text) for name, text in edge_text.items()),
        )
        return Ontology(
            schema_id=_sha256(canonical_profile_bytes(schema_org_version)),
            source_kind="schema_org",
            source_reference=source,
            node_types=tuple(sorted({*profile["classes"], *(
                name for item in entities for name in (item.domain, item.range))})),
            edge_types=edges,
            properties=properties,
            descriptions=descriptions,
        )
    if not path:
        raise ValueError(f"{mode.value} mode requires ontology_path")
    file_path = Path(path)
    data = file_path.read_bytes()
    if mode is OntologyMode.INLINE_JSONLD:
        if resolve_imports or schema_org_profile is not None or schema_org_version is not None:
            raise ValueError("inline_jsonld does not accept OWL import or Schema.org options")
        return _load_inline_jsonld(data, str(file_path))
    root = ElementTree.fromstring(data)
    imports = [element for element in root.iter() if element.tag.rsplit("}", 1)[-1] == "imports"]
    if imports:
        raise ValueError("OWL imports are not supported; supply a locally resolved ontology")
    nodes, edges, properties = _extract_simple_rdf_names(data)
    return Ontology(
        schema_id=_sha256(data),
        source_kind="owl_file",
        source_reference=str(file_path),
        node_types=tuple(sorted(nodes)),
        edge_types=tuple(sorted(edges)),
        properties=tuple(sorted(properties, key=lambda item: item.name)),
    )


def _local_name(value: str) -> str:
    return value.rsplit("#", 1)[-1].rsplit("/", 1)[-1].rsplit(":", 1)[-1]


def _registered_name(value: str, seen: dict[str, str], kind: str) -> str:
    name = _local_name(value)
    if not name:
        raise ValueError(f"OWL {kind} has an empty local name")
    prior = seen.setdefault(name, value)
    if prior != value:
        raise ValueError(f"OWL {kind} local-name collision for {name!r}")
    return name


def _extract_simple_rdf_names(
    data: bytes,
) -> tuple[set[str], set[tuple[str, str, str]], set[OntologyProperty]]:
    nodes: set[str] = set()
    edges: set[tuple[str, str, str]] = set()
    properties: set[OntologyProperty] = set()
    class_names: dict[str, str] = {}
    property_names: dict[str, str] = {}
    root = ElementTree.fromstring(data)
    for element in root.iter():
        local = element.tag.rsplit("}", 1)[-1]
        about = next((v for k, v in element.attrib.items() if k.rsplit("}", 1)[-1] in {"about", "ID"}), None)
        if local == "Class" and about:
            nodes.add(_registered_name(about, class_names, "class"))
        if local in {"ObjectProperty", "DatatypeProperty", "Property"} and about:
            resource = _registered_name(about, property_names, "property")
            values = {"domain": None, "range": None, "description": ""}
            for child in element:
                child_local = child.tag.rsplit("}", 1)[-1]
                target = next(
                    (value for key, value in child.attrib.items()
                     if key.rsplit("}", 1)[-1] in {"resource", "about"}),
                    None,
                )
                if child_local == "domain" and target:
                    values["domain"] = _registered_name(target, class_names, "class")
                elif child_local == "range" and target:
                    values["range"] = _registered_name(target, class_names, "class")
                elif child_local in {"label", "comment"} and child.text:
                    values["description"] = child.text.strip()
            domain = values["domain"]
            range_name = values["range"]
            value_kind = "entity" if local == "ObjectProperty" else "literal"
            properties.add(OntologyProperty(
                name=resource, domain=domain, range=range_name,
                value_kind=value_kind, description=values["description"] or "",
            ))
            if local == "ObjectProperty" and domain and range_name:
                edges.add((domain, resource, range_name))
    return nodes, edges, properties
