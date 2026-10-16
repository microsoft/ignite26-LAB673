"""Deterministic JSON-LD writer for the inline-compatible ontology profile."""

from __future__ import annotations

from ontology_core import hashing, names, owl_write
from ontology_core.errors import Blocked
from ontology_core.hygiene import normalize_text
from ontology_core.model import Ontology

OWL_NS = "http://www.w3.org/2002/07/owl#"
RDFS_NS = "http://www.w3.org/2000/01/rdf-schema#"
XSD_NS = owl_write.XSD_NS
XSD_MAP = owl_write.XSD_MAP


def write(ontology: Ontology, *, base_iri: str, version_info: str) -> bytes:
    """Write the supported flat ontology shape as canonical JSON-LD bytes.

    Parent classes are rejected rather than silently omitted. The profile validator is responsible for
    enforcing the inline consumer's size, declaration and RDF-triple limits.
    """
    base = owl_write.validate_base_iri(base_iri)
    try:
        base.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise Blocked("BASE_IRI_INVALID", "base IRI must be valid UTF-8") from exc
    if any(cls.parent for cls in ontology.classes):
        raise Blocked("JSONLD_EXPORT_UNSUPPORTED", "inline JSON-LD does not support class inheritance")
    unsupported = sorted({prop.kind for prop in ontology.properties if prop.kind not in ("object", "datatype")})
    if unsupported:
        raise Blocked("JSONLD_EXPORT_UNSUPPORTED",
                      f"property kind {unsupported[0]!r} is not supported by inline JSON-LD")
    class_names = {cls.name for cls in ontology.classes}
    for cls in ontology.classes:
        if not names.is_valid(cls.name):
            raise Blocked("JSONLD_EXPORT_UNSUPPORTED", f"class identifier {cls.name!r} is not supported")
    for prop in ontology.properties:
        if not names.is_valid(prop.name):
            raise Blocked("JSONLD_EXPORT_UNSUPPORTED", f"property identifier {prop.name!r} is not supported")
        if prop.domain not in class_names:
            raise Blocked("JSONLD_EXPORT_UNSUPPORTED", f"domain for property {prop.name!r} is not a declared class")
        if prop.kind == "object" and prop.range not in class_names:
            raise Blocked("JSONLD_EXPORT_UNSUPPORTED", f"range for property {prop.name!r} is not a declared class")

    graph: list[dict[str, object]] = [{
        "@id": base,
        "@type": "owl:Ontology",
        "owl:versionInfo": normalize_text(version_info),
    }]
    for cls in sorted(ontology.classes, key=lambda item: item.name):
        graph.append({
            "@id": base + cls.name,
            "@type": "owl:Class",
            "rdfs:label": cls.name,
            "rdfs:comment": normalize_text(cls.description),
        })
    for kind, jsonld_type in (("object", "owl:ObjectProperty"), ("datatype", "owl:DatatypeProperty")):
        for prop in sorted((item for item in ontology.properties if item.kind == kind), key=lambda item: item.name):
            if kind == "object":
                range_id = base + prop.range
            elif prop.range in XSD_MAP:
                range_id = XSD_NS + XSD_MAP[prop.range]
            else:
                raise Blocked("JSONLD_EXPORT_UNSUPPORTED",
                              f"datatype property {prop.name!r} has unsupported range {prop.range!r}")
            graph.append({
                "@id": base + prop.name,
                "@type": jsonld_type,
                "rdfs:label": prop.name,
                "rdfs:domain": {"@id": base + prop.domain},
                "rdfs:range": {"@id": range_id},
                "rdfs:comment": normalize_text(prop.description),
            })

    document = {
        "@context": {"owl": OWL_NS, "rdfs": RDFS_NS, "xsd": XSD_NS},
        "@graph": graph,
    }
    return hashing.canonical_bytes(document)
