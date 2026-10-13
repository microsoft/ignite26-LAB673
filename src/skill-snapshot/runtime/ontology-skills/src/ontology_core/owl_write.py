"""Byte-exact flat-owl RDF/XML writer. No rdflib."""

from __future__ import annotations

import re

from ontology_core import names
from ontology_core.errors import Blocked
from ontology_core.hygiene import normalize_text
from ontology_core.model import Ontology

XSD_MAP: dict[str, str] = {"String": "string", "Double": "double", "Boolean": "boolean", "DateTime": "dateTime"}
XSD_NS = "http://www.w3.org/2001/XMLSchema#"

_BAD_IRI = re.compile(r'[\s"<>]')
_HEADER = """<?xml version="1.0" encoding="utf-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
         xmlns:owl="http://www.w3.org/2002/07/owl#"
         xmlns:xsd="http://www.w3.org/2001/XMLSchema#"
         xml:base="{base}">
  <owl:Ontology rdf:about="{base}">
    <owl:versionInfo>{version_info}</owl:versionInfo>
  </owl:Ontology>
"""


def default_base_iri(source_index: str) -> str:
    """`urn:ontology:<names.slug(source_index)>#`."""
    return f"urn:ontology:{names.slug(source_index)}#"


def validate_base_iri(base_iri: str) -> str:
    """Return `base_iri` unchanged if it ends with `#` and has no whitespace, `"`, `<` or `>`.

    Raises:
        Blocked("BASE_IRI_INVALID"): otherwise.
    """
    if not isinstance(base_iri, str) or len(base_iri) < 2 or not base_iri.endswith("#") \
            or _BAD_IRI.search(base_iri):
        raise Blocked("BASE_IRI_INVALID", f"invalid base IRI {base_iri!r}: it must end with '#' and contain no "
                      "whitespace, quotes or angle brackets")
    return base_iri


def version_info(version: int, schema_id: str) -> str:
    """`v<N> <schema_id>`, e.g. `v3 sha256:ab12...`."""
    return f"v{version} {schema_id}"


def escape(text: str) -> str:
    """Escape `& < > "`, drop control chars and XML-illegal code points (tab, CR and LF count as whitespace),
    collapse whitespace runs, trim."""
    return (normalize_text(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def write(ontology: Ontology, *, base_iri: str, version_info: str) -> bytes:
    """Serialize as flat-owl RDF/XML: UTF-8, LF, 2-space indent, exactly one trailing LF; classes, then object
    properties, then datatype properties, each sorted by codepoint; label first, comment last;
    `rdfs:subClassOf` between them when `parent` is set. Deterministic: same input, same bytes.

    Raises:
        Blocked("BASE_IRI_INVALID"): via `validate_base_iri`.
        ValueError: a datatype property's range is not one of `XSD_MAP` (hygiene never lets one through).
    """
    base = escape(validate_base_iri(base_iri))
    lines = [_HEADER.format(base=base[:-1], version_info=escape(version_info))]
    for cls in sorted(ontology.classes, key=lambda c: c.name):
        lines.append(f'  <owl:Class rdf:about="{base}{escape(cls.name)}">\n')
        lines.append(f"    <rdfs:label>{escape(cls.name)}</rdfs:label>\n")
        if cls.parent:
            lines.append(f'    <rdfs:subClassOf rdf:resource="{base}{escape(cls.parent)}"/>\n')
        lines.append(f"    <rdfs:comment>{escape(cls.description)}</rdfs:comment>\n")
        lines.append("  </owl:Class>\n")
    for kind, tag in (("object", "owl:ObjectProperty"), ("datatype", "owl:DatatypeProperty")):
        for prop in sorted((p for p in ontology.properties if p.kind == kind), key=lambda p: p.name):
            if kind == "object":
                range_iri = base + escape(prop.range)
            elif prop.range in XSD_MAP:
                range_iri = XSD_NS + XSD_MAP[prop.range]
            else:
                raise ValueError(f"datatype property {prop.name!r} has unsupported range {prop.range!r}")
            lines.append(f'  <{tag} rdf:about="{base}{escape(prop.name)}">\n')
            lines.append(f"    <rdfs:label>{escape(prop.name)}</rdfs:label>\n")
            lines.append(f'    <rdfs:domain rdf:resource="{base}{escape(prop.domain)}"/>\n')
            lines.append(f'    <rdfs:range rdf:resource="{range_iri}"/>\n')
            lines.append(f"    <rdfs:comment>{escape(prop.description)}</rdfs:comment>\n")
            lines.append(f"  </{tag}>\n")
    lines.append("</rdf:RDF>\n")
    return "".join(lines).encode("utf-8")
