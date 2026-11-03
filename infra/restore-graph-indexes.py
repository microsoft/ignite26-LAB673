"""Restore and verify the committed Cocoarynth graph snapshots without an indexer."""

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
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from azure.core import MatchConditions
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import AzureError, ResourceNotFoundError
from azure.core.rest import HttpRequest
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import SearchIndex
from azure.search.documents.models import VectorizedQuery


BUNDLE = Path(__file__).resolve().parents[1] / "data" / "graph-data"
SDK_VERSION = "12.1.0a20260811002"
GRAPH_KS_API = "2026-11-01-preview"
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
        "WHERE b.id = 'urn:cocoarynth:Batch:PE26-0902' RETURN l.id AS answer LIMIT 20",
        {"urn:cocoarynth:BeanLot:PE25-L11"},
    ),
    (
        "complaint to overflow bay",
        "MATCH (c:`Case`)-[:`concernsShipment`]->(:`Shipment`)"
        "-[:`hasDepotStop`]->(:`DepotStop`)-[:`storedAt`]->(s:`Site`) "
        "WHERE c.id = 'urn:cocoarynth:Case:CASE-2607-18' RETURN s.id AS answer LIMIT 20",
        {"urn:cocoarynth:Site:riverbend-bay-4"},
    ),
    (
        "complaint to contributing farms",
        "MATCH (c:`Case`)-[:`concernsBatch`]->(:`Batch`)"
        "-[:`madeFrom`]->(:`BeanLot`)<-[:`contributedTo`]-(f:`Farm`) "
        "WHERE c.id = 'urn:cocoarynth:Case:CASE-2609-14' RETURN f.id AS answer LIMIT 20",
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


def load_bundle(prefix: str, owner: str | None) -> tuple[dict[str, Any], list[Snapshot]]:
    manifest = json.loads((BUNDLE / "manifest.json").read_text(encoding="utf-8"))
    require(manifest["format"] == "cocoarynth-offline-graph-v2", "Unsupported bundle format.")
    inputs = {entry[key] for entry in manifest["restore"]["order"]
              for key in ("definition", "records")}
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
        if prefix and entry["definition"] == "cocoarynth-topics-index.json":
            sidecars = [record for record in records if record["kind"] == "manifest"]
            require(len(sidecars) == 1, "Expected exactly one topic-sidecar manifest.")
            binding = json.loads(sidecars[0]["payload"])
            for key in ("physical_index", "source_index"):
                require(binding[key] in names, f"Unknown sidecar {key} binding.")
                binding[key] = names[binding[key]]
            sidecars[0]["payload"] = json.dumps(binding, sort_keys=True, separators=(",", ":"))
        # Positional REST dictionaries retain graphProfile, which this SDK does not model.
        assert_subset(definition, SearchIndex(definition).as_dict(exclude_readonly=True), name)
        snapshots.append(Snapshot(original, name, entry["key"], definition, records))
    return manifest, snapshots


def graph_source(manifest: dict[str, Any], snapshots: list[Snapshot],
                 owner: str | None) -> dict[str, Any]:
    by_name = {snapshot.original_name: snapshot for snapshot in snapshots}
    ontology = by_name["cocoarynth-ontology"]
    nodes: dict[str, dict[str, str]] = {}
    edges: dict[str, dict[str, str]] = {}
    for record in ontology.records:
        require(record["subject_type"] in ("NodeType", "EdgeType"),
                "The ontology contains an unsupported subject type.")
        group = nodes if record["subject_type"] == "NodeType" else edges
        properties = group.setdefault(record["subject"], {})
        require(record["predicate"] not in properties, "Duplicate ontology assertion.")
        properties[record["predicate"]] = record["object"]
    terms = []
    for name, properties in sorted(nodes.items()):
        require(set(properties) == {"rdf:type", "rdfs:comment"}
                and properties["rdf:type"] == "rdfs:Class", f"Incomplete ontology class: {name}")
        terms.append({"@id": f"coco:{name}", "@type": "owl:Class",
                      "rdfs:label": name, "rdfs:comment": properties["rdfs:comment"]})
    for name, properties in sorted(edges.items()):
        require(set(properties) == {"rdfs:domain", "rdfs:range", "rdfs:comment"}
                and properties["rdfs:domain"] in nodes and properties["rdfs:range"] in nodes,
                f"Incomplete ontology relationship: {name}")
        terms.append({"@id": f"coco:{name}", "@type": "owl:ObjectProperty",
                      "rdfs:label": name, "rdfs:comment": properties["rdfs:comment"],
                      "rdfs:domain": {"@id": "coco:" + properties["rdfs:domain"]},
                      "rdfs:range": {"@id": "coco:" + properties["rdfs:range"]}})
    inline = {"@context": {"coco": manifest["ontology_iri"],
                          "owl": "http://www.w3.org/2002/07/owl#",
                          "rdfs": "http://www.w3.org/2000/01/rdf-schema#"},
              "@graph": terms}
    return {
        "name": by_name["cocoarynth-graph"].name + "-ks",
        "kind": "searchIndex",
        "description": ("Cocoarynth business relationships. " + (owner or "")).strip(),
        "searchIndexParameters": {
            "searchIndexName": by_name["cocoarynth-graph"].name,
            "sourceDataFields": [{"name": name} for name in
                                 ("id", "subject", "predicate", "object", "chunk_id", "parent_id")],
            "graphOntology": {"kind": "inline", "name": ontology.name,
                              "value": json.dumps(inline, sort_keys=True, separators=(",", ":"))},
        },
    }


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
    sources = {record["chunk_id"] for record in by_name["cocoarynth-graph-sources"].records}
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


def require_absent(getter: Callable[[str], object], name: str) -> None:
    try:
        getter(name)
    except ResourceNotFoundError:
        return
    raise RuntimeError(f"Destination already exists; use --verify-only or a new prefix: {name}")


def cleanup(indexes: SearchIndexClient, sources: SearchIndexClient,
            intents: list[tuple[str, str]], owner: str) -> None:
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
    parser.add_argument("--endpoint", help="Explicit HTTPS Search endpoint; no .env file is loaded.")
    parser.add_argument("--prefix", default="", help="Optional destination prefix, without a trailing dash.")
    parser.add_argument("--graph-ks", action="store_true",
                        help="Also create/verify the private-preview inline-ontology Graph KS.")
    parser.add_argument("--cleanup", action="store_true",
                        help="Remove only resources created by this run; requires a prefix.")
    args = parser.parse_args()
    if args.prefix and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", args.prefix) is None:
        parser.error("--prefix must contain lowercase letters, digits and single internal dashes.")
    if args.cleanup and (not args.prefix or args.validate_only or args.verify_only):
        parser.error("--cleanup requires a prefixed restore, not a validation/read-only run.")
    if not args.validate_only:
        url = urlsplit(args.endpoint or "")
        if (url.scheme != "https" or not url.hostname or url.username or url.password
                or url.path not in ("", "/") or url.query or url.fragment):
            parser.error("--endpoint must be an explicit HTTPS Search service root.")
    require(importlib.metadata.version("azure-search-documents") == SDK_VERSION,
            f"Use azure-search-documents=={SDK_VERSION} from infra/requirements-graph.txt.")
    owner = f"[lab673-restore:{uuid4().hex}]" if args.cleanup else None
    manifest, snapshots = load_bundle(args.prefix, owner)
    uploads = {snapshot.name: batches(snapshot.records) for snapshot in snapshots}
    definition = graph_source(manifest, snapshots, owner) if args.graph_ks else None
    documents = sum(len(snapshot.records) for snapshot in snapshots)
    vectors = sum(bool(record.get(field["name"])) for snapshot in snapshots
                  for field in snapshot.definition["fields"] if field.get("dimensions")
                  for record in snapshot.records)
    summary = f"{len(snapshots)} indexes, {documents} documents, {vectors} stored vectors"
    if args.validate_only:
        print(f"Validated {summary}; SDK {SDK_VERSION}.")
        if definition:
            print("Validated inline Graph KS ontology from the committed ontology records.")
        return
    key = os.environ.get("AZURE_SEARCH_ADMIN_KEY")
    if not key:
        raise RuntimeError("Set AZURE_SEARCH_ADMIN_KEY for the explicit destination; no writes were sent.")
    endpoint = args.endpoint.rstrip("/")
    credential = AzureKeyCredential(key)
    api = manifest["restore"]["api_version"]
    intents: list[tuple[str, str]] = []
    with SearchIndexClient(endpoint, credential, api_version=api, **CLIENT_OPTIONS) as indexes, \
            SearchIndexClient(endpoint, credential, api_version=GRAPH_KS_API, **CLIENT_OPTIONS) as sources:
        if not args.verify_only:
            for snapshot in snapshots:
                require_absent(indexes.get_index, snapshot.name)
            if definition:
                require_absent(sources.get_knowledge_source, definition["name"])
        try:
            for snapshot in snapshots:
                if not args.verify_only:
                    intents.append(("index", snapshot.name))
                    indexes.create_index(SearchIndex(snapshot.definition))
                with SearchClient(endpoint=endpoint, index_name=snapshot.name, credential=credential,
                                  api_version=api, **CLIENT_OPTIONS) as client:
                    if not args.verify_only:
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
            if definition:
                if not args.verify_only:
                    intents.append(("source", definition["name"]))
                    preview_json(sources, endpoint, "knowledgesources", GRAPH_KS_API, definition, 201)
                assert_subset(definition, sources.get_knowledge_source(definition["name"]).as_dict(),
                              definition["name"])
                print(f"Verified inline-ontology Graph KS: {definition['name']}.", flush=True)
        finally:
            if owner is not None:
                cleanup(indexes, sources, intents, owner)
    print(f"Verified {summary}; SDK {SDK_VERSION}; no indexer or model calls.")


if __name__ == "__main__":
    try:
        main()
    except (AzureError, OSError, RuntimeError, ValueError) as error:
        secret = os.environ.get("AZURE_SEARCH_ADMIN_KEY")
        cause: BaseException | None = error
        while cause is not None:
            message = str(cause)
            if secret:
                message = message.replace(secret, "<REDACTED>")
            print(f"Error: {message}", file=sys.stderr)
            cause = cause.__cause__ or (None if cause.__suppress_context__ else cause.__context__)
        sys.exit(1)
