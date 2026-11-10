"""Offline contract and consumer checks for the canonical lab topic snapshot."""

import contextlib
import copy
import importlib.util
import io
import json
import math
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from azure.search.documents.indexes.models import SearchIndex


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


loader = load_module("lab_restore", ROOT / "infra" / "restore-graph-indexes.py")
with patch("dotenv.load_dotenv", return_value=False):
    explorer = load_module("lab_explorer", ROOT / "src" / "explorer" / "app.py")


class SnapshotClient:
    """Execute the examples' document filters and cosine queries against the real snapshots."""

    def __init__(self, snapshot, calls):
        self.snapshot = snapshot
        self.fields = {field["name"]: field for field in snapshot.definition["fields"]}
        self.calls = calls
        self.norms = {
            row[snapshot.key]: math.sqrt(sum(x * x for x in row[field["name"]]))
            for row in snapshot.records for field in self.fields.values()
            if field.get("dimensions") and row.get(field["name"])
        }

    def get_document_count(self):
        return len(self.snapshot.records)

    def get_document(self, key, selected_fields=None):
        row = next(row for row in self.snapshot.records if row[self.snapshot.key] == key)
        return {name: row.get(name) for name in selected_fields or self.fields}

    def search(self, search_text=None, *, select=None, filter=None, vector_queries=None,
               top=None, search_fields=None):
        self.calls.append({"index": self.snapshot.name, "filter": filter, "vectors": vector_queries, "top": top})
        selected = select or list(self.fields)
        for name in selected:
            assert name in self.fields and self.fields[name].get("retrievable", True), name
        rows = list(self.snapshot.records)
        if filter:
            equality = re.fullmatch(r"(\w+) eq '((?:[^']|'')*)'", filter)
            inclusion = re.fullmatch(r"search\.in\((\w+), '([^']*)', '([^']+)'\)", filter)
            assert equality or inclusion, f"Unsupported filter: {filter}"
            name = (equality or inclusion)[1]
            assert self.fields[name].get("filterable"), name
            if equality:
                rows = [row for row in rows if row.get(name) == equality[2].replace("''", "'")]
            else:
                keys = set(inclusion[2].split(inclusion[3]))
                rows = [row for row in rows if row.get(name) in keys]
        if search_text and search_text != "*":
            fields = search_fields or [name for name, field in self.fields.items() if field.get("searchable")]
            assert all(self.fields[name].get("searchable") for name in fields)
            phrase = search_text.strip('"').casefold()
            rows = [row for row in rows if any(phrase in str(row.get(name, "")).casefold() for name in fields)]
        if vector_queries:
            assert len(vector_queries) == 1
            query = vector_queries[0]
            name = query.fields
            assert name in self.fields and self.fields[name].get("searchable"), name
            assert len(query.vector) == self.fields[name]["dimensions"]
            query_norm = math.sqrt(sum(x * x for x in query.vector))
            ranked = [
                (sum(x * y for x, y in zip(query.vector, row[name]))
                 / (query_norm * self.norms[row[self.snapshot.key]]), row)
                for row in rows if row.get(name)
            ]
            rows = [row for _, row in sorted(ranked, key=lambda pair: (-pair[0], pair[1][self.snapshot.key]))]
            rows = rows[:query.k_nearest_neighbors]
        return [{name: row.get(name) for name in selected} for row in rows[:top]]

    def graph(self, *, gql, include_statistics=False):
        assert include_statistics
        match = re.search(r"MATCH \((\w+):`(\w+)`\)-\[:`(\w+)`\]->\((\w+):`(\w+)`\)", gql)
        assert match, gql
        left, left_type, predicate, right, right_type = match.groups()
        ontology = loader.read_ontology(ROOT / "data" / "graph-data" / "cocoarynth-sitemap.owl")
        properties = {
            term["@id"].split(":")[1]: term for term in ontology["@graph"]
            if term["@type"] in ("owl:ObjectProperty", "owl:DatatypeProperty")
        }
        relation = properties[predicate]
        assert relation["rdfs:domain"]["@id"] == "schema:" + left_type
        assert relation["rdfs:range"]["@id"] == "schema:" + right_type
        where = re.search(r"WHERE (\w+)\.id = '([^']+)'", gql)
        returns = re.search(r"RETURN (.*?)\s+LIMIT \d+", gql, re.S)[1]
        expressions = [re.fullmatch(r"(\w+)\.(\w+) AS (\w+)", item.strip()) for item in returns.split(",")]
        assert all(expressions), returns
        result = []
        for row in self.snapshot.records:
            if row["predicate"] != predicate:
                continue
            bindings = {left: row["subject_id"], right: row["object_id"]}
            if where and bindings[where[1]] != where[2]:
                continue
            projected = {}
            for expression in expressions:
                variable, name, alias = expression.groups()
                subject_id = bindings[variable]
                if name == "id":
                    projected[alias] = subject_id
                else:
                    assert name in properties, f"Unknown graph property: {name}"
                    fact = next(
                        fact for fact in self.snapshot.records
                        if fact["subject_id"] == subject_id and fact["predicate"] == "prop:" + name
                    )
                    projected[alias] = next(
                        fact[field] for field in ("object_string", "object_double", "object_bool", "object_datetime")
                        if fact.get(field) is not None
                    )
            result.append(projected)
        return SimpleNamespace(value=result)


class TopicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest, snapshots = loader.load_bundle("", None)
        cls.snapshots = {snapshot.original_name: snapshot for snapshot in snapshots}

    def setUp(self):
        self.calls = []
        self.clients = {name: SnapshotClient(snapshot, self.calls) for name, snapshot in self.snapshots.items()}
        explorer.get_topic_hierarchy.cache_clear()
        explorer.get_topic_metadata.cache_clear()

    def test_release_schema_and_all_sdk_models_round_trip(self):
        for snapshot in self.snapshots.values():
            loader.assert_subset(snapshot.definition, SearchIndex(snapshot.definition).as_dict(exclude_readonly=True),
                                 snapshot.name)
        ontology = loader.read_ontology(ROOT / "data" / "graph-data" / "cocoarynth-sitemap.owl")
        header = next(term for term in ontology["@graph"] if term["@type"] == "owl:Ontology")
        self.assertEqual(header["owl:versionInfo"], "2.3.0")
        topics = self.snapshots["cocoarynth-topics"]
        counts = {}
        for row in topics.records:
            counts[row["predicate"]] = counts.get(row["predicate"], 0) + 1
            self.assertFalse({"kind", "community_id", "centroid", "payload", "generation_id"} & set(row))
            self.assertFalse(row.get("chunk_id") or row.get("parent_id"))
        self.assertEqual(len(topics.records), 54)
        self.assertEqual(counts, {
            "HasRootTopic": 4, "HasSubTopic": 4, "HasCentroidVector": 6,
            "prop:title": 8, "prop:description": 8, "prop:level": 8,
            "prop:proportion": 8, "prop:parentProportion": 8,
        })

    def test_prefixed_restore_changes_bindings_not_topic_facts(self):
        manifest, snapshots = loader.load_bundle("offline-check", "[test-owner]")
        topics = next(snapshot for snapshot in snapshots if snapshot.original_name == "cocoarynth-topics")
        graph = next(snapshot for snapshot in snapshots if snapshot.original_name == "cocoarynth-graph")
        self.assertEqual(manifest["topics"]["physical_index"], "offline-check-cocoarynth-topics")
        self.assertEqual(manifest["topics"]["source_index"], "offline-check-cocoarynth-chunks")
        self.assertEqual(topics.records, self.snapshots["cocoarynth-topics"].records)
        self.assertNotIn("provenanceIndexName", topics.definition["graphProfile"])
        self.assertEqual(graph.definition["graphProfile"]["provenanceIndexName"], "offline-check-cocoarynth-chunks")

    def test_knowledge_sources_select_real_fields_and_preserve_business_provenance(self):
        sources = loader.graph_sources(self.manifest, list(self.snapshots.values()), None)
        for source in sources:
            parameters = source["searchIndexParameters"]
            fields = {field["name"] for field in self.snapshots[parameters["searchIndexName"]].definition["fields"]}
            self.assertTrue({field["name"] for field in parameters["sourceDataFields"]} <= fields)
        topic_source = next(source for source in sources if source["name"] == "cocoarynth-topics-knowledge-source")
        self.assertEqual(topic_source["searchIndexParameters"]["semanticConfigurationName"],
                         "topicgraph-topic-semantic")
        graph = self.snapshots["cocoarynth-graph"].records
        chunks = {row["chunk_id"]: row for row in self.snapshots["cocoarynth-chunks"].records}
        self.assertEqual((len(graph), len({row["fact_id"] for row in graph})), (120, 91))
        for row in graph:
            chunk = chunks[row["chunk_id"]]
            self.assertEqual(row["parent_id"], chunk["parent_id"])
            self.assertTrue(all(quote in chunk["chunk"] for quote in row["evidence_quotes"]))

    def test_invalid_legacy_and_incomplete_topic_snapshots_are_rejected(self):
        original = self.snapshots["cocoarynth-topics"]
        mutations = {
            "legacy field": lambda snapshot: snapshot.definition["fields"].append({"name": "kind"}),
            "missing leaf vector": lambda snapshot: snapshot.records.remove(next(
                row for row in snapshot.records if row["predicate"] == "HasCentroidVector")),
            "short leaf vector": lambda snapshot: next(
                row for row in snapshot.records if row["predicate"] == "HasCentroidVector").update(object_vector=[1.0]),
            "duplicate parent": lambda snapshot: snapshot.records.append(copy.deepcopy(next(
                row for row in snapshot.records if row["predicate"] == "HasSubTopic"))),
            "missing title": lambda snapshot: snapshot.records.remove(next(
                row for row in snapshot.records if row["predicate"] == "prop:title")),
            "wrong level": lambda snapshot: next(
                row for row in snapshot.records if row["predicate"] == "prop:level").update(object_double=9.0),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                snapshot = copy.deepcopy(original)
                mutate(snapshot)
                with self.assertRaises(RuntimeError):
                    loader.validate_topics(snapshot, self.manifest["topics"], 106)

    def test_restore_queries_canonical_root_and_child_edges(self):
        requests = []
        graph = self.snapshots["cocoarynth-graph"]
        assertion = graph.records[0]

        def preview(indexes, endpoint, path, api, body, expected_status):
            requests.append((path, body))
            self.assertEqual(api, "2026-11-01-preview")
            self.assertEqual(expected_status, 200)
            if "cocoarynth-topics" in path:
                result = self.clients["cocoarynth-topics"].graph(
                    gql=body["gql"], include_statistics=body["includeStatistics"],
                )
                rows = result.value
                self.assertEqual(len(rows), 4)
            else:
                expected = next(expected for _, gql, expected in loader.GRAPH_CASES if gql == body["gql"])
                rows = [{
                    "answer": answer,
                    "@search.graphProvenance": {"evidence": [{
                        "edgeId": assertion["id"], "chunkId": assertion["chunk_id"], "parentId": assertion["parent_id"],
                    }]},
                } for answer in expected]
            return {"value": rows, "@search.graphStats": {"executionMode": "execute"}}

        with patch.object(loader, "preview_json", side_effect=preview), contextlib.redirect_stdout(io.StringIO()):
            loader.verify_graph(None, "https://offline.search.windows.net", "2026-11-01-preview",
                                list(self.snapshots.values()))
        self.assertEqual(len(requests), 5)
        self.assertIn("HasRootTopic", requests[-2][1]["gql"])
        self.assertIn("HasSubTopic", requests[-1][1]["gql"])

    def test_explorer_reads_canonical_facts_and_uses_source_vector_queries(self):
        with patch.object(explorer, "client", side_effect=self.clients.__getitem__):
            hierarchy = explorer.get_topic_hierarchy()
            response = explorer.get_topics()
            self.assertEqual(len(hierarchy), 8)
            self.assertEqual(sum(topic["is_terminal"] for topic in hierarchy.values()), 6)
            self.assertEqual(sum(topic["is_terminal"] and topic["level"] == 0 for topic in hierarchy.values()), 2)
            self.assertEqual(response["coverage"]["assigned_node_count"], 97)
            for topic in hierarchy.values():
                members = explorer.get_topic_members(topic["topic_id"])
                self.assertEqual(len(members), topic["member_count"])
                self.assertTrue(all(member["blob_path"].endswith(".pdf") for member in members))
            topic_calls = [call for call in self.calls if call["index"] == "cocoarynth-topics"]
            self.assertEqual(len(topic_calls), 1)
            self.assertIsNone(topic_calls[0]["filter"])
            self.assertTrue(all(call["vectors"][0].fields == "text_vector"
                                for call in self.calls if call["index"] == "cocoarynth-chunks"))
            root = next(topic for topic in hierarchy.values() if not topic["is_terminal"])
            root["member_count"] = 1500
            explorer.get_topic_members(root["topic_id"])
            self.assertEqual(self.calls[-1]["vectors"][0].k_nearest_neighbors, 1000)
            with self.assertRaisesRegex(RuntimeError, "Unknown topic"):
                explorer.get_topic_members("topic:missing")

    def test_notebook_executes_in_order_with_only_offline_sdk_doubles(self):
        notebook = json.loads((ROOT / "src" / "notebooks" / "03-topics.ipynb").read_text(encoding="utf-8"))
        sources = {source["name"]: source for source in loader.graph_sources(
            self.manifest, list(self.snapshots.values()), None
        )}
        created_bases, requests = [], []

        def create_base(base):
            created_bases.append(base.as_dict())

        evidence = next(row for row in self.snapshots["cocoarynth-chunks"].records
                        if row["blob_path"].endswith("retention-check-gh26-0706.pdf"))

        def retrieve(knowledge_base_name, request):
            requests.append((knowledge_base_name, request.as_dict()))
            is_topic = knowledge_base_name == "cocoarynth-topics-knowledge-base"
            return SimpleNamespace(
                response=[SimpleNamespace(content=[SimpleNamespace(text="Offline response")])],
                activity=[SimpleNamespace(as_dict=lambda: {"type": "graphSearch" if is_topic else "searchIndex"})],
                references=[] if is_topic else [
                    SimpleNamespace(id="0", type="searchIndex", source_data=evidence)
                ],
            )

        def retrieval_client(*args, **kwargs):
            return SimpleNamespace(
                retrieve=lambda request: retrieve(kwargs["knowledge_base_name"], request)
            )

        index_client = SimpleNamespace(
            get_knowledge_source=lambda name: SimpleNamespace(as_dict=lambda: sources[name]),
            create_or_update_knowledge_base=create_base,
        )
        settings = {
            "AZURE_SEARCH_SERVICE_ENDPOINT": "https://offline.search.windows.net",
            "AZURE_SEARCH_ADMIN_KEY": "offline-test-key",
            "AZURE_OPENAI_ENDPOINT": "https://offline.openai.azure.com",
            "AZURE_OPENAI_KEY": "offline-test-key",
            "AZURE_OPENAI_CHATGPT_DEPLOYMENT": "offline",
            "AZURE_OPENAI_CHATGPT_MODEL_NAME": "gpt-6-luna",
        }
        scope, output = {}, io.StringIO()
        with patch.dict(os.environ, settings, clear=True), \
                patch("dotenv.load_dotenv", return_value=False), \
                patch("azure.search.documents.SearchClient", side_effect=lambda endpoint, index, *a, **k: self.clients[index]), \
                patch("azure.search.documents.indexes.SearchIndexClient", return_value=index_client), \
                patch("azure.search.documents.knowledgebases.KnowledgeBaseRetrievalClient",
                      side_effect=retrieval_client), \
                patch("azure.core.pipeline.transport.RequestsTransport.send") as transport, \
                contextlib.redirect_stdout(output):
            for number, cell in enumerate(notebook["cells"]):
                if cell["cell_type"] == "code":
                    self.assertIsNone(cell["execution_count"])
                    self.assertEqual(cell["outputs"], [])
                    exec(compile("".join(cell["source"]), f"03-topics.ipynb:cell-{number}", "exec"), scope)
            transport.assert_not_called()
        topic_reads = [call["filter"] for call in self.calls
                       if call["index"] == "cocoarynth-topics" and not call["vectors"]]
        self.assertEqual(topic_reads, [
            f"subject_id eq '{scope['NEAREST_TOPIC_ID']}'", "predicate eq 'HasCentroidVector'",
        ])
        with patch.object(explorer, "client", side_effect=self.clients.__getitem__):
            hierarchy = explorer.get_topic_hierarchy()
        nearest = hierarchy[scope["NEAREST_TOPIC_ID"]]
        self.assertTrue(nearest["is_terminal"])
        self.assertEqual(scope["nearest_topic"]["prop:title"], nearest["label"])
        self.assertEqual(scope["topic_size"], nearest["member_count"])
        self.assertEqual(len(scope["member_ids"]), nearest["member_count"])
        self.assertEqual(len(scope["direct"]), 8)
        self.assertEqual(len(scope["routed"]), 8)
        self.assertTrue(scope["routed_ids"] <= set(scope["member_ids"]))
        self.assertEqual({row["topic_id"] for row in scope["root_topics"]},
                         {topic_id for topic_id, topic in hierarchy.items() if topic["level"] == 0})
        self.assertEqual({row["topic_id"]: row["parent_id"] for row in scope["subtopics"]},
                         {topic_id: topic["parent_id"] for topic_id, topic in hierarchy.items() if topic["parent_id"]})
        self.assertEqual(len(scope["root_topics"]) + len(scope["subtopics"]), 8)
        self.assertEqual(set(scope["centroids"]),
                         {topic_id for topic_id, topic in hierarchy.items() if topic["is_terminal"]})
        for topic_id, centroid in scope["centroids"].items():
            self.assertTrue(all(math.isclose(left, right, abs_tol=1e-14)
                                for left, right in zip(hierarchy[topic_id]["centroid"], centroid)))
        self.assertEqual(len(created_bases), 1)
        self.assertEqual(len(requests), 2)
        self.assertEqual([name for name, _ in requests], [
            "cocoarynth-topics-knowledge-base", "cocoarynth-standard-knowledge-base",
        ])
        topic_request, document_request = [request for _, request in requests]
        topic_question = topic_request["messages"][0]["content"][0]["text"]
        self.assertIn("Larkspur", topic_question)
        self.assertIn("grey", topic_question)
        for topic in scope["root_topics"] + scope["subtopics"]:
            self.assertNotIn(topic["title"], topic_question)
            self.assertNotIn(topic["topic_id"], topic_question)
        self.assertNotIn("HasSubTopic", topic_question)
        self.assertEqual(
            [source["knowledgeSourceName"] for source in topic_request["knowledgeSourceParams"]],
            ["cocoarynth-topics-knowledge-source"],
        )
        document_question = document_request["messages"][0]["content"][0]["text"]
        for phrase in ("Larkspur", "GH26-0706", "batch", "delivery", "other stores"):
            self.assertIn(phrase, document_question)
        self.assertEqual(
            {source["knowledgeSourceName"] for source in document_request["knowledgeSourceParams"]},
            {f"cocoarynth-{domain}-knowledge-source" for domain in ("production", "sales", "policies")},
        )
        for _, request in requests:
            for source in request["knowledgeSourceParams"]:
                self.assertTrue(source["includeReferences"])
                self.assertTrue(source["includeReferenceSourceData"])
                self.assertTrue(source["alwaysQuerySource"])
        self.assertIn(evidence["blob_path"], output.getvalue())
        first_cell = "".join(notebook["cells"][0]["source"])
        self.assertIn("Run Part 1 first", first_cell)
        self.assertLess(first_cell.index("Mission"), first_cell.index("## How the topic graph is built"))

    def test_notebook_loads_settings_and_metadata_from_root_or_notebook_directory(self):
        notebook = json.loads((ROOT / "src" / "notebooks" / "03-topics.ipynb").read_text(encoding="utf-8"))
        cells = {cell["id"]: "".join(cell["source"]) for cell in notebook["cells"]}
        self.assertNotIn("find_dotenv", cells["a027f58b"])
        settings = {
            "AZURE_SEARCH_SERVICE_ENDPOINT": "https://offline.search.windows.net",
            "AZURE_SEARCH_ADMIN_KEY": "offline-test-key",
            "AZURE_OPENAI_ENDPOINT": "https://offline.openai.azure.com",
            "AZURE_OPENAI_KEY": "offline-test-key",
            "AZURE_OPENAI_CHATGPT_DEPLOYMENT": "offline",
            "AZURE_OPENAI_CHATGPT_MODEL_NAME": "gpt-6-luna",
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".env").write_text("\n".join(f"{key}={value}" for key, value in settings.items()),
                                     encoding="utf-8")
            metadata = root / "data" / "graph-data" / "manifest.json"
            metadata.parent.mkdir(parents=True)
            metadata.write_text(json.dumps(self.manifest), encoding="utf-8")
            notebook_directory = root / "src" / "notebooks"
            notebook_directory.mkdir(parents=True)
            for directory in (root, notebook_directory):
                with self.subTest(directory=directory), contextlib.chdir(directory), \
                        patch.dict(os.environ, {}, clear=True), \
                        patch.object(sys, "ps1", ">>>", create=True), \
                        contextlib.redirect_stdout(io.StringIO()):
                    scope = {"json": json, "Path": Path}
                    exec(compile(cells["a027f58b"], "03-topics.ipynb:settings", "exec"), scope)
                    exec(compile(cells["624a1a30"], "03-topics.ipynb:metadata", "exec"), scope)
                    self.assertTrue(all(scope[key] == value for key, value in settings.items()))
                    self.assertEqual(scope["metadata_file"].resolve(), metadata)
                    self.assertEqual(scope["build_metadata"]["clustered_source_document_count"], 97)

    def test_terminal_root_centroids_are_searchable(self):
        with patch.object(explorer, "client", side_effect=self.clients.__getitem__):
            roots = [topic for topic in explorer.get_topic_hierarchy().values()
                     if topic["level"] == 0 and topic["is_terminal"]]
        from azure.search.documents.models import VectorizedQuery

        self.assertEqual(len(roots), 2)
        for root in roots:
            hits = self.clients["cocoarynth-topics"].search(
                filter="predicate eq 'HasCentroidVector'",
                vector_queries=[VectorizedQuery(
                    vector=root["centroid"], fields="object_vector", k_nearest_neighbors=1, exhaustive=True,
                )],
                select=["subject_id"], top=1,
            )
            self.assertEqual(hits[0]["subject_id"], root["topic_id"])


if __name__ == "__main__":
    unittest.main()
