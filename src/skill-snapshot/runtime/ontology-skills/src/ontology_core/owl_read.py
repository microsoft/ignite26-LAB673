"""OWL import.

Readers return the raw hygiene input shape, not a cleaned `Ontology`; callers run
`hygiene.clean(raw, None, seed, version=..., origin="import")`. Construct-drop counts come back as
warnings so they can be merged into the version's `HygieneReport.warnings`.

Every format is first turned into a flat list of triples, then one extractor keeps only `owl:Class`,
`owl:ObjectProperty`, `owl:DatatypeProperty`, `rdfs:label`, `rdfs:comment`, `rdfs:domain`, `rdfs:range`
and `rdfs:subClassOf`. XML input may be RDF/XML (root `rdf:RDF`) or OWL/XML (root `owl:Ontology`); both
are parsed with ElementTree after an expat pass that rejects DOCTYPE and entity declarations.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urljoin
from xml.parsers import expat

from ontology_core.errors import Blocked
from ontology_core.hygiene import map_datatype
from ontology_core.model import ClassDef, Ontology, PropertyDef

MAX_BYTES = 5 * 1024 * 1024
Format = Literal["rdfxml", "turtle", "ntriples", "json"]
EXTENSIONS: dict[str, Format] = {
    ".owl": "rdfxml", ".rdf": "rdfxml", ".xml": "rdfxml", ".ttl": "turtle", ".nt": "ntriples", ".json": "json",
}

RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
OWL = "http://www.w3.org/2002/07/owl#"
XSD = "http://www.w3.org/2001/XMLSchema#"
XML = "http://www.w3.org/XML/1998/namespace"

_TYPE = RDF + "type"
_KINDS = {OWL + "Class": "class", OWL + "ObjectProperty": "object", OWL + "DatatypeProperty": "datatype"}
_FROM_XSD = {"string": "String", "double": "Double", "boolean": "Boolean", "dateTime": "DateTime"}
_DECLARATIONS = {
    "Class": OWL + "Class", "ObjectProperty": OWL + "ObjectProperty", "DataProperty": OWL + "DatatypeProperty",
    "NamedIndividual": OWL + "NamedIndividual", "AnnotationProperty": OWL + "AnnotationProperty",
    "Datatype": RDFS + "Datatype",
}
_AXIOMS = {
    "SubClassOf": RDFS + "subClassOf", "ObjectPropertyDomain": RDFS + "domain",
    "ObjectPropertyRange": RDFS + "range", "DataPropertyDomain": RDFS + "domain",
    "DataPropertyRange": RDFS + "range",
}
_NAMED = {"Class", "ObjectProperty", "DataProperty", "Datatype", "NamedIndividual", "AnnotationProperty"}
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")
_DECL_SCAN = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)

# A term is ("iri", value, None), ("bnode", id, None) or ("lit", value, lang).
Term = tuple[str, str, str | None]
Triple = tuple[Term, str, Term]


@dataclass
class ReadResult:
    raw: dict[str, Any]
    """`{"classes":[{name, description, parent}], "properties":[{name, kind, domain, range, description}]}`
    with local names (IRI fragment or last path segment) and no evidence."""
    warnings: list[str] = field(default_factory=list)
    """`dropped_construct:<kind>:<n>` and `no_description:<name>` entries."""
    base_iri: str | None = None


def detect_format(path: Path) -> Format:
    """By extension (case-insensitive) via `EXTENSIONS`.

    Raises:
        Blocked("IMPORT_UNSUPPORTED_FORMAT"): unknown extension.
    """
    fmt = EXTENSIONS.get(Path(path).suffix.lower())
    if fmt is None:
        raise Blocked("IMPORT_UNSUPPORTED_FORMAT", f"unsupported file extension {Path(path).suffix!r}",
                      details={"file": str(path)})
    return fmt


def read_bytes(data: bytes, fmt: Format) -> ReadResult:
    """Parse `data`. RDF/XML (and OWL/XML) uses ElementTree after a raw scan for `<!DOCTYPE`/`<!ENTITY`;
    Turtle and N-Triples use rdflib; `json` is the model's ontology shape (evidence and seed flags dropped).

    Raises:
        Blocked("IMPORT_INVALID"): over `MAX_BYTES`, DOCTYPE/ENTITY present, or malformed.
        Blocked("IMPORT_HAS_IMPORTS"): `owl:imports` present.
    """
    parsed = _parse(data, fmt)
    return ReadResult(raw=parsed.raw, warnings=parsed.warnings, base_iri=parsed.base_iri)


def read_file(path: Path) -> ReadResult:
    """`read_bytes(path.read_bytes(), detect_format(path))`, checking size before reading.

    Raises: as `detect_format` and `read_bytes`.
    """
    path = Path(path)
    fmt = detect_format(path)
    try:
        size = path.stat().st_size
        if size > MAX_BYTES:
            raise Blocked("IMPORT_INVALID", f"{path.name} is {size} bytes; the limit is {MAX_BYTES}",
                          details={"file": str(path)})
        data = path.read_bytes()
    except OSError as exc:
        raise Blocked("IMPORT_INVALID", f"cannot read {path}: {exc.strerror or exc}", details={"file": str(path)}) \
            from exc
    return read_bytes(data, fmt)


def read(data: bytes) -> Ontology:
    """Parse our own flat-owl RDF/XML back into an `Ontology` (version from `owl:versionInfo` `v<N>`,
    else 0; empty evidence; `seed=False`). Guarantee: `read(owl_write.write(o, ...)) == o` with evidence
    stripped, for any `o` that passed hygiene.

    Raises: as `read_bytes`.
    """
    parsed = _parse(data, "rdfxml")
    match = re.match(r"v(\d+)(?:\s|$)", parsed.version_info or "")
    classes = [ClassDef(name=c["name"], description=c["description"], evidence=[], parent=c["parent"], seed=False)
               for c in parsed.raw["classes"]]
    properties = []
    for p in parsed.raw["properties"]:
        range_ = p["range"]
        if p["kind"] == "datatype":
            range_ = _FROM_XSD.get(range_) or map_datatype(range_) or range_
        properties.append(PropertyDef(name=p["name"], kind=p["kind"], domain=p["domain"], range=range_,
                                      description=p["description"], evidence=[], seed=False))
    return Ontology(version=int(match.group(1)) if match else 0, classes=classes, properties=properties).canonical()


# --------------------------------------------------------------------------- parsing


@dataclass
class _Parsed:
    raw: dict[str, Any]
    warnings: list[str]
    base_iri: str | None
    version_info: str | None


def _invalid(message: str) -> Blocked:
    return Blocked("IMPORT_INVALID", message)


def _parse(data: bytes, fmt: Format) -> _Parsed:
    if not isinstance(data, (bytes, bytearray)):
        raise _invalid("input must be bytes")
    if len(data) > MAX_BYTES:
        raise _invalid(f"input is {len(data)} bytes; the limit is {MAX_BYTES}")
    if fmt == "json":
        return _parse_json(bytes(data))
    if fmt == "rdfxml":
        triples, drops = _xml_triples(bytes(data))
    elif fmt in ("turtle", "ntriples"):
        triples, drops = _rdflib_triples(bytes(data), fmt)
    else:
        raise Blocked("IMPORT_UNSUPPORTED_FORMAT", f"unsupported format {fmt!r}")
    return _extract(triples, drops)


def _parse_json(data: bytes) -> _Parsed:
    try:
        doc = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise _invalid(f"malformed JSON: {exc}") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("classes", []), list) \
            or not isinstance(doc.get("properties", []), list):
        raise _invalid("JSON must be an object with `classes` and `properties` lists")
    classes = [{"name": c.get("name"), "description": c.get("description"), "parent": c.get("parent")}
               for c in doc.get("classes", []) if isinstance(c, dict)]
    properties = [{k: p.get(k) for k in ("name", "kind", "domain", "range", "description")}
                  for p in doc.get("properties", []) if isinstance(p, dict)]
    return _Parsed({"classes": classes, "properties": properties}, [], None, None)


def _guard_xml(data: bytes) -> None:
    """XXE guard: a raw byte scan plus an expat pass that fails on any DOCTYPE or entity declaration."""
    if _DECL_SCAN.search(data):
        raise _invalid("DOCTYPE and ENTITY declarations are not allowed")

    def refuse(*_: Any) -> None:
        raise _invalid("DOCTYPE and ENTITY declarations are not allowed")

    parser = expat.ParserCreate()
    parser.StartDoctypeDeclHandler = refuse
    parser.EntityDeclHandler = refuse
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    try:
        parser.Parse(data, True)
    except expat.ExpatError as exc:
        raise _invalid(f"malformed XML: {expat.ErrorString(exc.code)} at line {exc.lineno}") from exc


def _parse_xml(data: bytes) -> ET.Element:
    _guard_xml(data)
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise _invalid(f"malformed XML: {exc}") from exc


def _xml_triples(data: bytes) -> tuple[list[Triple], Counter[str]]:
    root = _parse_xml(data)
    if root.tag == f"{{{RDF}}}RDF":
        return _RdfXml().triples(root), Counter()
    if root.tag == f"{{{OWL}}}Ontology":
        return _owlxml_triples(root)
    raise _invalid("the root element is neither rdf:RDF nor an OWL/XML Ontology")


def _tag_iri(tag: str) -> str:
    return tag[1:].replace("}", "", 1) if tag.startswith("{") else tag


def _resolve(base: str, ref: str) -> str:
    ref = ref.strip()
    if _SCHEME.match(ref):
        return ref
    if ref.startswith("#") or ref == "":
        return base.split("#", 1)[0] + ref
    return urljoin(base, ref)


class _RdfXml:
    """RDF/XML node and property elements, typed nodes, `rdf:ID`, `rdf:nodeID`, `rdf:parseType` and
    property attributes. Reification and container membership are not needed for our subset."""

    def __init__(self) -> None:
        self.out: list[Triple] = []
        self.n = 0

    def triples(self, root: ET.Element) -> list[Triple]:
        base = root.get(f"{{{XML}}}base", "")
        for child in root:
            self.node(child, base)
        return self.out

    def fresh(self) -> Term:
        self.n += 1
        return ("bnode", f"b{self.n}", None)

    def node(self, el: ET.Element, base: str) -> Term:
        base = el.get(f"{{{XML}}}base", base)
        if (about := el.get(f"{{{RDF}}}about")) is not None:
            subject: Term = ("iri", _resolve(base, about), None)
        elif (rid := el.get(f"{{{RDF}}}ID")) is not None:
            subject = ("iri", base.split("#", 1)[0] + "#" + rid, None)
        elif (nid := el.get(f"{{{RDF}}}nodeID")) is not None:
            subject = ("bnode", "n" + nid, None)
        else:
            subject = self.fresh()
        if el.tag != f"{{{RDF}}}Description":
            self.out.append((subject, _TYPE, ("iri", _tag_iri(el.tag), None)))
        for attr, value in el.attrib.items():
            if attr.startswith((f"{{{XML}}}", f"{{{RDF}}}about", f"{{{RDF}}}ID", f"{{{RDF}}}nodeID")):
                continue
            if attr == f"{{{RDF}}}type":
                self.out.append((subject, _TYPE, ("iri", _resolve(base, value), None)))
            else:
                self.out.append((subject, _tag_iri(attr), ("lit", value, None)))
        for child in el:
            self.prop(subject, child, base)
        return subject

    def prop(self, subject: Term, el: ET.Element, base: str) -> None:
        base = el.get(f"{{{XML}}}base", base)
        predicate = _tag_iri(el.tag)
        parse_type = el.get(f"{{{RDF}}}parseType")
        if (resource := el.get(f"{{{RDF}}}resource")) is not None:
            obj: Term = ("iri", _resolve(base, resource), None)
        elif (nid := el.get(f"{{{RDF}}}nodeID")) is not None:
            obj = ("bnode", "n" + nid, None)
        elif parse_type == "Resource":
            obj = self.fresh()
            for child in el:
                self.prop(obj, child, base)
        elif parse_type == "Collection":
            obj = self.fresh()
            for child in el:
                self.node(child, base)
        elif len(el) and parse_type != "Literal":
            obj = self.node(el[0], base)
        else:
            text = "".join(el.itertext()) if parse_type == "Literal" else (el.text or "")
            obj = ("lit", text, el.get(f"{{{XML}}}lang"))
        self.out.append((subject, predicate, obj))


def _owlxml_triples(root: ET.Element) -> tuple[list[Triple], Counter[str]]:
    """OWL 2 XML: declarations, named SubClassOf, property domain/range and label/comment assertions."""
    base = root.get(f"{{{XML}}}base") or root.get("ontologyIRI") or ""
    prefixes = {"owl": OWL, "rdf": RDF, "rdfs": RDFS, "xsd": XSD, "xml": XML + "#"}
    for el in root.iter(f"{{{OWL}}}Prefix"):
        prefixes[el.get("name", "")] = el.get("IRI", "")
    drops: Counter[str] = Counter()
    out: list[Triple] = []

    def iri(el: ET.Element) -> str:
        if el.get("abbreviatedIRI") is not None:
            prefix, _, local = el.get("abbreviatedIRI", "").partition(":")
            return prefixes.get(prefix, "") + local
        return _resolve(base, el.get("IRI", ""))

    def local(el: ET.Element) -> str:
        return el.tag.rsplit("}", 1)[-1]

    ontology: Term = ("iri", root.get("ontologyIRI") or base, None)
    out.append((ontology, _TYPE, ("iri", OWL + "Ontology", None)))
    for axiom in root:
        tag = local(axiom)
        args = [a for a in axiom if local(a) != "Annotation"]
        if tag in ("Prefix", "Annotation"):
            continue
        if tag == "Import":
            out.append((ontology, OWL + "imports", ("iri", (axiom.text or "").strip(), None)))
        elif tag == "Declaration" and args and local(args[0]) in _DECLARATIONS:
            out.append((("iri", iri(args[0]), None), _TYPE, ("iri", _DECLARATIONS[local(args[0])], None)))
        elif tag in _AXIOMS and len(args) == 2 and local(args[0]) in _NAMED:
            subject: Term = ("iri", iri(args[0]), None)
            if local(args[1]) in _NAMED:
                out.append((subject, _AXIOMS[tag], ("iri", iri(args[1]), None)))
            else:
                drops[local(args[1])] += 1
        elif tag == "AnnotationAssertion" and len(args) == 3:
            prop, subject_el, value = args
            if local(subject_el) == "AbbreviatedIRI":
                prefix, _, name = (subject_el.text or "").strip().partition(":")
                subject = ("iri", prefixes.get(prefix, "") + name, None)
            elif local(subject_el) == "IRI":
                subject = ("iri", _resolve(base, subject_el.text or ""), None)
            else:
                drops[tag] += 1
                continue
            if local(value) == "Literal":
                obj: Term = ("lit", value.text or "", value.get(f"{{{XML}}}lang"))
            else:
                obj = ("iri", _resolve(base, value.text or ""), None)
            out.append((subject, iri(prop), obj))
        else:
            drops[tag] += 1
    return out, drops


def _rdflib_triples(data: bytes, fmt: Format) -> tuple[list[Triple], Counter[str]]:
    import rdflib  # noqa: PLC0415 - only the Turtle and N-Triples paths need it

    try:
        graph = rdflib.Graph().parse(data=data.decode("utf-8-sig"), format="turtle" if fmt == "turtle" else "nt")
    except Exception as exc:  # rdflib raises many unrelated types for bad syntax
        raise _invalid(f"malformed {fmt}: {type(exc).__name__}: {exc}") from exc

    def term(t: Any) -> Term:
        if isinstance(t, rdflib.URIRef):
            return ("iri", str(t), None)
        if isinstance(t, rdflib.BNode):
            return ("bnode", str(t), None)
        return ("lit", str(t), t.language if isinstance(t, rdflib.Literal) else None)

    triples = [(term(s), str(p), term(o)) for s, p, o in graph]
    return sorted(triples, key=lambda t: (t[0], t[1], (t[2][0], t[2][1], t[2][2] or ""))), Counter()


# --------------------------------------------------------------------------- extraction


def _local(iri: str) -> str:
    """The IRI fragment after `#`, else the last path segment (else the part after the last `:`)."""
    if "#" in iri:
        return iri.rsplit("#", 1)[1]
    tail = iri.rstrip("/").rsplit("/", 1)[-1]
    return tail.rsplit(":", 1)[-1] if "/" not in iri else tail


def _pick(values: list[tuple[str, str | None]]) -> str:
    for want in (lambda lang: not lang, lambda lang: lang.lower().startswith("en"), lambda lang: True):
        for text, lang in values:
            if want(lang or "") and text.strip():
                return text
    return ""


@dataclass
class _Entity:
    iri: str
    kind: str
    labels: list[tuple[str, str | None]] = field(default_factory=list)
    comments: list[tuple[str, str | None]] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    ranges: list[str] = field(default_factory=list)
    parents: list[str] = field(default_factory=list)


def _extract(triples: list[Triple], drops: Counter[str]) -> _Parsed:
    if any(p == OWL + "imports" for _, p, _ in triples):
        raise Blocked("IMPORT_HAS_IMPORTS", "the file declares owl:imports")
    types: dict[Term, list[str]] = {}
    for s, p, o in triples:
        if p == _TYPE and o[0] == "iri":
            types.setdefault(s, []).append(o[1])
    ontologies = [s for s, ts in types.items() if OWL + "Ontology" in ts and s[0] == "iri"]
    entities: dict[str, _Entity] = {}
    for s, ts in types.items():
        kind = next((_KINDS[t] for t in ts if t in _KINDS), None)
        if kind and s[0] == "iri" and s[1] not in entities:
            entities[s[1]] = _Entity(s[1], kind)
    class_iris = {iri for iri, e in entities.items() if e.kind == "class"}
    referenced = {o for _, _, o in triples if o[0] == "bnode"}

    version_info = None
    for s, p, o in triples:
        if s in ontologies:
            if p == OWL + "versionInfo" and o[0] == "lit" and version_info is None:
                version_info = o[1]
            continue
        if s[0] != "iri":
            if s not in referenced and p == _TYPE and o[0] == "iri":
                drops[_local(o[1])] += 1
            continue
        if p == _TYPE:
            if o[1] in _KINDS or o[0] != "iri":
                continue
            drops["individual" if o[1] in class_iris else _local(o[1])] += 1
            continue
        entity = entities.get(s[1])
        if entity is None:
            continue
        if p in (RDFS + "label", RDFS + "comment") and o[0] == "lit":
            (entity.labels if p == RDFS + "label" else entity.comments).append((o[1], o[2]))
        elif o[0] == "iri" and p in (RDFS + "domain", RDFS + "range") and entity.kind != "class":
            (entity.domains if p == RDFS + "domain" else entity.ranges).append(o[1])
        elif o[0] == "iri" and p == RDFS + "subClassOf" and entity.kind == "class":
            entity.parents.append(o[1])
        elif o[0] == "bnode" and types.get(o):
            drops[_local(types[o][0])] += 1
        else:
            drops[_local(p)] += 1

    classes: list[dict[str, Any]] = []
    properties: list[dict[str, Any]] = []
    missing: list[str] = []
    for entity in entities.values():
        name = _local(entity.iri)
        description = _pick(entity.comments) or _pick(entity.labels)
        if not description.strip():
            missing.append(f"no_description:{name}")
            continue
        if entity.kind == "class":
            drops["subClassOf"] += max(0, len(entity.parents) - 1)
            parent = _local(entity.parents[0]) if entity.parents else None
            classes.append({"name": name, "description": description, "parent": parent})
        else:
            drops["domain"] += max(0, len(entity.domains) - 1)
            drops["range"] += max(0, len(entity.ranges) - 1)
            properties.append({
                "name": name, "kind": entity.kind, "description": description,
                "domain": _local(entity.domains[0]) if entity.domains else "",
                "range": _local(entity.ranges[0]) if entity.ranges else "",
            })
    warnings = [f"dropped_construct:{kind}:{n}" for kind, n in sorted(drops.items()) if n > 0] + missing
    base_iri = None
    if ontologies:
        iri = ontologies[0][1]
        base_iri = iri if iri.endswith(("#", "/")) else iri + "#"
    return _Parsed({"classes": classes, "properties": properties}, warnings, base_iri, version_info)
