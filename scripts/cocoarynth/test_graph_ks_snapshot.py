"""Regression checks at the offline snapshot command-line boundary."""

import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "verify-graph-ks.py"
SPEC = importlib.util.spec_from_file_location("graph_ks_check", SCRIPT)
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class GraphSnapshotTests(unittest.TestCase):
    def test_prepare_preserves_all_evidence_and_captured_vectors(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "prepare", "--output", directory],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            plan = json.loads((Path(directory) / "plan.json").read_text("utf-8"))
            self.assertEqual(
                (plan["source"]["records"], plan["source"]["vectors"]),
                (609, 106),
            )
            rows = {
                row["uid"]: row for row in (
                    json.loads(line) for line in
                    (Path(directory) / "sources-exported.jsonl").read_text("utf-8").splitlines()
                )
            }
            bundle = ROOT / "data" / "graph-data"
            for line in (bundle / "cocoarynth-graph-sources-exported.jsonl").read_text("utf-8").splitlines():
                original = json.loads(line)
                projected = rows[original["chunk_id"]]
                for before, after in (
                    ("chunk", "snippet"), ("parent_id", "snippet_parent_id"),
                    ("blob_path", "blob_url"), ("title", "title"),
                    ("source_pointer", "source_pointer"), ("source_index", "source_index"),
                    ("page_number_from", "page_number_from"), ("page_number_to", "page_number_to"),
                ):
                    self.assertEqual(projected.get(after), original.get(before))
            for line in (bundle / "cocoarynth-topic-sources-exported.jsonl").read_text("utf-8").splitlines():
                original = json.loads(line)
                self.assertEqual(
                    struct.pack("<3072f", *original["text_vector"]),
                    struct.pack("<3072f", *rows[original["chunk_id"]]["snippet_vector"]),
                )

    def test_prepare_preserves_native_assertions_and_the_source_join(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "prepare", "--output", directory],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            output = Path(directory)
            graph = [
                json.loads(line)
                for line in (output / "graph-exported.jsonl").read_text("utf-8").splitlines()
            ]
            original = [
                json.loads(line)
                for line in (ROOT / "data" / "graph-data" / "cocoarynth-graph-exported.jsonl")
                .read_text("utf-8").splitlines()
            ]
            self.assertEqual(graph, original)
            source_ids = {
                json.loads(line)["uid"]
                for line in (output / "sources-exported.jsonl").read_text("utf-8").splitlines()
            }
            self.assertTrue(all(row["chunk_id"] in source_ids for row in graph))
            definition = json.loads((output / "graph-index.json").read_text("utf-8"))
            sources = json.loads((output / "sources-index.json").read_text("utf-8"))
            self.assertEqual(
                definition["graphProfile"]["provenanceIndexName"], sources["name"]
            )

    def test_unembedded_evidence_has_empty_vector_collections_not_nulls(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "prepare", "--output", directory],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            rows = [
                json.loads(line) for line in
                (Path(directory) / "sources-exported.jsonl").read_text("utf-8").splitlines()
            ]
            self.assertEqual(sum(row["snippet_vector"] == [] for row in rows), 503)
            self.assertTrue(all(isinstance(row["snippet_vector"], list) for row in rows))

    def test_graph_ks_declares_its_real_preview_and_projection_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "prepare", "--output", directory],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            output = Path(directory)
            plan = json.loads((output / "plan.json").read_text("utf-8"))
            self.assertEqual(plan["graph_ks"]["api_version"], "2026-11-01-preview")
            self.assertEqual(plan["graph_ks"]["omitted_datatype_properties"], 185)
            self.assertTrue(plan["graph_ks"]["runtime_validated"])
            self.assertEqual(CHECK.load_plan(output)["owner"], plan["owner"])
            source = json.loads((output / "graph-ks.json").read_text("utf-8"))
            ontology = json.loads(source["searchIndexParameters"]["graphOntology"]["value"])
            declarations = ontology["@graph"]
            self.assertEqual(len(declarations), 109)
            self.assertEqual(
                sum(item["@type"] == "owl:ObjectProperty" for item in declarations), 70
            )

    def test_lexical_answers_and_client_fallbacks_cannot_prove_graph_ks(self):
        response = {
            "response": [{"type": "text", "text": "urn:cocoarynth:Farm:el-cedro"}],
            "activity": [
                {"type": "searchIndex", "knowledgeSourceName": "test-ks", "count": 1}
            ],
            "graph_rows": [{"answer": "urn:cocoarynth:Farm:el-cedro"}],
        }
        with self.assertRaises(CHECK.CheckError):
            CHECK.check_graph_activity(response, "test-ks", "test-graph")

    def test_schema_readback_respects_server_defaults_for_unspecified_flags(self):
        expected = {
            "description": "owned", "fields": [
                {"name": "uid", "type": "Edm.String", "key": True},
                {"name": "page_number_from", "type": "Edm.Int32", "filterable": True},
            ],
        }
        observed = {
            "description": "owned", "fields": [
                {"name": "uid", "type": "Edm.String", "key": True,
                 "sortable": True, "filterable": True, "facetable": True,
                 "searchable": True, "retrievable": True},
                {"name": "page_number_from", "type": "Edm.Int32", "filterable": True,
                 "sortable": True, "facetable": True, "retrievable": True},
            ],
        }
        CHECK.check_definition(expected, observed)
        expected["fields"][1]["filterable"] = False
        with self.assertRaises(CHECK.CheckError):
            CHECK.check_definition(expected, observed)

    def test_datetime_readback_allows_utc_normalization_but_preserves_original_text(self):
        original = {
            "id": "reading", "object": "2026-07-14T16:00:00-07:00",
            "object_datetime": "2026-07-14T16:00:00-07:00",
        }
        returned = {
            "id": "reading", "object": "2026-07-14T16:00:00-07:00",
            "object_datetime": "2026-07-14T23:00:00Z",
        }
        self.assertEqual(CHECK.parity([original], [returned], "id"), {"reading"})
        with self.assertRaises(CHECK.CheckError):
            CHECK.parity([original], [{**returned, "object": "2026-07-14T23:00:00Z"}], "id")

    def test_graph_ks_requires_successful_scoped_execution_and_generated_gql(self):
        query = "MATCH (f:`Farm`) RETURN f.id LIMIT 20"
        arguments = {
            "graphIndexName": "test-graph", "naturalLanguageQuery": "Which farms?",
            "outcome": "Success", "gql": query,
        }
        record = {"type": "graphSearch", "knowledgeSourceName": "test-ks",
                  "count": 2, "graphSearchArguments": arguments}
        self.assertEqual(
            CHECK.check_graph_activity({"activity": [record]}, "test-ks", "test-graph"), [query]
        )
        invalid = [
            {**record, "count": 0},
            {**record, "count": True},
            {**record, "error": {"message": "execution failed"}},
            {**record, "graphSearchArguments": {**arguments, "gql": None}},
            {**record, "graphSearchArguments": {**arguments, "outcome": "failed"}},
            {**record, "graphSearchArguments": {**arguments, "graphIndexName": "other-graph"}},
        ]
        for item in invalid:
            with self.subTest(activity=item), self.assertRaises(CHECK.CheckError):
                CHECK.check_graph_activity({"activity": [item]}, "test-ks", "test-graph")

    def test_http_success_with_graph_error_diagnostics_is_not_a_pass(self):
        client = Mock()
        client.request.return_value = {
            "value": [{"answer": "urn:cocoarynth:Farm:el-cedro"}],
            "@search.graphDiagnostics": [{"severity": "error", "message": "unsupported query"}],
        }
        with self.assertRaises(CHECK.CheckError):
            CHECK.graph_query(client, "test-graph", "MATCH (f:`Farm`) RETURN f.id LIMIT 20")

    def test_ownership_and_vector_parity_reject_unrelated_or_changed_data(self):
        with self.assertRaises(CHECK.CheckError):
            CHECK.check_definition({"description": "owned"}, {"description": "unrelated"})
        with self.assertRaises(CHECK.CheckError):
            CHECK.parity(
                [{"uid": "original", "snippet_vector": []}],
                [{"uid": "original", "snippet_vector": [0.0] * 3072}], "uid",
            )
        original = {"uid": "captured", "snippet_vector": [1.0] + [0.0] * 3071}
        same_float32 = {"uid": "captured", "snippet_vector": [1.00000000001] + [0.0] * 3071}
        self.assertEqual(CHECK.parity([original], [same_float32], "uid"), {"captured"})
        with self.assertRaises(CHECK.CheckError):
            CHECK.parity([original], [{
                "uid": "captured", "snippet_vector": [1.0000001192092896] + [0.0] * 3071,
            }], "uid")

    def test_prepared_index_definitions_cannot_escape_the_declared_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "prepare", "--output", directory],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            output = Path(directory)
            path = output / "sources-index.json"
            definition = json.loads(path.read_text("utf-8"))
            definition["name"] = "unrelated-sources"
            path.write_text(json.dumps(definition), encoding="utf-8")
            with self.assertRaisesRegex(CHECK.CheckError, "declared ownership scope"):
                CHECK.load_plan(output)

    def test_graph_ks_and_kb_metadata_cannot_redirect_the_verification(self):
        source = {
            "name": "owned-ks", "description": "owned", "kind": "searchIndex",
            "searchIndexParameters": {"searchIndexName": "owned-graph",
                                      "graphOntology": {"kind": "inline", "value": "{}"}},
        }
        CHECK.check_metadata(source, source)
        with self.assertRaises(CHECK.CheckError):
            CHECK.check_metadata(source, {
                **source, "searchIndexParameters": {
                    **source["searchIndexParameters"], "searchIndexName": "unrelated-graph",
                },
            })
        kb = {"name": "owned-kb", "description": "owned",
              "knowledgeSources": [{"name": "owned-ks"}]}
        with self.assertRaises(CHECK.CheckError):
            CHECK.check_metadata(kb, {**kb, "knowledgeSources": [{"name": "unrelated-ks"}]})

    def test_other_bad_requests_are_not_mislabeled_as_an_unavailable_preview(self):
        client = Mock()
        client.request.side_effect = CHECK.ServiceError(
            400, "Invalid property for the supplied api-version.", CHECK.KS_API
        )
        with self.assertRaises(CHECK.ServiceError):
            CHECK.preview_available(client, {})
        client.request.side_effect = CHECK.ServiceError(
            400, "The version indicated by the api-version query string parameter does not exist.",
            CHECK.KS_API,
        )
        report = {}
        self.assertFalse(CHECK.preview_available(client, report))
        self.assertFalse(report["graph_ks"]["server_nl2gql_verified"])


if __name__ == "__main__":
    unittest.main()
