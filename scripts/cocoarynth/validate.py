"""Validate the Cocoarynth world data and the facts each lab mystery depends on.

Usage: .venv-cocoarynth/bin/python scripts/cocoarynth/validate.py
"""

import json
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import yaml

DATA = Path(__file__).resolve().parents[2] / "data" / "cocoarynth"
errors: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def d(value: str) -> date:
    return date.fromisoformat(value[:10])


def by_id(items: list[dict], label: str) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for item in items:
        check(item["id"] not in index, f"duplicate {label} id {item['id']}")
        index[item["id"]] = item
    return index


def main() -> None:
    w = {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in sorted((DATA / "world").glob("*.json"))}
    company, origins_doc, beans, production, retail, sensory, commercial = (
        w["company"], w["origins"], w["beans"], w["production"], w["retail"], w["sensory"], w["commercial"]
    )

    people = by_id(company["people"], "person")
    partners = by_id(company["partners"], "partner")
    sites = by_id(company["sites"], "site")
    suppliers = by_id(origins_doc["suppliers"], "supplier")
    origins = by_id(origins_doc["origins"], "origin")
    farms = by_id(origins_doc["farms"], "farm")
    certs = by_id(origins_doc["certifications"], "certification")
    inspections = by_id(origins_doc["inspections"], "inspection")
    tickets = by_id(beans["collection_tickets"], "ticket")
    consignments = by_id(beans["consignments"], "consignment")
    lots = by_id(beans["lots"], "lot")
    products = by_id(production["products"], "product")
    batches = by_id(production["batches"], "batch")
    retailers = by_id(retail["retailers"], "retailer")
    shipments = by_id(retail["shipments"], "shipment")
    loggers = by_id(retail["loggers"], "logger")
    cases = by_id(retail["cases"], "case")
    orgs = {"cocoarynth"} | set(suppliers) | set(partners) | set(retailers)
    limits = beans["receiving_limits"]

    # References
    for person in people.values():
        check(person["org"] in orgs, f"person {person['id']}: unknown org {person['org']}")
    for site in sites.values():
        check(site["org"] in orgs, f"site {site['id']}: unknown org")
        check(site.get("parent") in (None, *sites), f"site {site['id']}: unknown parent")
    for supplier in suppliers.values():
        check(supplier["contact"] in people, f"supplier {supplier['id']}: unknown contact")
    for origin in origins.values():
        check(origin["supplier"] in suppliers, f"origin {origin['id']}: unknown supplier")
    for farm in farms.values():
        check(farm["origin"] in origins, f"farm {farm['id']}: unknown origin")
        check(farm["farmer"] in people, f"farm {farm['id']}: unknown farmer")
    for cert in certs.values():
        check(cert["supplier"] in suppliers, f"cert {cert['id']}: unknown supplier")
        check(cert["certifier"] in (None, *partners), f"cert {cert['id']}: unknown certifier")
    for insp in inspections.values():
        check(insp["supplier"] in suppliers, f"inspection {insp['id']}: unknown supplier")
        check(insp["inspector"] in people, f"inspection {insp['id']}: unknown inspector")
        for farm_id in insp["farms"]:
            check(farms.get(farm_id, {}).get("origin") in [o["id"] for o in origins.values() if o["supplier"] == insp["supplier"]],
                  f"inspection {insp['id']}: farm {farm_id} not supplied by {insp['supplier']}")
        for finding in insp["findings"]:
            check(finding["farm"] in insp["farms"], f"finding {finding['id']}: farm not in inspection")
            if finding.get("due"):
                check(d(finding["due"]) >= d(insp["date"]), f"finding {finding['id']}: due before inspection")
            if finding.get("closed"):
                check(d(finding["closed"]) >= d(insp["date"]), f"finding {finding['id']}: closed before inspection")

    # Bean lots
    ticket_kg: dict[tuple[str, str], float] = defaultdict(float)
    for ticket in tickets.values():
        check(ticket["farm"] in farms and ticket["lot"] in lots and ticket["received_by"] in people,
              f"ticket {ticket['id']}: bad reference")
        ticket_kg[(ticket["lot"], ticket["farm"])] += ticket["wet_kg"]
    for cn in consignments.values():
        check(cn["forwarder"] in partners and cn["importer"] in partners, f"consignment {cn['id']}: bad partner")
        check(d(cn["departed"]) < d(cn["arrived"]) <= d(cn["factory_receipt"]), f"consignment {cn['id']}: dates out of order")
        for lot_id in cn["lots"]:
            check(lots.get(lot_id, {}).get("consignment") == cn["id"], f"consignment {cn['id']}: lot {lot_id} mismatch")

    available: dict[str, float] = {}
    for lot in lots.values():
        lid = lot["id"]
        check(lot["origin"] in origins, f"lot {lid}: unknown origin")
        wet = sum(c.get("wet_kg", 0) for c in lot["contributions"])
        dried_parts = sum(c.get("dried_kg", 0) for c in lot["contributions"])
        for c in lot["contributions"]:
            check(farms.get(c["farm"], {}).get("origin") == lot["origin"], f"lot {lid}: farm {c['farm']} from another origin")
            if "wet_kg" in c and any(t["lot"] == lid for t in tickets.values()):
                check(ticket_kg[(lid, c["farm"])] == c["wet_kg"], f"lot {lid}: tickets for {c['farm']} don't sum to {c['wet_kg']} kg")
        if wet:
            check(0.33 * wet <= lot["dried_kg"] <= 0.45 * wet, f"lot {lid}: dried/wet ratio implausible")
        if dried_parts:
            check(abs(dried_parts - lot["dried_kg"]) < 0.01, f"lot {lid}: contributions don't sum to dried_kg")
        check(lot["received_kg"] <= lot["dried_kg"], f"lot {lid}: received more than dispatched")

        steps = []
        if "fermentation" in lot:
            steps += [lot["fermentation"]["start"], lot["fermentation"]["end"]]
        if "drying" in lot:
            steps += [lot["drying"]["start"], lot["drying"]["end"]]
        steps.append(lot["dispatched"])
        if lot.get("consignment"):
            cn = consignments[lot["consignment"]]
            check(d(lot["dispatched"]) <= d(cn["departed"]), f"lot {lid}: dispatched after vessel departed")
            steps.append(cn["factory_receipt"])
        elif lot.get("received"):
            steps.append(lot["received"])
        check(all(d(a) <= d(b) for a, b in zip(steps, steps[1:])), f"lot {lid}: process dates out of order")
        received = d(steps[-1])

        moisture = [t for t in lot["tests"] if t["type"] == "moisture"]
        sensory_tests = [t for t in lot["tests"] if t["type"] == "sensory_check"]
        for test in lot["tests"]:
            check(d(test["date"]) >= received, f"lot {lid}: test before receipt")
            if test["type"] == "moisture":
                expected = "pass" if test["value_pct"] <= limits["moisture_max_pct"] else "fail"
                check(test["result"] == expected, f"lot {lid}: moisture {test['value_pct']} marked {test['result']}")
            if test["type"] == "cut_test":
                categories = ["well_fermented", "partly_fermented", "slaty", "purple", "mouldy", "insect_damaged", "germinated", "flat"]
                check(sum(test[k] for k in categories) == test["beans"], f"lot {lid}: cut test doesn't sum to {test['beans']}")
                ok = (100 * test["mouldy"] / test["beans"] <= limits["mouldy_max_pct"]
                      and 100 * test["slaty"] / test["beans"] <= limits["slaty_max_pct"]
                      and 100 * test["insect_damaged"] / test["beans"] <= limits["insect_damaged_max_pct"])
                check(test["result"] == ("pass" if ok else "fail"), f"lot {lid}: cut test result inconsistent")
        if lot["status"] in ("released", "sample_approved"):
            check(bool(moisture) and moisture[-1]["result"] == "pass", f"lot {lid}: released without passing moisture")
            check(bool(sensory_tests) and sensory_tests[-1]["result"] == "pass", f"lot {lid}: released without passing sensory")
            check(all(d(t["date"]) <= d(lot["released"]) for t in lot["tests"]), f"lot {lid}: tests after release")
        if lot["status"] == "rejected":
            check(any(t["result"] == "fail" for t in lot["tests"]), f"lot {lid}: rejected without a failed test")
        if "hold" in lot:
            check(d(lot["hold"]["opened"]) <= d(lot["hold"]["closed"]) <= d(lot["released"]), f"lot {lid}: hold dates out of order")
            first, last = moisture[0]["value_pct"], moisture[-1]["value_pct"]
            expected_mass = lot["received_kg"] * (1 - first / 100) / (1 - last / 100)
            check(abs(expected_mass - lot["mass_after_redry_kg"]) < 0.1, f"lot {lid}: re-dry mass should be {expected_mass:.1f}")
            checks = [value for _, value in lot.get("redry_checks", [])]
            check(checks and checks[0] == first and checks[-1] == last and checks == sorted(checks, reverse=True),
                  f"lot {lid}: re-dry checks must fall from {first} to {last}")
        available[lid] = lot.get("mass_after_redry_kg", lot["received_kg"]) - lot["sample_kg"]

    # Production
    process = production["process"]
    used: dict[str, float] = defaultdict(float)
    for product in products.values():
        check(product["origin"] in origins, f"product {product['id']}: unknown origin")
    for batch in batches.values():
        bid = batch["id"]
        product = products.get(batch["product"])
        check(product is not None, f"batch {bid}: unknown product")
        if product is None:
            continue
        kg = 0.0
        for item in batch["inputs"]:
            lot = lots.get(item["lot"])
            check(lot is not None and lot["origin"] == product["origin"], f"batch {bid}: input lot {item['lot']} wrong origin")
            if lot:
                check(lot["status"] == "released" and d(lot["released"]) <= d(batch["production_date"]),
                      f"batch {bid}: uses lot {lot['id']} before release")
            used[item["lot"]] += item["kg"]
            kg += item["kg"]
        check(d(batch["production_date"]) <= d(batch["packed"]), f"batch {bid}: packed before production")
        ceiling = kg * process["nib_yield"] / (product["cocoa_pct"] / 100) * (1 - process["packing_loss"]) / 0.070
        check(0.95 * ceiling <= batch["bars"] <= ceiling, f"batch {bid}: {batch['bars']} bars implausible (max {ceiling:.0f})")
        if batch["organic_claim"]:
            supplier = origins[product["origin"]]["supplier"]
            valid = [c for c in certs.values() if c["supplier"] == supplier and c["valid_from"]
                     and d(c["valid_from"]) <= d(batch["packed"]) <= d(c["valid_until"])]
            check(bool(valid), f"batch {bid}: organic claim without a valid certificate on the packing date")
    for lot_id, kg in used.items():
        check(kg <= available[lot_id] + 1e-6, f"lot {lot_id}: batches use {kg} kg but only {available[lot_id]} kg available")

    # Shipments and sales
    shipped: dict[str, int] = defaultdict(int)
    sell_in = commercial["sell_in_units_2026"]
    for shipment in shipments.values():
        sid = shipment["id"]
        check(shipment["retailer"] in retailers and shipment["carrier"] in partners, f"shipment {sid}: bad reference")
        sent, arrived = datetime.fromisoformat(shipment["dispatched"]), datetime.fromisoformat(shipment["delivered"])
        check(sent < arrived, f"shipment {sid}: delivered before dispatch")
        month = sent.month - 1
        for line in shipment["lines"]:
            batch = batches.get(line["batch"])
            check(batch is not None, f"shipment {sid}: unknown batch {line['batch']}")
            if batch is None:
                continue
            check(d(batch["packed"]) <= sent.date(), f"shipment {sid}: ships {batch['id']} before packing")
            shipped[batch["id"]] += line["bars"]
            series = sell_in["by_product_retailer"].get(batch["product"], {}).get(shipment["retailer"])
            check(series is not None and series[month] >= line["bars"],
                  f"shipment {sid}: sell-in for {batch['product']}/{shipment['retailer']} in month {month + 1} below {line['bars']}")
        for stop in shipment["depot_stops"]:
            check(stop["site"] in sites and stop["position"] in sites and stop["logger"] in loggers, f"shipment {sid}: bad depot stop")
            check(sent < datetime.fromisoformat(stop["arrived"]) <= datetime.fromisoformat(stop["placed"])
                  < datetime.fromisoformat(stop["departed"]) < arrived, f"shipment {sid}: depot times out of order")
    for batch_id, bars in shipped.items():
        batch = batches[batch_id]
        check(bars <= batch["bars"] - batch["retained_bars"], f"batch {batch_id}: ships {bars} bars, more than packed")
    for product_id, by_retailer in sell_in["by_product_retailer"].items():
        check(product_id in products, f"sell-in: unknown product {product_id}")
        for retailer_id, series in by_retailer.items():
            check(retailer_id in retailers and len(series) == len(sell_in["months"]), f"sell-in {product_id}/{retailer_id}: bad series")

    for case in cases.values():
        for key, collection in (("retailer", retailers), ("batch", batches), ("shipment", shipments), ("lot", lots), ("supplier", suppliers)):
            if case.get(key):
                check(case[key] in collection, f"case {case['id']}: unknown {key} {case[key]}")

    # Commercial
    for contract in commercial["contracts"]:
        check(contract["supplier"] in suppliers, f"contract {contract['id']}: unknown supplier")
        origin_id = next(o["id"] for o in origins.values() if o["supplier"] == contract["supplier"])
        check(commercial["prices_landed_usd_kg"][origin_id][str(contract["year"])] == contract["price_landed_usd_kg"],
              f"contract {contract['id']}: price differs from price table")
    for table in ("prices_landed_usd_kg", "purchases_kg"):
        for origin_id in commercial[table]:
            check(origin_id in origins, f"{table}: unknown origin {origin_id}")

    # Sensory
    for panel in sensory["panels"]:
        for sample in panel["samples"]:
            check(sample["product"] in products, f"panel {panel['id']}: unknown product {sample['product']}")
            check(set(sample["scores"]) == set(sensory["attributes"]), f"panel {panel['id']}: sample {sample['code']} attributes mismatch")

    # Mystery facts
    facts = mystery_facts(retail, loggers, lots, batches, products, origins, commercial, sensory)
    for line in facts:
        print("  " + line)

    questions = yaml.safe_load((DATA / "questions.yaml").read_text(encoding="utf-8"))
    collections = {
        "retail.cases": cases, "retail.shipments": shipments, "retail.loggers": loggers, "production.batches": batches,
        "production.products": products, "beans.lots": lots, "origins.inspections": inspections,
        "origins.certifications": certs, "sensory.panels": by_id(sensory["panels"], "panel"),
    }
    for mystery in questions["mysteries"]:
        for ref in mystery["world"]:
            prefix, _, key = ref.rpartition(".")
            if prefix in collections:
                check(key in collections[prefix], f"{mystery['id']}: unresolved world reference {ref}")

    check_briefs(w, questions["mysteries"], orgs | set(people))

    if errors:
        print(f"\n{len(errors)} problem(s):")
        for error in errors:
            print(f"  - {error}")
        sys.exit(1)
    print("\nWorld data is consistent.")


def resolve(world: dict, ref: str) -> bool:
    node = world
    for part in ref.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list):
            node = next((item for item in node if isinstance(item, dict) and item.get("id") == part), None)
            if node is None:
                return False
        else:
            return False
    return True


def check_briefs(world: dict, mysteries: list[dict], authors: set[str]) -> None:
    asset_doc = yaml.safe_load((DATA / "briefs" / "assets.yaml").read_text(encoding="utf-8"))
    assets = {a["name"] for section in asset_doc.values() for a in section}
    for asset in asset_doc["photos"]:
        path = asset.get("path", f"assets/photos/{asset['name']}.png")
        check((DATA / path).is_file(), f"asset {asset['name']}: missing file {path}")
    for asset in asset_doc["charts"] + asset_doc.get("diagrams", []):
        for ref in asset["data"] if isinstance(asset["data"], list) else [asset["data"]]:
            check(resolve(world, ref), f"asset {asset['name']}: unresolved data {ref}")
    for asset in asset_doc["derived"]:
        check(asset["from"] in assets | {"html", "code"}, f"asset {asset['name']}: unknown source {asset['from']}")

    seen: set[str] = set()
    counts: dict[str, int] = {}
    for path in sorted((DATA / "briefs").glob("cocoarynth-*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        index = doc["index"]
        check(path.stem == index, f"{path.name}: index name differs from file name")
        counts[index] = len(doc["briefs"])
        for brief in doc["briefs"]:
            bid = brief["id"]
            check(bid not in seen, f"brief {bid}: duplicate id")
            seen.add(bid)
            check(brief["language"] in ("en", "es"), f"brief {bid}: unsupported language")
            check(brief["author"] in authors, f"brief {bid}: unknown author {brief['author']}")
            check(isinstance(brief["date"], date), f"brief {bid}: date must be YYYY-MM-DD")
            for ref in brief["entities"]:
                check(resolve(world, ref), f"brief {bid}: unresolved entity {ref}")
            for visual in brief["visuals"]:
                check(visual["asset"] in assets, f"brief {bid}: unknown asset {visual['asset']}")

    for mystery in mysteries:
        for n, item in enumerate(mystery["evidence"], start=1):
            label = f"{mystery['id']}.{n}"
            documents = item.get("documents", [])
            check(bool(documents), f"evidence {label} ({item['fact']}) lists no documents")
            for document in documents:
                check(document.endswith(".pdf") and document.removesuffix(".pdf") in seen, f"evidence {label}: unknown document {document}")
            if item.get("part_a_file"):
                check(len(documents) == 1, f"evidence {label}: the Part A file source must be a single document")
    corpora_path = DATA / "corpora.json"
    check(json.loads(corpora_path.read_text(encoding="utf-8")) == expected_corpora(), "corpora.json doesn't match the briefs; rerun render.py")
    print(f"  briefs: {sum(counts.values())} total, " + ", ".join(f"{k} {v}" for k, v in counts.items()))


def expected_corpora() -> dict[str, list[str]]:
    """corpora.json drives lab ingestion: each index's PDFs, plus the Part A file source."""
    corpora: dict[str, list[str]] = defaultdict(list)
    index_of: dict[str, str] = {}
    for path in sorted((DATA / "briefs").glob("cocoarynth-*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for brief in doc["briefs"]:
            index_of[brief["id"]] = doc["index"]
            corpora[doc["index"]].append(f"documents/{doc['index']}/{brief['id']}.pdf")
    mysteries = yaml.safe_load((DATA / "questions.yaml").read_text(encoding="utf-8"))["mysteries"]
    part_a = {name.removesuffix(".pdf") for m in mysteries for e in m["evidence"] if e.get("part_a_file") for name in e["documents"]}
    file_source = sorted(f"documents/{index_of[bid]}/{bid}.pdf" for bid in part_a if bid in index_of)
    return {index: sorted(paths) for index, paths in sorted(corpora.items())} | {"file-source": file_source}


def mystery_facts(retail, loggers, lots, batches, products, origins, commercial, sensory) -> list[str]:
    out = []
    readings = loggers["LOGGER-04"]["readings"]
    risk = retail["storage_guidance"]["bloom_risk_above_c"]
    hot = [time for time, value in readings if value > risk]
    hours = (len(hot) - 1) * loggers["LOGGER-04"]["interval_minutes"] / 60
    peak_time, peak = max(readings, key=lambda r: r[1])
    check(hours == 6.0 and peak == 34.1 and peak_time == "14:30", "M1: logger no longer shows 6 h above 25 °C peaking at 34.1 °C at 14:30")
    out.append(f"M1 logger above {risk} °C {hot[0]}–{hot[-1]} ({hours:g} h), peak {peak} °C at {peak_time}")

    farm_names = [c["farm"] for item in batches["EC26-0811"]["inputs"] for c in lots[item["lot"]]["contributions"]]
    check(farm_names == ["las-brisas", "el-cedro"], "M2: EC26-0811 no longer traces to Las Brisas and El Cedro")
    out.append(f"M2 EC26-0811 farms: {', '.join(farm_names)}")

    mg = lots["MG26-L02"]
    product = products["MGNB"]
    slip = (d(product["launched"]) - d(product["planned_launch"])).days
    check(slip == 30, "M5: launch slip is no longer one month")
    out.append(f"M5 MG26-L02 moisture {[t['value_pct'] for t in mg['tests'] if t['type'] == 'moisture']}; launch slipped {slip} days")

    samples = sensory["panels"][0]["samples"]
    winner = max(samples, key=lambda s: s["overall"])
    check(products[winner["product"]]["origin"] == "madagascar", "M6: Madagascar no longer wins the panel")
    out.append(f"M6 panel winner {winner['product']} {winner['overall']}")

    year = "2026"
    prices = {o: p[year] for o, p in commercial["prices_landed_usd_kg"].items() if year in p}
    priciest = max(prices, key=prices.get)
    margins = {}
    for pid, p in products.items():
        if p["wholesale_usd"] and p["origin"] in prices and pid != "MGNB":
            beans_kg = 0.070 * p["cocoa_pct"] / 100 / 0.80
            margins[pid] = round(p["wholesale_usd"] - beans_kg * prices[p["origin"]], 2)
    best = max(margins, key=margins.get)
    check(priciest == "madagascar" and best == "MG70", "M7: Madagascar no longer the priciest with the best margin")
    out.append(f"M7 priciest {priciest} {prices[priciest]}/kg; margin after beans per bar {margins}")
    return out


if __name__ == "__main__":
    main()
