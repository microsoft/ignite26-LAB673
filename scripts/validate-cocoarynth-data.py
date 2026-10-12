"""Validate Cocoarynth records, finished PDFs and the unchanged lab selections offline."""
from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data" / "cocoarynth"
POLICY = {
    "mass_tolerance_g": 1,
    "moisture_limit_percent": 7.5,
    "liquor_yield_percent": 80,
    "bar_mass_g": 70,
}
ALLOWLIST = [
    "passport_id", "product_name", "batch_number", "origins", "producer_name",
    "harvest_year", "cacao_percentage", "certification_statement",
    "production_start", "production_completed", "shipment_date",
]
APP_ALLOWLIST = [
    "passportId", "productName", "batchNumber", "country", "region", "producerName",
    "harvestYear", "cacaoPercentage", "certificationStatus", "productionDate",
    "shipmentDate", "generatedAt",
]
CSV_FIELDS = [
    "origin_passport_id", "product_name", "batch_number", "country", "growing_region",
    "producer_name", "harvest_year", "cacao_percentage", "certification_status",
    "production_date", "shipment_date",
]


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def validate(data, source_manifest):
    errors = []

    def require(condition, code, detail):
        if not condition:
            errors.append(f"{code}: {detail}")

    rows = data["records"]
    lookup = {r["id"]: r for r in rows}
    require(len(lookup) == len(rows), "ids", "duplicate record ID")
    source_ids = {s["id"] for s in source_manifest["sources"] + source_manifest["capability_sources"]}
    by_kind = defaultdict(list)
    for row in rows:
        by_kind[row["kind"]].append(row)
        require(row["id"].startswith("V2-"), "ids", row["id"])
        require(row["basis"] in {"synthetic_scenario", "synthetic_policy", "synthetic_requirement_model",
                                "requirement_reference", "app_capability"}, "basis", row["id"])
        require(set(row["source_refs"]) <= source_ids, "source", row["id"])
        require(row["synthetic"] == (row["basis"] != "app_capability"), "basis", row["id"])

        def refs(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key.endswith("_id") and item is not None:
                        require(item in lookup, "reference", f"{row['id']}.{key} -> {item}")
                    elif key.endswith("_ids"):
                        require(all(x in lookup for x in item), "reference", f"{row['id']}.{key}")
                    elif key != "snapshot":
                        refs(item)
            elif isinstance(value, list):
                for item in value:
                    refs(item)

        refs({k: v for k, v in row.items() if k != "id"})
    if any(e.startswith("reference:") for e in errors) or len(lookup) != len(rows):
        return errors

    def typed(identifier, kind):
        row = lookup[identifier]
        require(row["kind"] == kind, "reference_type", f"{identifier} should be {kind}")
        return row

    def after_or_equal(earlier, later, code, detail):
        require(earlier is not None and later is not None and earlier <= later, code, detail)

    for row in rows:
        for key, value in row.items():
            if key in {"date", "opened", "closed", "receipt_date", "dispatch_date", "harvest_start",
                       "harvest_end", "fermentation_start", "fermentation_end", "drying_end",
                       "bean_dispatch", "release_date", "recheck_date", "production_start",
                       "production_completed", "quality_date", "approved_date", "received_date",
                       "issued_at"} and value is not None:
                try:
                    if key == "issued_at":
                        datetime.fromisoformat(value.replace("Z", "+00:00"))
                    else:
                        date.fromisoformat(value)
                    require(value[:10] <= data["as_of"], "chronology", f"{row['id']}.{key} beyond snapshot")
                except ValueError:
                    errors.append(f"date: {row['id']}.{key} invalid")
        for key, value in row.items():
            if key.endswith("_g") and key not in {"delta_g", "planned_recipe_g"}:
                require(isinstance(value, int) and not isinstance(value, bool) and value >= 0,
                        "quantity", f"{row['id']}.{key}")
    for lot in by_kind["lot"]:
        sequence = [lot[k] for k in ["harvest_start", "harvest_end", "fermentation_start",
                                     "fermentation_end", "drying_end", "bean_dispatch", "receipt_date"]]
        require(sequence == sorted(sequence), "chronology", lot["id"])
        if lot["release_date"]:
            after_or_equal(lot["receipt_date"], lot["release_date"], "chronology", lot["id"])
        require(sum(f["wet_beans_g"] for f in lot["farm_inputs"]) == lot["wet_beans_g"],
                "postharvest_mass", lot["id"])
        require(lot["wet_beans_g"] == lot["packed_g"] + lot["postharvest_outflow_g"],
                "postharvest_mass", lot["id"])
        require(lot["packed_g"] == lot["received_g"] + lot["transit_loss_g"], "custody_mass", lot["id"])
        require(lot["received_g"] == lot["water_removed_g"] + lot["destructive_sample_g"] + lot["usable_g"],
                "bean_mass", lot["id"])
        require(set(lot["farm_ids"]) == {f["farm_id"] for f in lot["farm_inputs"]},
                "farm_scope", lot["id"])
        for farm_id in lot["farm_ids"]:
            farm = typed(farm_id, "farm")
            require(farm["cooperative_id"] == lot["cooperative_id"] and farm["origin_id"] == lot["origin_id"],
                    "farm_scope", lot["id"])
        if lot["water_removed_g"]:
            nonwater_before = lot["received_g"] * (1 - lot["initial_moisture_percent"] / 100)
            nonwater_after = (lot["received_g"]-lot["water_removed_g"]) * (1-lot["final_moisture_percent"]/100)
            require(abs(nonwater_after-nonwater_before) <= POLICY["mass_tolerance_g"],
                    "moisture_mass", lot["id"])
            require(lot["initial_moisture_percent"] > POLICY["moisture_limit_percent"],
                    "moisture_hold", lot["id"])
        require(lot["disposition"] == "rejected" or
                (lot["release_date"] and lot["final_moisture_percent"] <= POLICY["moisture_limit_percent"]),
                "bean_release", lot["id"])
    for transfer in by_kind["custody"]:
        lot = typed(transfer["lot_id"], "lot")
        require(transfer["from_id"] == lot["cooperative_id"] and transfer["to_id"] == "V2-COCO",
                "custody_owner", transfer["id"])
        require(transfer["dispatched_g"] == lot["packed_g"] and transfer["received_g"] == lot["received_g"]
                and transfer["loss_g"] == lot["transit_loss_g"], "custody_mass", transfer["id"])
        require(transfer["dispatch_date"] == lot["bean_dispatch"] and
                transfer["receipt_date"] == lot["receipt_date"], "chronology", transfer["id"])
    for quality in by_kind["quality_check"]:
        lot = typed(quality["lot_id"], "lot")
        require(quality["moisture_result"] == ("hold" if quality["moisture_percent"] > quality["limit_percent"] else "pass"),
                "quality_status", quality["id"])
        require(quality["final_decision"] == lot["disposition"], "quality_status", quality["id"])
        if lot["disposition"] == "released":
            require(quality["release_date"] and quality["recheck_percent"] <= quality["limit_percent"]
                    and quality["sensory_result"] == "pass", "quality_status", quality["id"])
    for observation in by_kind["field_observation"]:
        lot = typed(observation["lot_id"], "lot")
        require(lot["fermentation_start"] <= observation["date"] <= lot["fermentation_end"],
                "chronology", observation["id"])
        require(isinstance(observation["box_center_temperature_c"], (int, float)),
                "quantity", observation["id"])
    for batch in by_kind["batch"]:
        require(batch["bean_input_g"] == sum(x["quantity_g"] for x in batch["lot_inputs"]),
                "conversion_mass", batch["id"])
        require(batch["bean_input_g"] == sum(batch[k] for k in
                ["roast_loss_g", "shells_g", "bean_process_loss_g", "liquor_g"]), "conversion_mass", batch["id"])
        require(batch["liquor_g"] * 100 == batch["bean_input_g"] * POLICY["liquor_yield_percent"],
                "conversion_yield", batch["id"])
        origin_ids = set()
        for item in batch["lot_inputs"]:
            lot = typed(item["lot_id"], "lot")
            origin_ids.add(lot["origin_id"])
            require(lot["disposition"] == "released", "rejected_consumption", batch["id"])
            after_or_equal(lot["release_date"], batch["production_start"], "chronology", batch["id"])
        require(origin_ids == set(batch["origin_ids"]), "origin_scope", batch["id"])
        require((len(origin_ids) == 1) == (batch["profile"] == "single_origin"), "origin_scope", batch["id"])
        product = typed(batch["product_id"], "product")
        require(set(product["bean_origin_ids"]) == origin_ids, "origin_scope", batch["id"])
        require(product["cacao_percentage"] == batch["cacao_percentage"], "recipe", batch["id"])
        formulated = "conching" in batch["completed_stages"]
        if formulated:
            require(batch["formulated_g"] == batch["liquor_g"] + batch["butter_g"] + batch["sugar_g"],
                    "formulation_mass", batch["id"])
            require(batch["formulated_g"] == batch["processing_loss_g"] + batch["packed_g"] + batch["wip_g"],
                    "finished_mass", batch["id"])
            require((batch["liquor_g"] + batch["butter_g"]) * 100 ==
                    batch["formulated_g"] * batch["cacao_percentage"], "recipe", batch["id"])
        else:
            require(batch["formulated_g"] == batch["butter_g"] == batch["sugar_g"] == batch["packed_g"] == 0
                    and batch["wip_g"] == batch["liquor_g"], "wip", batch["id"])
            plan = product["planned_recipe_g"]
            require((plan["liquor"]+plan["butter"]) * 100 ==
                    sum(plan.values()) * batch["cacao_percentage"], "recipe", batch["id"])
        require(batch["packed_g"] == batch["bars"] * POLICY["bar_mass_g"], "bar_mass", batch["id"])
        events = [e for e in by_kind["production_event"] if e["batch_id"] == batch["id"]]
        require({e["stage"] for e in events} == set(batch["completed_stages"]) and
                len(events) == len(batch["completed_stages"]), "stages", batch["id"])
        stage_order = ["roasting", "grinding", "conching", "tempering", "packaging"]
        require(batch["completed_stages"] == stage_order[:len(batch["completed_stages"])], "stages", batch["id"])
        ordered = sorted(events, key=lambda e: stage_order.index(e["stage"]))
        require([e["date"] for e in ordered] == sorted(e["date"] for e in ordered), "chronology", batch["id"])
        for event in events:
            after_or_equal(batch["production_start"], event["date"], "chronology", event["id"])
            if batch["production_completed"]:
                after_or_equal(event["date"], batch["production_completed"], "chronology", event["id"])
        if batch["status"] in {"ready", "shipped"}:
            require(batch["production_completed"] and batch["quality_state"] == "released" and
                    "packaging" in batch["completed_stages"], "eligibility", batch["id"])
            after_or_equal(batch["production_completed"], batch["quality_date"], "chronology", batch["id"])
        else:
            require(batch["packed_g"] == 0 and batch["production_completed"] is None and
                    batch["quality_state"] == "pending", "eligibility", batch["id"])

    accounts = {r["id"]: r for r in by_kind["inventory_account"]}
    per_account = defaultdict(list)
    for movement in by_kind["inventory_movement"]:
        typed(movement["account_id"], "inventory_account")
        require(isinstance(movement["delta_g"], int) and movement["unit"] == "g", "quantity", movement["id"])
        per_account[movement["account_id"]].append(movement)
    for identifier, account in accounts.items():
        daily = defaultdict(int)
        for movement in per_account[identifier]:
            daily[movement["date"]] += movement["delta_g"]
        balance = 0
        for day in sorted(daily):
            balance += daily[day]
            require(balance >= 0, "inventory_negative", identifier + " on " + day)
        require(balance == account["balance_g"], "inventory_balance", identifier)
    for lot in by_kind["lot"]:
        consumed = sum(item["quantity_g"] for b in by_kind["batch"]
                       for item in b["lot_inputs"] if item["lot_id"] == lot["id"])
        disposed = sum(d["quantity_g"] for d in by_kind["disposition"] if d["lot_id"] == lot["id"])
        suffix = lot["id"].removeprefix("V2-L-")
        require(lot["usable_g"] == consumed + disposed + accounts["V2-AC-BEAN-" + suffix]["balance_g"],
                "bean_allocation", lot["id"])
    for ingredient in by_kind["ingredient_lot"]:
        field = "butter_g" if ingredient["id"] == "V2-BUTTER" else "sugar_g"
        require(ingredient["received_g"] == sum(b[field] for b in by_kind["batch"]) +
                accounts["V2-AC-" + ingredient["id"].removeprefix("V2-")]["balance_g"],
                "ingredient_balance", ingredient["id"])
    for batch in by_kind["batch"]:
        suffix = batch["id"].removeprefix("V2-B-")
        retained = accounts.get("V2-AC-RETAIN-" + suffix, {}).get("balance_g", 0)
        dispatched = sum(s["dispatched_g"] for s in by_kind["shipment"] if s["batch_id"] == batch["id"])
        require(batch["packed_g"] == retained + dispatched + accounts["V2-AC-FIN-" + suffix]["balance_g"],
                "finished_inventory", batch["id"])

    expected_roles = {"origin_facts": "sourcing_owner", "bean_quality": "quality_reviewer",
                      "finished_quality": "quality_reviewer", "certification_wording": "quality_reviewer",
                      "shipment_eligibility": "wholesale_operator",
                      "producer_display_correction": "sourcing_owner"}
    for approval in by_kind["approval"]:
        actor = typed(approval["actor_id"], "actor")
        require(actor["role"] == expected_roles[approval["scope"]], "approval_role", approval["id"])
        require(approval["decision"] in {"approved", "pending", "rejected"}, "approval", approval["id"])
        if approval["decision"] == "approved":
            require(approval["date"] is not None, "approval", approval["id"])
    for batch in by_kind["batch"]:
        decisions = [a for a in by_kind["approval"] if a["subject_id"] == batch["id"] and
                     a["scope"] == "finished_quality"]
        require(len(decisions) == 1, "approval_consistency", batch["id"])
        if decisions:
            require(decisions[0]["date"] == batch["quality_date"] and
                    (decisions[0]["decision"] == "approved") == (batch["quality_state"] == "released"),
                    "approval_consistency", batch["id"])
    for rework in by_kind["rework"]:
        batch = typed(rework["batch_id"], "batch")
        require(rework["input_g"] == rework["returned_g"]+rework["loss_g"] and rework["new_output_g"] == 0,
                "rework_mass", rework["id"])
        require(rework["input_g"] <= batch["formulated_g"], "rework_mass", rework["id"])
        require(typed(rework["approval_actor_id"], "actor")["role"] == "quality_reviewer",
                "approval_role", rework["id"])
        after_or_equal(batch["production_start"], rework["date"], "chronology", rework["id"])
        after_or_equal(rework["date"], batch["production_completed"], "chronology", rework["id"])
    for cert in by_kind["certificate"]:
        require(cert["valid_from"] <= cert["valid_until"], "certificate_period", cert["id"])
        for farm in cert["farm_ids"]:
            require(typed(farm, "farm")["cooperative_id"] == cert["holder_id"], "certificate_scope", cert["id"])
    for claim in by_kind["claim"]:
        batch = typed(claim["batch_id"], "batch")
        if claim["status"] == "approved":
            require(claim["certificate_id"] is not None and claim["approved_date"] is not None,
                    "certificate_claim", claim["id"])
            if claim["certificate_id"] is None or claim["approved_date"] is None:
                continue
            cert = typed(claim["certificate_id"], "certificate")
            require(cert["status"] == "active" and cert["approved_wording"] == claim["wording"],
                    "certificate_claim", claim["id"])
            for item in batch["lot_inputs"]:
                lot = typed(item["lot_id"], "lot")
                require(lot["id"] in cert["lot_ids"] and set(lot["farm_ids"]) <= set(cert["farm_ids"]) and
                        lot["cooperative_id"] == cert["holder_id"], "certificate_scope", claim["id"])
                for day in [lot["harvest_start"], lot["harvest_end"], lot["bean_dispatch"], claim["approved_date"]]:
                    require(cert["valid_from"] <= day <= cert["valid_until"], "certificate_period", claim["id"])
        elif claim["status"] == "pending":
            require(claim["approved_date"] is None and
                    typed(claim["certificate_id"], "certificate")["status"] == "pending",
                    "certificate_claim", claim["id"])
        else:
            require(claim["status"] == "no_claim" and claim["certificate_id"] is None,
                    "certificate_claim", claim["id"])
    for order in by_kind["order"]:
        if order["status"] in {"blocked_format", "cancelled"}:
            require(order["batch_id"] is None and order["allocation_g"] == 0 and
                    not any(s["order_id"] == order["id"] for s in by_kind["shipment"]),
                    "order_allocation", order["id"])
    for shipment in by_kind["shipment"]:
        batch = typed(shipment["batch_id"], "batch")
        order = typed(shipment["order_id"], "order")
        require(batch["status"] == "shipped" and batch["quality_state"] == "released",
                "eligibility", shipment["id"])
        after_or_equal(batch["quality_date"], shipment["dispatch_date"], "chronology", shipment["id"])
        after_or_equal(shipment["dispatch_date"], shipment["receipt_date"], "chronology", shipment["id"])
        require(shipment["recipient_id"] == order["recipient_id"] and order["batch_id"] == batch["id"],
                "recipient", shipment["id"])
        require(shipment["dispatched_g"] == order["allocation_g"] == order["requested_g"],
                "order_allocation", shipment["id"])
        require(shipment["dispatched_g"] == shipment["accepted_g"] + shipment["damaged_g"],
                "receipt_mass", shipment["id"])
        require(shipment["dispatched_g"] % POLICY["bar_mass_g"] == 0 and
                shipment["damaged_g"] % POLICY["bar_mass_g"] == 0, "bar_mass", shipment["id"])
        decisions = [a for a in by_kind["approval"] if a["subject_id"] == shipment["id"] and
                     a["scope"] == "shipment_eligibility"]
        require(len(decisions) == 1 and decisions[0]["decision"] == "approved" and
                decisions[0]["date"] <= shipment["dispatch_date"], "approval_consistency", shipment["id"])
    for batch in by_kind["batch"]:
        require((batch["status"] == "shipped") ==
                any(s["batch_id"] == batch["id"] for s in by_kind["shipment"]),
                "eligibility", batch["id"])
    passports = {p["id"]: p for p in by_kind["passport"]}
    children = defaultdict(list)
    for passport in passports.values():
        shipment = typed(passport["shipment_id"], "shipment")
        batch = typed(passport["batch_id"], "batch")
        auth = typed(passport["authorization_id"], "sharing_authorization")
        snapshot = passport["snapshot"]
        require(passport["basis"] == "synthetic_requirement_model", "basis", passport["id"])
        require(set(snapshot) == set(ALLOWLIST) and set(snapshot) <= set(auth["fields"]),
                "allowlist", passport["id"])
        require(auth["decision"] == "approved" and auth["purpose"] == "wholesale_origin_traceability"
                and auth["channel"] == "demo_partner_portal", "sharing", passport["id"])
        require(passport["recipient_id"] == auth["recipient_id"] == shipment["recipient_id"] and
                auth["subject_id"] == shipment["id"] and shipment["batch_id"] == batch["id"],
                "recipient", passport["id"])
        day = passport["issued_at"][:10]
        require(auth["date"] <= day <= auth["expires"], "sharing_period", passport["id"])
        after_or_equal(shipment["dispatch_date"], day, "chronology", passport["id"])
        require(passport["snapshot_sha256"] == digest(encoded(snapshot)),
                "snapshot_hash", passport["id"])
        product = typed(batch["product_id"], "product")
        lot = typed(batch["lot_inputs"][0]["lot_id"], "lot")
        origin = typed(lot["origin_id"], "origin")
        claim = next(c for c in by_kind["claim"] if c["batch_id"] == batch["id"])
        require(claim["status"] == "approved" and claim["approved_date"] <= shipment["dispatch_date"],
                "certificate_claim", passport["id"])
        expected = {
            "passport_id": passport["id"], "product_name": product["name"],
            "batch_number": batch["batch_number"],
            "origins": [{"country": origin["country"], "region": origin["region"]}],
            "harvest_year": int(lot["harvest_start"][:4]),
            "cacao_percentage": batch["cacao_percentage"], "certification_statement": claim["wording"],
            "production_start": batch["production_start"], "production_completed": batch["production_completed"],
            "shipment_date": shipment["dispatch_date"],
        }
        require(all(snapshot.get(k) == v for k, v in expected.items()), "snapshot_facts", passport["id"])
        if passport["supersedes_id"]:
            prior = typed(passport["supersedes_id"], "passport")
            children[prior["id"]].append(passport["id"])
            require(passport["version"] == prior["version"] + 1 and
                    passport["batch_id"] == prior["batch_id"] and
                    passport["shipment_id"] == prior["shipment_id"] and
                    passport["recipient_id"] == prior["recipient_id"], "lineage", passport["id"])
            require(prior["issued_at"] < passport["issued_at"], "lineage", passport["id"])
            correction = typed(passport["correction_approval_id"], "approval")
            require(correction["decision"] == "approved" and correction["scope"] == "producer_display_correction"
                    and correction["date"] <= day and correction["subject_id"] == lot["cooperative_id"]
                    and correction["approved_value"] == snapshot["producer_name"]
                    and correction["original_value"] == prior["snapshot"]["producer_name"],
                    "lineage_approval", passport["id"])
            changed = {k for k in snapshot if snapshot[k] != prior["snapshot"].get(k)}
            require(changed == {"passport_id", "producer_name"}, "lineage_delta", passport["id"])
        else:
            require(passport["version"] == 1 and snapshot["producer_name"] ==
                    typed(lot["cooperative_id"], "organization")["name"], "lineage", passport["id"])
    for passport in passports.values():
        require(len(children[passport["id"]]) <= 1 and
                passport["lifecycle"] == ("superseded" if children[passport["id"]] else "current"),
                "lineage", passport["id"])
    for case in by_kind["case"]:
        if case["closed"]:
            after_or_equal(case["opened"], case["closed"], "chronology", case["id"])
        require(case["status"] == ("closed" if case["closed"] else "open"), "case_status", case["id"])
    capability = lookup["V2-CAPABILITY"]
    require(capability["app_fields"] == APP_ALLOWLIST and capability["implemented_format"] == "JSON"
            and capability["csv"] == "not implemented" and not capability["synthetic"],
            "capability", capability["id"])
    contract = lookup["V2-CONTRACT-MP"]
    require(contract["fields"] == CSV_FIELDS and contract["shipment_id"] is None and
            contract["production_date_meaning"] == "finished production completion",
            "contract", contract["id"])
    for source in source_manifest["sources"]:
        require(source.get("licence") and source.get("url", "").startswith("https://"),
                "attribution", source["id"])
        if source["status"] == "consulted_not_used":
            require(not source["adopted_facts"], "attribution", source["id"])
    return errors


def local_path(root, relative):
    path = (root / relative.replace("\\", "/")).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"Missing or non-local file: {relative}")
    return path


def render_binding(value, format_name):
    if format_name == "kg":
        return f"{value / 1000:,.3f}".rstrip("0").rstrip(".")
    if format_name == "json" or isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if format_name is not None:
        raise ValueError(f"Unknown binding format: {format_name}")
    return str(value) if value is not None else "not recorded"


def check_documents(data, sources, manifest, pdfs=False):
    errors = []
    lookup = {r["id"]: r for r in data["records"]}
    source_ids = {s["id"] for s in sources["sources"] + sources["capability_sources"]}
    require = lambda ok, detail: None if ok else errors.append("content: " + detail)
    require(len({d["id"] for d in manifest}) == len(manifest), "duplicate document ID")
    require(len({d["title"] for d in manifest}) == len(manifest), "duplicate title")
    require(len({d["genre"] for d in manifest}) >= 15, "insufficient genre diversity")
    require(len({d["path"] for d in manifest}) == len(manifest), "duplicate document path")
    require(len({d["sha256"] for d in manifest}) == len(manifest), "duplicate document bytes")
    if pdfs:
        try:
            import pymupdf
        except ImportError as error:
            raise RuntimeError(
                "PDF checks require PyMuPDF. Install scripts/requirements-sample-validation.txt "
                "from the documented Microsoft CFS feed."
            ) from error
    for document in manifest:
        identifier = document["id"]
        path = local_path(DATA_ROOT, document["path"])
        require(path.suffix == ".pdf", identifier + " must select a finished PDF")
        require(digest(path.read_bytes()) == document["sha256"], identifier + " PDF hash drift")
        require(document["synthetic"] is True, identifier + " missing synthetic metadata")
        require(set(document["record_ids"]) <= lookup.keys(), identifier + " dangling record link")
        require(set(document["source_refs"]) <= source_ids, identifier + " dangling source link")
        require(document["authoring_source"]["included"] is False, identifier + " authoring source included")
        for binding in document.get("bindings", []):
            value = lookup[binding["record_id"]][binding["field"]]
            require(render_binding(value, binding["format"]) == binding["rendered_value"],
                    identifier + " stale canonical binding")
        for record_id, fields in document.get("fact_expectations", {}).items():
            require(all(lookup[record_id].get(key) == value for key, value in fields.items()),
                    identifier + " stale case facts for " + record_id)
        if not pdfs:
            continue
        with pymupdf.open(path) as pdf:
            require(len(pdf) == document["pages"], identifier + " wrong page count")
            text = "".join(page.get_text() for page in pdf)
            compact = re.sub(r"\s+", "", text)
            for binding in document.get("bindings", []) + document.get("display_fact_bindings", []):
                require(re.sub(r"\s+", "", binding["rendered_value"]) in compact,
                        identifier + " PDF missing bound value " + binding["field"])
            uris = []
            for page in pdf:
                require(bool(page.get_text().strip()), identifier + " non-selectable page")
                require(abs(page.rect.width - 595.2756) < 0.1 and
                        abs(page.rect.height - 841.8898) < 0.1, identifier + " not A4 portrait")
                for link in page.get_links():
                    if link["kind"] == pymupdf.LINK_URI:
                        uri = link.get("uri", "")
                        require(urlparse(uri).scheme in {"https", "http"}, identifier + " unsafe hyperlink")
                        uris.append(uri)
                    else:
                        require(link["kind"] == pymupdf.LINK_GOTO and
                                0 <= link.get("page", -1) < len(pdf), identifier + " broken internal hyperlink")
                for font in page.get_fonts():
                    if font[3] not in {"Helvetica", "Times-Roman", "Courier"}:
                        require(bool(pdf.extract_font(font[0])[3]), identifier + " unembedded font")
                if identifier.startswith("D"):
                    require("Fictional sample data" in page.get_text(), identifier + " missing fiction footer")
            for source_id in document["source_refs"]:
                source = next(s for s in sources["sources"] + sources["capability_sources"]
                              if s["id"] == source_id)
                url = source.get("url")
                require(url is not None and url in uris, identifier + " missing source hyperlink " + source_id)
    used_records = {r for d in manifest for r in d["record_ids"]}
    require(all(r["id"] in used_records for r in data["records"] if r["kind"] in
                {"lot", "batch", "shipment", "passport", "certificate", "order", "case"}),
            "an operational storyline lacks a document")
    return errors


def check_lab_selection():
    # Exercise the real loader without importing its Azure clients or loading .env.
    source = REPO_ROOT / "infra" / "create-index-snapshots.py"
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    function = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == "load_corpora")
    counts = next(ast.literal_eval(node.value) for node in tree.body
                  if isinstance(node, ast.Assign) and
                  any(isinstance(target, ast.Name) and target.id == "CORPUS_COUNTS"
                      for target in node.targets))
    namespace = {
        "json": json, "Path": Path, "DATA_ROOT": DATA_ROOT,
        "CORPORA_PATH": DATA_ROOT / "corpora.json", "CORPUS_COUNTS": counts,
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
    selected = namespace["load_corpora"]()
    return {name: len(paths) for name, paths in selected.items()}


def check_import(frozen=False):
    inventory = json.loads((DATA_ROOT / "sample-data-import.json").read_text(encoding="utf-8"))
    errors = []
    for relative, expected in inventory["canonical_files"].items():
        content = local_path(REPO_ROOT, relative).read_bytes()
        normalized = inventory.get("canonical_text_hashes", {}).get(relative)
        if digest(content) != expected and (
            normalized is None or digest(content.replace(b"\r\n", b"\n")) != normalized
        ):
            errors.append("baseline: changed canonical file " + relative)
    if frozen:
        for item in inventory["files"]:
            if digest(local_path(REPO_ROOT, item["path"]).read_bytes()) != item["source_sha256"]:
                errors.append("import: changed source bytes " + item["path"])
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", action="store_true", help="Also parse PDF text, fonts and hyperlinks locally")
    parser.add_argument("--frozen", action="store_true", help="Verify original imported bytes before development")
    args = parser.parse_args()
    data = json.loads((DATA_ROOT / "records.json").read_text(encoding="utf-8"))
    sources = json.loads((DATA_ROOT / "sample-sources.json").read_text(encoding="utf-8"))
    manifest = json.loads((DATA_ROOT / "document-manifest.json").read_text(encoding="utf-8"))
    errors = validate(data, sources) + check_documents(data, sources, manifest, args.pdf) + check_import(args.frozen)
    selected = check_lab_selection()
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"PASS: {len(data['records'])} records, {len(manifest)} finished PDFs; "
          f"lab selections {selected}; PDF parsing={args.pdf}; frozen import={args.frozen}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
