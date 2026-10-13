from __future__ import annotations

import hashlib
from pathlib import Path
from xml.etree import ElementTree

from .models import Ontology, OntologyMode, OntologyProperty
from .schema_org_profiles import (
    PROFILE_NAME, PROFILE_VERSION, PROFILES, canonical_profile_bytes, profile_properties,
)


def _sha256(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


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
        raise ValueError("OWL mode requires ontology_path")
    file_path = Path(path)
    data = file_path.read_bytes()
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
