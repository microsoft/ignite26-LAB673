"""Bounded regression and adversarial tests for the checked-in finished sample data."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SCRIPT_ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("cocoarynth_validation", SCRIPT_ROOT / "validate-cocoarynth-data.py")
validation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validation)


class CocoarynthData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = validation.DATA_ROOT
        cls.data = json.loads((root / "records.json").read_text(encoding="utf-8"))
        cls.sources = json.loads((root / "sample-sources.json").read_text(encoding="utf-8"))
        cls.documents = json.loads((root / "document-manifest.json").read_text(encoding="utf-8"))

    def altered(self, identifier, **fields):
        data = deepcopy(self.data)
        next(row for row in data["records"] if row["id"] == identifier).update(fields)
        return data

    def rejected(self, data, code):
        errors = validation.validate(data, self.sources)
        self.assertTrue(any(error.startswith(code + ":") for error in errors), errors)

    def test_checked_in_domain(self):
        self.assertEqual([], validation.validate(self.data, self.sources))

    def test_finished_document_links_and_bindings(self):
        self.assertEqual([], validation.check_documents(self.data, self.sources, self.documents))

    def test_canonical_files_preserved(self):
        self.assertEqual([], validation.check_import())

    def test_real_lab_loader_keeps_original_selections(self):
        self.assertEqual(
            {"cocoarynth-documents-index": 4, "cocoarynth-engineering-practices-index": 4},
            validation.check_lab_selection(),
        )

    def test_duplicate_ids(self):
        data = deepcopy(self.data)
        data["records"].append(deepcopy(data["records"][0]))
        self.rejected(data, "ids")

    def test_dangling_record_link(self):
        self.rejected(self.altered("V2-B-042", product_id="V2-UNKNOWN"), "reference")

    def test_unrecorded_transit_loss(self):
        self.rejected(self.altered("V2-L-042", received_g=300001), "custody_mass")

    def test_redry_cannot_remove_unaccounted_solids(self):
        self.rejected(self.altered("V2-L-042", water_removed_g=4000), "moisture_mass")

    def test_negative_inventory(self):
        self.rejected(self.altered("V2-MV-042-BEAN-042", delta_g=-999000), "inventory_negative")

    def test_wrong_closing_inventory(self):
        self.rejected(self.altered("V2-AC-BEAN-042", balance_g=999000), "inventory_balance")

    def test_roast_and_shell_outflows_stay_separate(self):
        self.rejected(self.altered("V2-B-042", shells_g=0), "conversion_mass")

    def test_recipe_percentage_is_not_bean_yield(self):
        self.rejected(self.altered("V2-B-042", cacao_percentage=67), "recipe")

    def test_bar_unit_conversion(self):
        self.rejected(self.altered("V2-B-039", bars=3000), "bar_mass")

    def test_wip_cannot_consume_planned_ingredients(self):
        self.rejected(self.altered("V2-B-027", butter_g=7000), "wip")

    def test_corrupted_passport_hash(self):
        self.rejected(self.altered("V2-PP-042-1", snapshot_sha256="0" * 64), "snapshot_hash")

    def test_extra_passport_field_rejected(self):
        data = deepcopy(self.data)
        passport = next(row for row in data["records"] if row["id"] == "V2-PP-042-1")
        passport["snapshot"]["internal_quality_notes"] = "not allowed"
        self.rejected(data, "allowlist")

    def test_replacement_cannot_change_recipient(self):
        self.rejected(self.altered("V2-PP-042-2", recipient_id="V2-MAPAYCA"), "recipient")

    def test_ready_batch_cannot_be_called_shipped(self):
        self.rejected(self.altered("V2-B-031", status="shipped"), "eligibility")

    def test_duplicate_document_identity(self):
        documents = deepcopy(self.documents)
        documents.append(deepcopy(documents[0]))
        self.assertIn(
            "content: duplicate document ID",
            validation.check_documents(self.data, self.sources, documents),
        )

    def test_stale_document_binding(self):
        documents = deepcopy(self.documents)
        documents[0]["bindings"][0]["rendered_value"] = "wrong"
        self.assertTrue(any("stale canonical binding" in error for error in
                            validation.check_documents(self.data, self.sources, documents)))

    def test_stale_case_fact(self):
        documents = deepcopy(self.documents)
        item = next(row for row in documents if row["id"] == "collection-notebook")
        item["fact_expectations"]["V2-L-042"]["wet_beans_g"] = 1
        self.assertTrue(any("stale case facts" in error for error in
                            validation.check_documents(self.data, self.sources, documents)))

    def test_stale_pdf_hash(self):
        documents = deepcopy(self.documents)
        documents[0]["sha256"] = "0" * 64
        self.assertTrue(any("PDF hash drift" in error for error in
                            validation.check_documents(self.data, self.sources, documents)))

    def test_nonlocal_document_path_rejected(self):
        with self.assertRaisesRegex(ValueError, "non-local"):
            validation.local_path(validation.DATA_ROOT, "../../README.md")

    def test_missing_lab_pdf_rejected_by_real_loader(self):
        with tempfile.TemporaryDirectory(prefix="cocoarynth-loader-") as directory:
            root = Path(directory)
            original = validation.DATA_ROOT / "corpora.json"
            (root / "corpora.json").write_bytes(original.read_bytes())
            with patch.object(validation, "DATA_ROOT", root):
                with self.assertRaisesRegex(RuntimeError, "missing files"):
                    validation.check_lab_selection()


if __name__ == "__main__":
    unittest.main()
