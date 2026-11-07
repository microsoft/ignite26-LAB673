"""Cocoarynth graph explorer: a local web app for browsing the ontology, graph, and topics in Foundry IQ.

Run from the repository root:
    python src/explorer/app.py
Then open http://localhost:8765
"""

import json
import os
import webbrowser
from collections import Counter
from functools import lru_cache
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from xml.etree import ElementTree as ET

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from dotenv import load_dotenv

load_dotenv(override=True)

PORT = int(os.getenv("EXPLORER_PORT", "8765"))
STATIC_DIR = Path(__file__).parent / "static"
API_VERSION = "2026-11-01-preview"
GRAPH_INDEX = "cocoarynth-graph"
ONTOLOGY_FILE = Path(__file__).resolve().parents[2] / "data" / "graph-data" / "cocoarynth.owl"
DOCUMENTS_DIR = Path(__file__).resolve().parents[2] / "data" / "cocoarynth" / "documents"
CHUNKS_INDEX = "cocoarynth-chunks"
TOPICS_INDEX = "cocoarynth-topics"

ASSERTION_FIELDS = ["id", "fact_id", "subject", "subject_type", "subject_id", "predicate", "object", "object_type", "object_id", "chunk_id", "evidence_quotes"]


@lru_cache
def client(name):
    return SearchClient(
        os.environ["AZURE_SEARCH_SERVICE_ENDPOINT"],
        name,
        AzureKeyCredential(os.environ["AZURE_SEARCH_ADMIN_KEY"]),
        api_version=API_VERSION,
    )


def odata(value):
    return "'" + value.replace("'", "''") + "'"


def get_ontology():
    ns = {
        "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
        "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
        "owl": "http://www.w3.org/2002/07/owl#",
    }
    ontology = ET.parse(ONTOLOGY_FILE).getroot()
    types = [
        {"name": node.attrib[f"{{{ns['rdf']}}}about"].rsplit("#", 1)[1],
         "comment": node.findtext("rdfs:comment", namespaces=ns)}
        for node in ontology.findall("owl:Class", ns)
    ]
    relationships = [
        {"name": node.attrib[f"{{{ns['rdf']}}}about"].rsplit("#", 1)[1],
         "domain": node.find("rdfs:domain", ns).attrib[f"{{{ns['rdf']}}}resource"].rsplit("#", 1)[1],
         "range": node.find("rdfs:range", ns).attrib[f"{{{ns['rdf']}}}resource"].rsplit("#", 1)[1],
         "comment": node.findtext("rdfs:comment", namespaces=ns)}
        for node in ontology.findall("owl:ObjectProperty", ns)
    ]
    return {
        "types": sorted(types, key=lambda row: row["name"]),
        "relationships": sorted(relationships, key=lambda row: row["name"]),
    }


def find_entities(query):
    entities = {}
    for row in client(GRAPH_INDEX).search(
        search_text=query,
        search_fields=["subject"],
        select=["subject", "subject_type", "subject_id"],
        top=50,
    ):
        entities.setdefault(row["subject_id"], {"id": row["subject_id"], "name": row["subject"], "type": row["subject_type"]})
    return list(entities.values())[:15]


def graph_view(rows):
    """Turn assertion rows into nodes, one edge per distinct fact, and deduplicated literal properties."""
    nodes, edges, properties = {}, {}, {}
    for row in rows:
        nodes.setdefault(row["subject_id"], {"id": row["subject_id"], "name": row["subject"], "type": row["subject_type"]})
        if row.get("object_id"):
            nodes.setdefault(row["object_id"], {"id": row["object_id"], "name": row["object"], "type": row["object_type"]})
            # One fact can be asserted by several chunks; show it as one edge
            edge = edges.setdefault(row["fact_id"], {
                "id": row["fact_id"], "source": row["subject_id"], "target": row["object_id"],
                "predicate": row["predicate"], "evidence_count": 0,
            })
            edge["evidence_count"] += 1
        else:
            prop = properties.setdefault(row["fact_id"], {
                "entity": row["subject_id"], "predicate": row["predicate"].removeprefix("prop:"),
                "value": row["object"], "fact": row["fact_id"],
            })
    return nodes, list(edges.values()), list(properties.values())


def get_neighbors(entity_id):
    """Return the entity's literal properties and its relationships to other entities."""
    rows = client(GRAPH_INDEX).search(
        search_text="*",
        filter=f"subject_id eq {odata(entity_id)} or object_id eq {odata(entity_id)}",
        select=ASSERTION_FIELDS,
        top=1000,
    )
    nodes, edges, properties = graph_view(rows)
    return {
        "id": entity_id,
        "nodes": list(nodes.values()),
        "edges": edges,
        "properties": [p for p in properties if p["entity"] == entity_id],
    }


def get_catalog():
    """Return every entity grouped by type, plus all relationship facts, for browsing without IDs."""
    rows = list(client(GRAPH_INDEX).search(search_text="*", select=ASSERTION_FIELDS, top=1000))
    nodes, edges, _ = graph_view(rows)
    types = {}
    for node in nodes.values():
        types.setdefault(node["type"], []).append(node)
    return {
        "types": [
            {"name": name, "entities": sorted(entities, key=lambda e: e["name"])}
            for name, entities in sorted(types.items())
        ],
        "edges": edges,
    }


def get_evidence(fact_id):
    """Return a fact and every chunk that supports it."""
    assertions = [
        dict(row) for row in client(GRAPH_INDEX).search(
            search_text="*", filter=f"fact_id eq {odata(fact_id)}", select=ASSERTION_FIELDS, top=100,
        )
    ]
    supports = []
    for assertion in assertions:
        source = None
        if assertion.get("chunk_id"):
            source = dict(client(CHUNKS_INDEX).get_document(
                assertion["chunk_id"],
                selected_fields=["chunk_id", "title", "blob_path", "chunk", "page_number_from", "page_number_to"],
            ))
        supports.append({"evidence_quotes": assertion.get("evidence_quotes") or [], "source": source})
    fact = assertions[0]
    fact["predicate"] = fact["predicate"].removeprefix("prop:")
    return {"fact": fact, "supports": supports}


def get_topics():
    topics = client(TOPICS_INDEX)
    manifest_row = list(topics.search(search_text="*", filter="kind eq 'manifest'", select=["payload"], top=1))[0]
    manifest = json.loads(manifest_row["payload"])
    representatives = [
        dict(row)
        for row in topics.search(
            search_text="*",
            filter="kind eq 'representative'",
            select=["community_id", "parent_id", "level", "member_count", "label", "description", "is_terminal"],
            top=1000,
        )
    ]
    for topic in representatives:
        titles = Counter(member["title"] for member in get_topic_members(topic["community_id"]))
        topic["sample_titles"] = [title for title, _ in titles.most_common(4)]
    return {
        "coverage": {
            key: manifest.get(key)
            for key in ("source_document_count", "assigned_node_count", "unassigned_source_document_count")
        },
        "topics": representatives,
    }


def get_topic_members(community_id):
    chunk_ids = [
        row["chunk_id"]
        for row in client(TOPICS_INDEX).search(
            search_text="*",
            filter=f"kind eq 'membership' and community_id eq {odata(community_id)}",
            select=["chunk_id"],
            top=1000,
        )
    ]
    if not chunk_ids:
        return []
    return [
        dict(row)
        for row in client(CHUNKS_INDEX).search(
            search_text="*",
            filter=f"search.in(chunk_id, {odata(','.join(chunk_ids))}, ',')",
            select=["chunk_id", "title", "blob_path", "chunk"],
            top=1000,
        )
    ]


def get_sources():
    """Name where each tab's data comes from, so the page can point attendees at the same resources."""
    return {
        "ontology_file": str(ONTOLOGY_FILE.relative_to(ONTOLOGY_FILE.parents[2])),
        "graph_index": GRAPH_INDEX,
        "chunks_index": CHUNKS_INDEX,
        "topics_index": TOPICS_INDEX,
    }


ROUTES = {
    "/api/sources": lambda params: get_sources(),
    "/api/ontology": lambda params: get_ontology(),
    "/api/entities": lambda params: find_entities(params["q"]),
    "/api/neighbors": lambda params: get_neighbors(params["id"]),
    "/api/evidence": lambda params: get_evidence(params["id"]),
    "/api/catalog": lambda params: get_catalog(),
    "/api/topics": lambda params: get_topics(),
    "/api/topic-members": lambda params: get_topic_members(params["id"]),
}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path.startswith("/documents/"):
            return self.send_document(unquote(url.path.removeprefix("/documents/")))
        route = ROUTES.get(url.path)
        if route is None:
            return super().do_GET()
        params = {key: values[0] for key, values in parse_qs(url.query).items()}
        try:
            body, status = json.dumps(route(params)), 200
        except Exception as error:  # Show the service error in the browser instead of failing silently
            body, status = json.dumps({"error": f"{type(error).__name__}: {error}"}), 500
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body.encode())

    def send_document(self, relative_path):
        """Serve an original PDF from data/cocoarynth/documents, refusing paths outside that folder."""
        path = (DOCUMENTS_DIR / relative_path).resolve()
        if path.suffix != ".pdf" or not path.is_relative_to(DOCUMENTS_DIR) or not path.is_file():
            return self.send_error(404)
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    server = ThreadingHTTPServer(("localhost", PORT), Handler)
    url = f"http://localhost:{PORT}"
    print(f"Cocoarynth graph explorer running at {url} (press Ctrl+C to stop)")
    if os.getenv("EXPLORER_NO_BROWSER") != "1":
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
