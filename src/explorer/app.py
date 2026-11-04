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
from urllib.parse import parse_qs, urlparse

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from dotenv import load_dotenv

load_dotenv(override=True)

PORT = int(os.getenv("EXPLORER_PORT", "8765"))
STATIC_DIR = Path(__file__).parent / "static"
API_VERSION = "2026-11-01-preview"
GRAPH_INDEX = "cocoarynth-graph"
ONTOLOGY_INDEX = "cocoarynth-ontology"
GRAPH_SOURCES_INDEX = "cocoarynth-graph-sources"
TOPICS_INDEX = "grz-cocoarynth-topics-bb1deb018565"
TOPIC_SOURCES_INDEX = "grz-cocoarynth-input-f7d06ba6-517dba815a29"

ASSERTION_FIELDS = ["id", "subject", "subject_type", "subject_id", "predicate", "object", "object_type", "object_id", "chunk_id"]


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
    types, relationships = {}, {}
    for row in client(ONTOLOGY_INDEX).search(
        search_text="*", select=["subject", "subject_type", "predicate", "object"], top=1000
    ):
        if row["subject_type"] == "NodeType" and row["predicate"] == "rdfs:comment":
            types[row["subject"]] = row["object"]
        elif row["subject_type"] == "EdgeType":
            key = {"rdfs:domain": "domain", "rdfs:range": "range", "rdfs:comment": "comment"}[row["predicate"]]
            relationships.setdefault(row["subject"], {"name": row["subject"]})[key] = row["object"]
    return {
        "types": [{"name": name, "comment": comment} for name, comment in sorted(types.items())],
        "relationships": sorted(relationships.values(), key=lambda r: r["name"]),
    }


def find_entities(query):
    entities = {}
    for row in client(GRAPH_INDEX).search(
        search_text=query,
        search_fields=["subject"],
        select=["subject", "subject_type", "subject_id"],
        filter="subject_type ne 'Document'",
        top=50,
    ):
        entities.setdefault(row["subject_id"], {"id": row["subject_id"], "name": row["subject"], "type": row["subject_type"]})
    return list(entities.values())[:15]


def get_neighbors(entity_id):
    """Return the entity's literal properties and its relationships to other entities."""
    rows = client(GRAPH_INDEX).search(
        search_text="*",
        filter=f"subject_id eq {odata(entity_id)} or object_id eq {odata(entity_id)}",
        select=ASSERTION_FIELDS,
        top=300,
    )
    properties, edges, nodes = [], [], {}
    for row in rows:
        if row["subject_id"] == entity_id:
            nodes[entity_id] = {"id": entity_id, "name": row["subject"], "type": row["subject_type"]}
        if not row.get("object_id"):
            if row["subject_id"] == entity_id:
                properties.append({"predicate": row["predicate"], "value": row["object"], "assertion": row["id"]})
            continue
        nodes.setdefault(row["subject_id"], {"id": row["subject_id"], "name": row["subject"], "type": row["subject_type"]})
        nodes.setdefault(row["object_id"], {"id": row["object_id"], "name": row["object"], "type": row["object_type"]})
        edges.append({
            "id": row["id"],
            "source": row["subject_id"],
            "target": row["object_id"],
            "predicate": row["predicate"],
        })
    return {"id": entity_id, "nodes": list(nodes.values()), "edges": edges, "properties": properties}


def get_evidence(assertion_id):
    assertion = dict(client(GRAPH_INDEX).get_document(assertion_id, selected_fields=ASSERTION_FIELDS))
    source = None
    if assertion.get("chunk_id"):
        source = dict(client(GRAPH_SOURCES_INDEX).get_document(assertion["chunk_id"]))
    return {"assertion": assertion, "source": source}


def get_topics():
    topics = client(TOPICS_INDEX)
    manifest_row = list(topics.search(search_text="*", filter="kind eq 'manifest'", select=["payload"], top=1))[0]
    manifest = json.loads(manifest_row["payload"])
    generation = manifest["generation_id"]
    representatives = [
        dict(row)
        for row in topics.search(
            search_text="*",
            filter=f"kind eq 'representative' and generation_id eq {odata(generation)}",
            select=["community_id", "parent_id", "level", "member_count", "label"],
            top=1000,
        )
    ]
    for topic in representatives:
        titles = Counter(member["title"] for member in get_topic_members(topic["community_id"], generation))
        topic["sample_titles"] = [title for title, _ in titles.most_common(4)]
    return {
        "generation_id": generation,
        "coverage": {
            key: manifest.get(key)
            for key in ("source_document_count", "assigned_node_count", "unassigned_source_document_count")
        },
        "topics": representatives,
    }


def get_topic_members(community_id, generation):
    chunk_ids = [
        row["chunk_id"]
        for row in client(TOPICS_INDEX).search(
            search_text="*",
            filter=f"kind eq 'membership' and community_id eq {odata(community_id)} and generation_id eq {odata(generation)}",
            select=["chunk_id"],
            top=1000,
        )
    ]
    if not chunk_ids:
        return []
    return [
        dict(row)
        for row in client(TOPIC_SOURCES_INDEX).search(
            search_text="*",
            filter=f"search.in(chunk_id, {odata(','.join(chunk_ids))}, ',')",
            select=["chunk_id", "title", "blob_path", "chunk"],
            top=1000,
        )
    ]


ROUTES = {
    "/api/ontology": lambda params: get_ontology(),
    "/api/entities": lambda params: find_entities(params["q"]),
    "/api/neighbors": lambda params: get_neighbors(params["id"]),
    "/api/evidence": lambda params: get_evidence(params["id"]),
    "/api/topics": lambda params: get_topics(),
    "/api/topic-members": lambda params: get_topic_members(params["id"], params["generation"]),
}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def do_GET(self):
        url = urlparse(self.path)
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
