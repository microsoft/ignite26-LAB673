"""Restore the Cocoarynth lab indexes and their inline-ontology knowledge sources.

The bundle holds three index snapshots. The three document-group indexes used in Part 1
(production, sales, policies) are split from the chunk snapshot by its domain field, so they
share its passages, chunk IDs and embeddings.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import re
import struct
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit
from uuid import uuid4
from xml.etree import ElementTree as ET

if TYPE_CHECKING:
    from azure.search.documents import SearchClient
    from azure.search.documents.indexes import SearchIndexClient


BUNDLE = Path(__file__).resolve().parents[1] / "data" / "graph-data"
# Part 1 document groups, each made of one or more of the chunk snapshot's domain values
DOCUMENT_GROUPS = {
    "production": ("origins", "quality"),
    "sales": ("logistics-retail",),
    "policies": ("policies",),
}
SDK_VERSION = "12.1.0a20261027002"
CLIENT_OPTIONS = {
    "retry_total": 0,
    "permit_redirects": False,
    "connection_timeout": 15,
    "read_timeout": 60,
}
GRAPH_CASES = (
    (
        "batch to bean lot",
        "MATCH (b:`Batch`)-[:`madeFrom`]->(l:`BeanLot`) "
        "WHERE b.id = 'urn:cocoarynth:Batch:EC26-0811' RETURN DISTINCT l.id AS answer LIMIT 20",
        {"urn:cocoarynth:BeanLot:EC26-L07"},
    ),
    (
        "complaint to depot storage",
        "MATCH (c:`Case`)-[:`concernsShipment`]->(:`Shipment`)"
        "-[:`hasDepotStop`]->(:`DepotStop`)-[:`storedAt`]->(s:`Site`) "
        "WHERE c.id = 'urn:cocoarynth:Case:CASE-2607-18' RETURN DISTINCT s.id AS answer LIMIT 20",
        {"urn:cocoarynth:Site:overflow-bay-4"},
    ),
    (
        "complaint to contributing farms",
        "MATCH (c:`Case`)-[:`concernsBatch`]->(:`Batch`)"
        "-[:`madeFrom`]->(:`BeanLot`)<-[:`contributedTo`]-(f:`Farm`) "
        "WHERE c.id = 'urn:cocoarynth:Case:CASE-2609-14' RETURN DISTINCT f.id AS answer LIMIT 20",
        {"urn:cocoarynth:Farm:el-cedro", "urn:cocoarynth:Farm:las-brisas"},
    ),
)


@dataclass
class Snapshot:
    original_name: str
    name: str
    key: str
    definition: dict[str, Any]
    records: list[dict[str, Any]]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def assert_subset(expected: Any, actual: Any, path: str) -> None:
    if isinstance(expected, dict):
        require(isinstance(actual, dict), f"{path}: expected an object.")
        for key, value in expected.items():
            require(key in actual, f"{path}.{key}: missing from the service response.")
            assert_subset(value, actual[key], f"{path}.{key}")
    elif isinstance(expected, list):
        require(isinstance(actual, list) and len(expected) == len(actual),
                f"{path}: collection length differs.")
        for number, (left, right) in enumerate(zip(expected, actual)):
            assert_subset(left, right, f"{path}[{number}]")
    else:
        require(expected == actual, f"{path}: value differs.")


def normalized(field: dict[str, Any], value: Any) -> Any:
    kind = field["type"]
    if kind == "Collection(Edm.String)":
        require(value is None or isinstance(value, list) and all(isinstance(item, str) for item in value),
                f"{field['name']}: expected a string collection.")
        return tuple(value or [])
    if kind == "Collection(Edm.Single)":
        if value is None:
            return ()
        require(isinstance(value, list), f"{field['name']}: expected a vector collection.")
        require(not value or len(value) == field["dimensions"],
                f"{field['name']}: vector dimensions differ.")
        require(all(isinstance(item, (int, float)) and not isinstance(item, bool)
                    and math.isfinite(item) and abs(item) <= 3.4028234663852886e38
                    for item in value), f"{field['name']}: invalid float32 component.")
        return tuple(struct.pack("<f", item) for item in value)
    if value is None:
        return None
    if kind == "Edm.DateTimeOffset":
        instant = value if isinstance(value, datetime) else datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
        require(instant.tzinfo is not None, f"{field['name']}: timezone is missing.")
        return instant.astimezone(timezone.utc)
    if kind == "Edm.String":
        require(isinstance(value, str), f"{field['name']}: expected a string.")
    elif kind == "Edm.Boolean":
        require(isinstance(value, bool), f"{field['name']}: expected a Boolean.")
    elif kind in ("Edm.Int32", "Edm.Int64"):
        bits = 32 if kind == "Edm.Int32" else 64
        require(isinstance(value, int) and not isinstance(value, bool)
                and -(2 ** (bits - 1)) <= value < 2 ** (bits - 1),
                f"{field['name']}: integer is outside its schema range.")
    elif kind == "Edm.Double":
        require(isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value), f"{field['name']}: invalid double.")
    else:
        raise RuntimeError(f"Unsupported snapshot field type: {kind}")
    return value


def read_ontology(path: Path) -> dict[str, Any]:
    namespaces = {
        "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
        "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
        "owl": "http://www.w3.org/2002/07/owl#",
        "xsd": "http://www.w3.org/2001/XMLSchema#",
        "evidence": "urn:cocoarynth:passage:",
    }
    rdf, rdfs, owl = (namespaces[name] for name in ("rdf", "rdfs", "owl"))
    root = ET.parse(path).getroot()
    require(root.tag == f"{{{rdf}}}RDF", f"{path.name}: expected RDF/XML OWL.")
    headers = root.findall(f"{{{owl}}}Ontology")
    require(len(headers) == 1, f"{path.name}: expected one ontology declaration.")
    namespace = headers[0].get(f"{{{rdf}}}about", "")
    require(namespace.endswith("#"), f"{path.name}: ontology IRI must end in #.")
    namespaces["schema"] = namespace

    def curie(iri: str) -> str:
        for prefix, base in namespaces.items():
            if iri.startswith(base):
                return prefix + ":" + iri[len(base):]
        require(iri.startswith(("https://", "http://")), f"{path.name}: unsupported IRI {iri}.")
        return iri

    allowed = {f"{{{owl}}}{name}" for name in ("Ontology", "Class", "ObjectProperty", "DatatypeProperty")}
    terms = []
    for node in root:
        require(node.tag in allowed, f"{path.name}: only flat named OWL declarations are supported.")
        iri = node.get(f"{{{rdf}}}about")
        require(bool(iri), f"{path.name}: an OWL declaration has no rdf:about.")
        term: dict[str, Any] = {"@id": curie(iri), "@type": "owl:" + node.tag.split("}", 1)[1]}
        for child in node:
            require(child.tag in {f"{{{rdfs}}}{name}" for name in
                                  ("label", "comment", "domain", "range", "seeAlso")},
                    f"{path.name}: unsupported OWL construct {child.tag}.")
            key = "rdfs:" + child.tag.split("}", 1)[1]
            resource = child.get(f"{{{rdf}}}resource")
            value = {"@id": curie(resource)} if resource else child.text
            require(value is not None, f"{path.name}: empty ontology annotation.")
            if key == "rdfs:seeAlso":
                term.setdefault(key, []).append(value)
            else:
                require(key not in term, f"{path.name}: multiple {key} values are unsupported.")
                term[key] = value
        terms.append(term)
    classes = {term["@id"] for term in terms if term["@type"] == "owl:Class"}
    require(bool(classes) and len({term["@id"] for term in terms}) == len(terms),
            f"{path.name}: empty or duplicate ontology declarations.")
    for term in terms:
        if term["@type"] in ("owl:ObjectProperty", "owl:DatatypeProperty"):
            domain = term.get("rdfs:domain", {}).get("@id")
            range_ = term.get("rdfs:range", {}).get("@id")
            require(domain in classes, f"{path.name}: undeclared property domain.")
            require(range_ in classes if term["@type"] == "owl:ObjectProperty"
                    else range_ in {f"xsd:{name}" for name in
                                    ("string", "double", "decimal", "integer", "boolean", "date", "dateTime")},
                    f"{path.name}: invalid property range.")
    document = {"@context": namespaces, "@graph": terms}
    require(len(terms) <= 512 and len(json.dumps(document)) <= 131072,
            f"{path.name}: ontology exceeds the private-preview limits.")
    return document


def load_bundle(prefix: str, owner: str | None) -> tuple[dict[str, Any], list[Snapshot]]:
    manifest = json.loads((BUNDLE / "manifest.json").read_text(encoding="utf-8"))
    require(manifest["format"] == "cocoarynth-three-index-v1", "Unsupported bundle format.")
    require({entry["index"] for entry in manifest["restore"]["order"]}
            == {"cocoarynth-chunks", "cocoarynth-topics", "cocoarynth-graph"}
            and len(manifest["restore"]["order"]) == 3, "The lab requires exactly three indexes.")
    inputs = {entry[key] for entry in manifest["restore"]["order"]
              for key in ("definition", "records")}
    inputs.update(manifest["ontologies"].values())
    inputs.add(manifest["provenance"])
    artifacts = {entry["path"]: entry for entry in manifest["artifacts"]}
    require(len(artifacts) == len(manifest["artifacts"]) and inputs == set(artifacts),
            "The restore inputs and checksum inventory differ.")
    payloads: dict[str, bytes] = {}
    for name, metadata in artifacts.items():
        require(Path(name).name == name, "Snapshot paths must be local filenames.")
        payload = (BUNDLE / name).read_bytes().replace(b"\r\n", b"\n")
        require(len(payload) == metadata["bytes"]
                and hashlib.sha256(payload).hexdigest() == metadata["sha256"],
                f"Snapshot checksum or byte count differs: {name}")
        payloads[name] = payload

    names = {entry["index"]: f"{prefix}-{entry['index']}" if prefix else entry["index"]
             for entry in manifest["restore"]["order"]}
    require(len(names) == len(manifest["restore"]["order"]), "Duplicate index names.")
    snapshots = []
    for entry in manifest["restore"]["order"]:
        original = entry["index"]
        name = names[original]
        require(len(name) <= 128 and re.fullmatch(r"[a-z0-9][a-z0-9_-]+", name) is not None,
                f"Invalid destination index name: {name}")
        definition = json.loads(payloads[entry["definition"]])
        require(definition["name"] == original, f"{original}: definition name differs.")
        definition["name"] = name
        profile = definition.get("graphProfile")
        if profile and ("provenanceIndexName" in profile or original == "cocoarynth-graph"):
            require(profile.get("provenanceIndexName") in names,
                    f"{name}: unknown provenance index.")
            profile["provenanceIndexName"] = names[profile["provenanceIndexName"]]
        if owner:
            definition["description"] = (definition.get("description", "") + " " + owner).strip()
        fields = {field["name"]: field for field in definition["fields"]}
        require([field["name"] for field in fields.values() if field.get("key")] == [entry["key"]],
                f"{name}: key field differs from the manifest.")
        require(all(field.get("retrievable", True) for field in fields.values()),
                f"{name}: full readback requires retrievable fields.")
        records = [json.loads(line) for line in payloads[entry["records"]].splitlines()]
        keys = [record.get(entry["key"]) for record in records]
        require(bool(records) and all(isinstance(key, str) and key for key in keys)
                and len(keys) == len(set(keys)), f"{name}: empty or duplicate document keys.")
        for record in records:
            require(set(record) <= set(fields), f"{name}: document contains unknown fields.")
            for field in fields.values():
                normalized(field, record.get(field["name"]))
        snapshots.append(Snapshot(original, name, entry["key"], definition, records))
    topic_metadata = manifest.get("topics")
    require(isinstance(topic_metadata, dict), "The canonical topic snapshot needs separate capture metadata.")
    for key in ("physical_index", "source_index"):
        require(topic_metadata[key] in names, f"Unknown topic {key} binding.")
        topic_metadata[key] = names[topic_metadata[key]]
    require(topic_metadata["source_index"] == names["cocoarynth-chunks"],
            "The topic source must be the PDF chunk snapshot.")
    for filename in manifest["ontologies"].values():
        read_ontology(BUNDLE / filename)
    chunks = {row["chunk_id"]: row for snapshot in snapshots
              if snapshot.original_name == "cocoarynth-chunks" for row in snapshot.records}
    require(len(chunks) == 106 and len({row["blob_path"] for row in chunks.values()}) == 55
            and all(row["blob_path"].endswith(".pdf") for row in chunks.values()),
            "The chunk index must contain the 106 passages from the 55 PDFs only.")
    provenance = json.loads(payloads[manifest["provenance"]])
    require(provenance["input"] == {"passages": 106, "pdfs": 55, "generator_json_used": False},
            "The extraction ledger does not describe the PDF-only corpus.")
    business_ontology = read_ontology(BUNDLE / manifest["ontologies"]["cocoarynth-graph"])
    declarations = {term["@id"].split(":", 1)[1]: term for term in business_ontology["@graph"]
                    if term["@type"] != "owl:Ontology"}
    require(set(provenance["ontology_evidence"]) == set(declarations),
            "Every business ontology declaration needs PDF evidence in the provenance ledger.")
    for name, evidence in provenance["ontology_evidence"].items():
        require(bool(evidence), "An ontology declaration has no source evidence.")
        expected_links = {"evidence:" + entry["passage_iri"].removeprefix(
            business_ontology["@context"]["evidence"]) for entry in evidence}
        require({link["@id"] for link in declarations[name].get("rdfs:seeAlso", [])} == expected_links,
                f"{name}: OWL evidence links differ from the provenance ledger.")
        for entry in evidence:
            source = chunks.get(entry["chunk_id"])
            require(source is not None and entry["pdf"] == source["blob_path"]
                    and bool(entry["quote"]) and entry["quote"] in source["chunk"],
                    "Ontology evidence does not resolve to a verbatim PDF passage.")
    for snapshot in snapshots:
        if not snapshot.definition.get("graphProfile"):
            continue
        ontology = read_ontology(BUNDLE / manifest["ontologies"][snapshot.original_name])
        properties = {}
        for term in ontology["@graph"]:
            if term["@type"] in ("owl:ObjectProperty", "owl:DatatypeProperty"):
                name = term["@id"].split(":", 1)[1]
                predicate = "prop:" + name if term["@type"] == "owl:DatatypeProperty" else name
                properties[predicate] = (
                    term["rdfs:domain"]["@id"].split(":", 1)[1],
                    term["rdfs:range"]["@id"].replace("schema:", ""),
                )
        for record in snapshot.records:
            require(properties.get(record["predicate"]) ==
                    (record["subject_type"], record["object_type"]),
                    f"{snapshot.name}/{record['id']}: triple violates the OWL domain/range.")
            if snapshot.original_name == "cocoarynth-graph":
                require(bool(record.get("chunk_id")), f"{snapshot.name}/{record['id']}: PDF provenance is missing.")
            if record.get("chunk_id"):
                source = chunks.get(record["chunk_id"])
                parent_field = snapshot.definition["graphProfile"]["fields"]["sourceParentIdField"]
                require(source is not None and record.get(parent_field) == source["parent_id"],
                        f"{snapshot.name}/{record['id']}: provenance does not resolve to a PDF passage.")
                if snapshot.original_name == "cocoarynth-graph":
                    quotes = record.get("evidence_quotes")
                    require(bool(quotes) and all(quote and quote in source["chunk"] for quote in quotes),
                            f"{snapshot.name}/{record['id']}: evidence quotations are not verbatim.")
    topics = next(snapshot for snapshot in snapshots if snapshot.original_name == "cocoarynth-topics")
    validate_topics(topics, topic_metadata, len(chunks))
    return manifest, snapshots + domain_snapshots(snapshots, prefix)


def validate_topics(snapshot: Snapshot, metadata: dict[str, Any], source_count: int) -> None:
    """Check the canonical release contract, not the retired kind/membership sidecar."""
    fields = {field["name"]: field for field in snapshot.definition["fields"]}
    require(set(fields) == {
        "id", "subject", "subject_type", "subject_id", "subject_id_display_name", "predicate",
        "object", "object_type", "object_id", "object_id_display_name", "object_string",
        "graph_name", "object_double", "object_bool", "object_datetime", "edge_confidence",
        "s_confidence", "p_confidence", "o_confidence", "chunk_id", "parent_id", "object_vector",
    }, "The topic index must use the canonical TopicGraph release fields only.")
    require(metadata["schema_version"] == "topicgraph-release-v1"
            and metadata["physical_index"] == snapshot.name,
            "The topic snapshot contract or physical binding differs.")
    require(fields["object_vector"]["dimensions"] == metadata["dimension"] == 3072
            and fields["object_vector"].get("retrievable") is True,
            "Topic leaf centroids must be retrievable 3,072-dimensional object_vector values.")
    profile = snapshot.definition["graphProfile"]
    require(profile["kind"] == "edgeList" and profile["fields"]["factIdField"] == "id"
            and "provenanceIndexName" not in profile,
            "Canonical topic facts have no chunk-membership provenance index.")
    clustered = metadata["clustered_source_document_count"]
    require(isinstance(clustered, int) and not isinstance(clustered, bool) and clustered > 0
            and metadata["source_document_count"] == source_count
            and clustered + metadata["unassigned_source_document_count"] == source_count
            and math.isclose(metadata["node_coverage"], clustered / source_count),
            "Topic capture coverage differs from the PDF chunk snapshot.")
    values: dict[str, dict[str, Any]] = {}
    roots: set[str] = set()
    parents: dict[str, str] = {}
    centroids: dict[str, list[float]] = {}
    properties = {"prop:title", "prop:description", "prop:level", "prop:proportion", "prop:parentProportion"}
    for row in snapshot.records:
        subject, predicate, target = row["subject_id"], row["predicate"], row.get("object_id")
        require(row["graph_name"] == metadata["graph_name"] == "topicgraph-community"
                and not row.get("chunk_id") and not row.get("parent_id"),
                "Topic facts must not claim per-chunk membership or PDF provenance.")
        if predicate == "HasRootCommunity":
            require(subject == "communitygraph:topicgraph-community"
                    and row["subject_type"] == "CommunityGraph" and target not in roots,
                    "A topic root edge is invalid or duplicated.")
            roots.add(target)
            continue
        require(subject.startswith("community:") and row["subject_type"] == "Community",
                "Topic subjects must use the stored community: identity.")
        topic = values.setdefault(subject, {})
        if predicate == "HasSubCommunity":
            require(target not in parents, "A topic has more than one parent.")
            parents[target] = subject
        elif predicate == "HasCentroidVector":
            require(subject not in centroids and len(row.get("object_vector") or []) == metadata["dimension"]
                    and any(row["object_vector"]), "A leaf centroid is missing, zero, or duplicated.")
            centroids[subject] = row["object_vector"]
        else:
            require(predicate in properties and predicate not in topic,
                    f"{subject}: unexpected or repeated topic property {predicate}.")
            topic[predicate] = row.get("object_string") if predicate in {
                "prop:title", "prop:description"
            } else row.get("object_double")
    ids = set(values)
    require(ids and roots == ids - set(parents) and set(parents) <= ids
            and set(parents.values()) <= ids and not roots & set(parents),
            "Topic root and child edges must form one complete forest.")
    require(set(centroids) == ids - set(parents.values()),
            "Only leaf topics, including terminal roots, must have stored centroids.")
    for cid, topic in values.items():
        require(set(topic) == properties and bool(topic["prop:title"]) and bool(topic["prop:description"]),
                f"{cid}: a canonical topic property is missing.")
        level, proportion = topic["prop:level"], topic["prop:proportion"]
        require(isinstance(level, (int, float)) and level >= 0 and level == int(level)
                and isinstance(proportion, (int, float)) and 0 < proportion <= 1,
                f"{cid}: invalid topic level or proportion.")
    level_counts: dict[str, int] = {}
    for cid, topic in values.items():
        level, proportion = topic["prop:level"], topic["prop:proportion"]
        if cid in parents:
            parent = values[parents[cid]]
            require(level == parent["prop:level"] + 1
                    and math.isclose(topic["prop:parentProportion"], proportion / parent["prop:proportion"]),
                    f"{cid}: topic depth or parent proportion differs.")
        else:
            require(level == 0 and math.isclose(topic["prop:parentProportion"], proportion),
                    f"{cid}: roots must be level zero with their global proportion.")
        children = [child for child, parent in parents.items() if parent == cid]
        if children:
            require(math.isclose(sum(values[child]["prop:proportion"] for child in children), proportion),
                    f"{cid}: child proportions do not cover the parent.")
        key = str(int(level))
        level_counts[key] = level_counts.get(key, 0) + round(proportion * clustered)
    require(math.isclose(sum(values[root]["prop:proportion"] for root in roots), 1)
            and len(ids) == metadata["topic_count"] and len(centroids) == metadata["terminal_topic_count"]
            and level_counts == metadata["assigned_chunks_by_level"],
            "Topic counts, proportions, or per-level capture coverage differ.")


def domain_snapshots(snapshots: list[Snapshot], prefix: str) -> list[Snapshot]:
    """Split the chunk snapshot into one index per document group, for Part 1's knowledge sources."""
    chunks = next(snapshot for snapshot in snapshots if snapshot.original_name == "cocoarynth-chunks")
    domains = [domain for group in DOCUMENT_GROUPS.values() for domain in group]
    require({record["domain"] for record in chunks.records} == set(domains) and len(domains) == len(set(domains)),
            "The chunk snapshot's domains differ from the document groups.")
    result = []
    for group, group_domains in DOCUMENT_GROUPS.items():
        original = f"cocoarynth-{group}"
        name = f"{prefix}-{original}" if prefix else original
        records = [record for record in chunks.records if record["domain"] in group_domains]
        definition = json.loads(json.dumps(chunks.definition))
        definition["name"] = name
        definition["description"] = definition["description"].replace(
            "106 PDF passages", f"The {len(records)} {group} PDF passages from cocoarynth-chunks", 1)
        result.append(Snapshot(original, name, chunks.key, definition, records))
    return result


def graph_sources(manifest: dict[str, Any], snapshots: list[Snapshot],
                  owner: str | None) -> list[dict[str, Any]]:
    definitions = []
    for snapshot in snapshots:
        filename = manifest["ontologies"].get(snapshot.original_name)
        if not filename:
            continue
        fields = ["id", "subject", "predicate", "object"]
        if snapshot.original_name == "cocoarynth-topics":
            fields += ["subject_id", "object_id", "object_string", "object_double", "graph_name"]
        else:
            fields += ["chunk_id", "parent_id", "evidence_quotes"]
        definitions.append({
            "name": snapshot.name + "-knowledge-source",
            "kind": "searchIndex",
            "description": (snapshot.definition["description"] + " " + (owner or "")).strip(),
            "searchIndexParameters": {
                "searchIndexName": snapshot.name,
                "sourceDataFields": [{"name": name} for name in fields],
                **({"semanticConfigurationName": snapshot.definition["semantic"]["defaultConfiguration"]}
                   if snapshot.original_name == "cocoarynth-topics" else {}),
                "graphOntology": {"kind": "inline", "name": Path(filename).stem,
                                  "value": json.dumps(read_ontology(BUNDLE / filename),
                                                      ensure_ascii=False, separators=(",", ":"))},
            },
        })
    require(len(definitions) == 2, "Both the business graph and sitemap need inline-ontology knowledge sources.")
    return definitions


def batches(records: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    result: list[list[dict[str, Any]]] = []
    batch: list[dict[str, Any]] = []
    size = 16
    for record in records:
        encoded_size = len(json.dumps({"@search.action": "upload", **record}).encode("utf-8")) + 2
        require(encoded_size < 15 * 1024 * 1024, "A document exceeds the upload byte limit.")
        if batch and (len(batch) == 1000 or size + encoded_size >= 15 * 1024 * 1024):
            result.append(batch)
            batch, size = [], 16
        batch.append(record)
        size += encoded_size
    if batch:
        result.append(batch)
    return result


def verify_index(indexes: SearchIndexClient, client: SearchClient, snapshot: Snapshot) -> None:
    from azure.search.documents.models import VectorizedQuery

    assert_subset(snapshot.definition, indexes.get_index(snapshot.name).as_dict(), snapshot.name)
    deadline = time.monotonic() + 60
    while True:
        count = client.get_document_count()
        if count == len(snapshot.records):
            break
        require(count < len(snapshot.records) and time.monotonic() < deadline,
                f"{snapshot.name}: expected {len(snapshot.records)} documents; got {count}.")
        time.sleep(2)
    fields = snapshot.definition["fields"]
    expected = {record[snapshot.key]: record for record in snapshot.records}
    seen: set[str] = set()
    for record in client.search(search_text="*", select=[field["name"] for field in fields]):
        key = record[snapshot.key]
        require(key in expected and key not in seen, f"{snapshot.name}: unexpected/duplicate key.")
        seen.add(key)
        for field in fields:
            require(normalized(field, expected[key].get(field["name"]))
                    == normalized(field, record.get(field["name"])),
                    f"{snapshot.name}/{key}/{field['name']}: document readback differs.")
    require(seen == set(expected), f"{snapshot.name}: document enumeration is incomplete.")
    for field in fields:
        if not field.get("dimensions"):
            continue
        sample = next(record for record in reversed(snapshot.records) if record.get(field["name"]))
        query = VectorizedQuery(vector=sample[field["name"]], fields=field["name"],
                                k_nearest_neighbors=1, exhaustive=True)
        same_vector = {record[snapshot.key] for record in snapshot.records
                       if normalized(field, record.get(field["name"]))
                       == normalized(field, sample[field["name"]])}
        hits = list(client.search(vector_queries=[query], select=[snapshot.key], top=1))
        require(len(hits) == 1 and hits[0][snapshot.key] in same_vector,
                f"{snapshot.name}/{field['name']}: known-vector lookup failed.")
    print(f"Verified {snapshot.name}: {len(seen)} documents.", flush=True)


def preview_json(client: SearchIndexClient, endpoint: str, path: str, api: str,
                 body: dict[str, Any], expected_status: int) -> dict[str, Any]:
    from azure.core.rest import HttpRequest

    request = HttpRequest("POST", f"{endpoint}/{path}?api-version={api}", json=body)
    with client.send_request(request) as response:
        response.raise_for_status()
        require(response.status_code == expected_status,
                f"{path}: unexpected HTTP {response.status_code}.")
        return response.json()


def verify_graph(indexes: SearchIndexClient, endpoint: str, api: str,
                 snapshots: list[Snapshot]) -> None:
    by_name = {snapshot.original_name: snapshot for snapshot in snapshots}
    graph = by_name["cocoarynth-graph"]
    assertions = {record["id"]: record for record in graph.records}
    sources = {record["chunk_id"] for record in by_name["cocoarynth-chunks"].records}
    for name, gql, expected in GRAPH_CASES:
        result = preview_json(indexes, endpoint, f"indexes('{graph.name}')/docs/search.graph", api,
                              {"gql": gql, "includeDiagnostics": True, "includeStatistics": True,
                               "provenance": {"kind": "ids"}}, 200)
        require(not any(item.get("severity", "").lower() == "error"
                        for item in result.get("@search.graphDiagnostics", [])),
                f"{name}: native graph execution reported errors.")
        require(result.get("@search.graphStats", {}).get("executionMode") == "execute",
                f"{name}: native graph execution was not confirmed.")
        rows = result.get("value", [])
        require(len(rows) == len(expected) and {row.get("answer") for row in rows} == expected,
                f"{name}: native graph answers differ.")
        for row in rows:
            evidence = row.get("@search.graphProvenance", {}).get("evidence", [])
            require(bool(evidence), f"{name}: graph provenance is missing.")
            for item in evidence:
                original = assertions.get(item.get("edgeId"))
                require(original is not None and item.get("chunkId") == original["chunk_id"]
                        and item.get("parentId") == original["parent_id"]
                        and item["chunkId"] in sources, f"{name}: provenance binding differs.")
        print(f"Verified native graph query: {name}.", flush=True)
    topics = by_name["cocoarynth-topics"]
    for predicate, subject_type in (("HasRootCommunity", "CommunityGraph"), ("HasSubCommunity", "Community")):
        expected_links = {(row["subject_id"], row["object_id"])
                          for row in topics.records if row["predicate"] == predicate}
        result = preview_json(indexes, endpoint, f"indexes('{topics.name}')/docs/search.graph", api,
                              {"gql": f"MATCH (p:`{subject_type}`)-[:`{predicate}`]->(c:`Community`) "
                                      "RETURN p.id AS parent, c.id AS child LIMIT 100",
                               "includeStatistics": True}, 200)
        require(result.get("@search.graphStats", {}).get("executionMode") == "execute"
                and {(row["parent"], row["child"]) for row in result.get("value", [])} == expected_links
                and len(result.get("value", [])) == len(expected_links),
                f"The topic index did not execute the expected {predicate} GQL traversal.")
    print("Verified native sitemap GQL over the topic index.", flush=True)


def require_absent(getter: Callable[[str], object], name: str) -> None:
    from azure.core.exceptions import ResourceNotFoundError

    try:
        getter(name)
    except ResourceNotFoundError:
        return
    raise RuntimeError(f"Destination already exists; use --verify-only or a new prefix: {name}")


def cleanup(indexes: SearchIndexClient, sources: SearchIndexClient,
            intents: list[tuple[str, str]], owner: str) -> None:
    from azure.core import MatchConditions
    from azure.core.exceptions import AzureError, ResourceNotFoundError

    failures = []
    for kind, name in reversed(intents):
        getter = indexes.get_index if kind == "index" else sources.get_knowledge_source
        deleter = indexes.delete_index if kind == "index" else sources.delete_knowledge_source
        try:
            try:
                resource = getter(name)
            except ResourceNotFoundError:
                continue
            require(owner in (resource.get("description") or ""),
                    f"Refusing to delete {name}: this run's ownership marker is absent.")
            require(bool(resource.get("@odata.etag")), f"{name}: cleanup ETag is absent.")
            deleter(resource, match_condition=MatchConditions.IfNotModified)
            require_absent(getter, name)
            print(f"Removed temporary {kind}: {name}.", flush=True)
        except (AzureError, RuntimeError) as error:
            failures.append(f"{name}: {error}")
    require(not failures, "Temporary-resource cleanup failed: " + "; ".join(failures))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--validate-only", action="store_true", help="Check the bundle without Azure calls.")
    mode.add_argument("--verify-only", action="store_true", help="Read and test existing destinations.")
    mode.add_argument("--ensure", action="store_true",
                      help="Create missing resources and verify, without replacing, existing ones.")
    parser.add_argument("--endpoint", help="Explicit HTTPS Search endpoint; no .env file is loaded.")
    parser.add_argument("--embedding-endpoint",
                        help="Foundry endpoint for query vectorizers; defaults to AZURE_OPENAI_ENDPOINT.")
    parser.add_argument("--embedding-deployment",
                        help="Existing text-embedding-3-large deployment; defaults to AZURE_OPENAI_EMBEDDING_DEPLOYMENT.")
    parser.add_argument("--prefix", default="", help="Optional destination prefix, without a trailing dash.")
    parser.add_argument("--graph-ks", action="store_true",
                        help="Compatibility flag; both inline-ontology knowledge sources are always included.")
    parser.add_argument("--cleanup", action="store_true",
                        help="Remove only resources created by this run; requires a prefix.")
    args = parser.parse_args()
    if args.prefix and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", args.prefix) is None:
        parser.error("--prefix must contain lowercase letters, digits and single internal dashes.")
    if args.cleanup and (not args.prefix or args.validate_only or args.verify_only or args.ensure):
        parser.error("--cleanup requires a new prefixed restore, not validation, verification, or --ensure.")
    if not args.validate_only:
        url = urlsplit(args.endpoint or "")
        if (url.scheme != "https" or not url.hostname or url.username or url.password
                or url.path not in ("", "/") or url.query or url.fragment):
            parser.error("--endpoint must be an explicit HTTPS Search service root.")
    owner = f"[lab673-restore:{uuid4().hex}]" if args.cleanup else None
    manifest, snapshots = load_bundle(args.prefix, owner)
    uploads = {snapshot.name: batches(snapshot.records) for snapshot in snapshots}
    definitions = graph_sources(manifest, snapshots, owner)
    documents = sum(len(snapshot.records) for snapshot in snapshots)
    vectors = sum(bool(record.get(field["name"])) for snapshot in snapshots
                  for field in snapshot.definition["fields"] if field.get("dimensions")
                  for record in snapshot.records)
    summary = f"{len(snapshots)} indexes, {documents} documents, {vectors} stored vectors"
    if args.validate_only:
        print(f"Validated {summary}; no dependencies or Azure access required.")
        print("Validated both inline-ontology knowledge sources from the checked-in OWL files.")
        return
    embedding_url = urlsplit(args.embedding_endpoint or os.environ.get("AZURE_OPENAI_ENDPOINT", ""))
    require(embedding_url.scheme == "https" and bool(embedding_url.hostname)
            and not embedding_url.username and not embedding_url.password
            and embedding_url.path.rstrip("/") in ("", "/openai/v1")
            and not embedding_url.query and not embedding_url.fragment,
            "Set --embedding-endpoint or AZURE_OPENAI_ENDPOINT to the intended Foundry HTTPS endpoint.")
    embedding_endpoint = f"{embedding_url.scheme}://{embedding_url.netloc}"
    deployment = args.embedding_deployment or os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")
    for snapshot in snapshots:
        for vectorizer in snapshot.definition.get("vectorSearch", {}).get("vectorizers", []):
            parameters = vectorizer["azureOpenAIParameters"]
            parameters["resourceUri"] = embedding_endpoint
            if deployment:
                parameters["deploymentId"] = deployment
    from azure.core.credentials import AzureKeyCredential
    from azure.core.exceptions import AzureError, ResourceNotFoundError
    from azure.search.documents import SearchClient
    from azure.search.documents.indexes import SearchIndexClient
    from azure.search.documents.indexes.models import SearchIndex

    require(importlib.metadata.version("azure-search-documents") == SDK_VERSION,
            f"Use azure-search-documents=={SDK_VERSION} from infra/requirements.txt.")
    for snapshot in snapshots:
        assert_subset(snapshot.definition,
                      SearchIndex(snapshot.definition).as_dict(exclude_readonly=True), snapshot.name)
    key = os.environ.get("AZURE_SEARCH_ADMIN_KEY")
    if not key:
        raise RuntimeError("Set AZURE_SEARCH_ADMIN_KEY for the explicit destination; no writes were sent.")
    endpoint = args.endpoint.rstrip("/")
    credential = AzureKeyCredential(key)
    api = manifest["restore"]["api_version"]
    intents: list[tuple[str, str]] = []
    try:
        with SearchIndexClient(endpoint, credential, api_version=api, **CLIENT_OPTIONS) as indexes, \
                SearchIndexClient(endpoint, credential, api_version=api, **CLIENT_OPTIONS) as sources:
            existing_indexes: set[str] = set()
            for snapshot in snapshots:
                try:
                    stored = indexes.get_index(snapshot.name)
                except ResourceNotFoundError:
                    require(not args.verify_only, f"Index is missing: {snapshot.name}")
                    continue
                require(args.ensure or args.verify_only,
                        f"Destination already exists; use --ensure, --verify-only or a new prefix: {snapshot.name}")
                assert_subset(snapshot.definition, stored.as_dict(), snapshot.name)
                with SearchClient(endpoint, snapshot.name, credential, api_version=api,
                                  **CLIENT_OPTIONS) as client:
                    verify_index(indexes, client, snapshot)
                existing_indexes.add(snapshot.name)
            existing_sources: set[str] = set()
            for definition in definitions:
                try:
                    stored_source = sources.get_knowledge_source(definition["name"])
                except ResourceNotFoundError:
                    require(not args.verify_only, f"Knowledge source is missing: {definition['name']}")
                    continue
                require(args.ensure or args.verify_only,
                        f"Destination already exists; use --ensure, --verify-only or a new prefix: {definition['name']}")
                assert_subset(definition, stored_source.as_dict(), definition["name"])
                existing_sources.add(definition["name"])
            try:
                for snapshot in snapshots:
                    if snapshot.name in existing_indexes:
                        continue
                    intents.append(("index", snapshot.name))
                    indexes.create_index(SearchIndex(snapshot.definition))
                    with SearchClient(endpoint, snapshot.name, credential, api_version=api,
                                      **CLIENT_OPTIONS) as client:
                        for batch in uploads[snapshot.name]:
                            results = client.upload_documents(batch)
                            require(len(results) == len(batch)
                                    and {item.key for item in results}
                                    == {record[snapshot.key] for record in batch},
                                    f"{snapshot.name}: upload acknowledgments are incomplete.")
                            failures = [item for item in results if not item.succeeded]
                            require(not failures, f"{snapshot.name}: upload failed: " + "; ".join(
                                f"{item.key}: {item.error_message}" for item in failures
                            ))
                        verify_index(indexes, client, snapshot)
                verify_graph(indexes, endpoint, api, snapshots)
                for definition in definitions:
                    if definition["name"] not in existing_sources:
                        intents.append(("source", definition["name"]))
                        preview_json(sources, endpoint, "knowledgesources", api, definition, 201)
                    assert_subset(definition, sources.get_knowledge_source(definition["name"]).as_dict(),
                                  definition["name"])
                    print(f"Verified inline-ontology knowledge source: {definition['name']}.", flush=True)
            finally:
                if owner is not None:
                    cleanup(indexes, sources, intents, owner)
    except AzureError as error:
        raise RuntimeError(str(error)) from None
    print(f"Verified {summary}; SDK {SDK_VERSION}; no indexer or model calls.")


if __name__ == "__main__":
    try:
        main()
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        secret = os.environ.get("AZURE_SEARCH_ADMIN_KEY")
        cause: BaseException | None = error
        while cause is not None:
            message = str(cause)
            if secret:
                message = message.replace(secret, "<REDACTED>")
            print(f"Error: {message}", file=sys.stderr)
            cause = cause.__cause__ or (None if cause.__suppress_context__ else cause.__context__)
        sys.exit(1)
