"""Render the allowlisted Cocoarynth operational PDFs from portable JSON sources."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal
from functools import partial
from html import escape
import json
from pathlib import Path
import re
import shutil
import tempfile

import fitz
import reportlab
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


REPO = Path(__file__).resolve().parents[1]
AUTHORING = REPO / "data" / "cocoarynth" / "authoring"
ORIGINALS = AUTHORING.parent / "documents"
FILENAMES = frozenset(
    name + ".pdf" for name in (
        "archive-card assurance-review capability-reference collection-notebook control-reference "
        "custody-statement dispatch-receipt drying-notebook field-log formulation-memo governance-decision "
        "integration-brief integration-exception inventory-review issuance-register label-review "
        "nonconformance-report order-note packing-sheet production-closeout production-traveler quality-report "
        "receipt-acknowledgment receipt-case review-request rework-ticket routing-card sensory-note "
        "sharing-decision shift-handover shipment-close sourcing-decision sourcing-dossier stock-card "
        "stock-summary support-timeline technical-letter training-case wip-handoff wip-tag"
    ).split()
)
PALETTES = {
    "record": ("#321C15", "#FFF9EF"),
    "stores": ("#234D43", "#F1F5F2"),
    "partner": ("#243B54", "#F2F5F8"),
    "field": ("#635337", "#FAF6E9"),
    "notebook": ("#635337", "#FAF6E9"),
    "memo": ("#321C15", "#FFF9EF"),
    "letter": ("#321C15", "#FFFFFF"),
}
DECIMAL = Decimal


def load_source() -> tuple[list[dict], dict]:
    documents = json.loads((AUTHORING / "documents.json").read_text(encoding="utf-8"))
    evidence = json.loads((AUTHORING / "evidence.json").read_text(encoding="utf-8"))
    if documents["schema_version"] != 1 or evidence["schema_version"] != 1:
        raise ValueError("Unsupported authoring schema")
    return documents["documents"], evidence


def selected_rows(spec: dict, evidence: dict) -> list[dict]:
    collection = evidence[spec["collection"]]
    if not isinstance(collection, list):
        raise ValueError("Evidence tables require a row collection")
    selection = spec.get("select", {})
    rows = [row for row in collection if all(row.get(k) == v for k, v in selection.items())]
    if not rows:
        raise ValueError(f"Empty evidence selection: {spec}")
    return rows


def shown(value: object) -> str:
    return "Not supplied" if value is None else str(value)


def expanded_blocks(document: dict, evidence: dict) -> list[list]:
    blocks = []
    for b in document["blocks"]:
        if b[0] == "evidence":
            spec = b[1]
            rows = selected_rows(spec, evidence)
            columns = spec["columns"]
            blocks.append(["table", [c[1] for c in columns],
                           [[shown(row[c[0]]) for c in columns] for row in rows], spec.get("widths")])
        elif b[0] == "science_sources":
            for source in evidence["sources"]:
                blocks.append(["link", source["title"], source["url"]])
        else:
            blocks.append(b)
    return blocks


def aware(timestamp: str) -> datetime:
    value = datetime.fromisoformat(timestamp)
    if value.utcoffset() is None:
        raise ValueError(f"Timestamp must include an explicit UTC offset: {timestamp}")
    return value


def validate_source(documents: list[dict], evidence: dict) -> None:
    names = [d["filename"] for d in documents]
    if len(names) != 40 or set(names) != FILENAMES:
        raise ValueError("Source must contain exactly the fixed 40 generated filenames")
    if Counter(d["language"] for d in documents) != {"en": 32, "es": 8}:
        raise ValueError("PDF document-count split must be 32 English / 8 Spanish")
    canonical = evidence["canonical_source"]
    if canonical["repository"] != "pamelas-organization/cocoarynth-trace" or canonical["revision"] != "a0b02a0579a8667c3d1bac7d1f5001ab0a0b0f77":
        raise ValueError("Canonical application identity or revision changed")
    for d in documents:
        if d["genre"] not in PALETTES:
            raise ValueError(f"Unknown document genre: {d['genre']}")
        for block in expanded_blocks(d, evidence):
            if block[0] not in ("h", "p", "note", "table", "page", "refs", "link"):
                raise ValueError(f"Unknown block: {block[0]}")
            if block[0] == "refs":
                for name in block[1]:
                    relative = Path(name)
                    if relative.is_absolute() or ".." in relative.parts:
                        raise ValueError(f"Non-relative companion reference: {name}")
                    if name not in FILENAMES and not (ORIGINALS / relative).is_file():
                        raise ValueError(f"Missing companion reference: {name}")
            if block[0] == "table":
                heads, rows, widths = block[1:]
                if not rows or any(len(row) != len(heads) for row in rows):
                    raise ValueError(f"Malformed table in {d['filename']}")
                if widths and (len(widths) != len(heads) or abs(sum(widths) - 1) > 0.001):
                    raise ValueError(f"Malformed column widths in {d['filename']}")

    ids = {}
    for collection, rows in evidence.items():
        if not isinstance(rows, list):
            continue
        if len({row["id"] for row in rows}) != len(rows):
            raise ValueError(f"Duplicate ID within {collection}")
        for row in rows:
            ids[row["id"]] = row
            if row.get("document") and row["document"] not in FILENAMES:
                raise ValueError(f"Evidence file does not resolve: {row['id']}")
            for field in ("timestamp", "start", "end"):
                if row.get(field):
                    aware(row[field])
            if collection != "sources" and row.get("basis") and row["basis"] not in ("observed", "calculated", "provisional"):
                raise ValueError(f"Unsupported evidence basis: {row['id']}")

    shipments = {s["id"]: s for s in evidence["shipments"]}
    samples = {s["id"]: s for s in evidence["samples"]}
    expected_shipments = {
        "shipment-esm-042": ("ESM-2026-042", "2026-08-26", "2026-08-28", "210", "207.2", "2.8"),
        "shipment-esm-039": ("ESM-2026-039", "2026-08-05", "2026-08-07", "196", "196", "0"),
        "shipment-suh-028": ("SUH-2026-028", "2026-07-22", "2026-07-24", "280", "280", "0"),
    }
    if set(shipments) != set(expected_shipments):
        raise ValueError("Do not invent or replace a canonical wholesale shipment")
    for identity, values in expected_shipments.items():
        s = shipments[identity]
        actual = tuple(s[k] for k in ("batch_id", "dispatch_date", "receipt_date", "dispatch_kg", "accepted_kg", "arrival_quarantine_kg"))
        if actual != values or DECIMAL(s["dispatch_kg"]) != DECIMAL(s["accepted_kg"]) + DECIMAL(s["arrival_quarantine_kg"]):
            raise ValueError(f"Canonical receipt changed: {identity}")
        if s["pallet_id"] not in ids or s["route_id"] not in ids:
            raise ValueError(f"Unknown pallet or route: {identity}")
    if shipments["shipment-esm-042"]["arrival_quarantine_bars"] != 40:
        raise ValueError("Northstar arrival quarantine must remain 40 bars")
    for sample in samples.values():
        if sample["destructive"]:
            raise ValueError("Selected visual cohorts must not create new inventory withdrawals")
        if sample["shipment_id"]:
            s = shipments[sample["shipment_id"]]
            if sample["batch_id"] != s["batch_id"] or sample["pallet_id"] != s["pallet_id"]:
                raise ValueError(f"Sample lineage mismatch: {sample['id']}")
    for observation in evidence["observations"]:
        sample = samples[observation["sample_id"]]
        if not 0 <= observation["white_film_bars"] <= sample["n"]:
            raise ValueError(f"Observation exceeds cohort: {observation['id']}")
        if sample["shipment_id"] and aware(observation["timestamp"]).date().isoformat() < shipments[sample["shipment_id"]]["receipt_date"]:
            raise ValueError(f"Retail observation precedes receipt: {observation['id']}")
    for movement in evidence["movements"]:
        s = shipments[movement["shipment_id"]]
        if movement["pallet_id"] != s["pallet_id"] or not s["dispatch_date"] <= aware(movement["timestamp"]).date().isoformat() <= s["receipt_date"]:
            raise ValueError(f"Movement identity or chronology mismatch: {movement['id']}")
        if movement["position_id"] not in ids or movement["site_id"] not in ids:
            raise ValueError(f"Unknown staging relationship: {movement['id']}")
    for reading in evidence["readings"]:
        if reading["sensor_id"] not in ids or reading["position_id"] not in ids:
            raise ValueError(f"Unresolved sensor relationship: {reading['id']}")
        DECIMAL(reading["value"])
        if reading["unit"] not in ("degC", "percent_RH"):
            raise ValueError(f"Unspecified measurement unit: {reading['id']}")
    for series in evidence["coverage"]:
        if series["sensor_id"] not in ids:
            raise ValueError(f"Unknown coverage sensor: {series['id']}")
        start, end = aware(series["start"]), aware(series["end"])
        if start > end:
            raise ValueError(f"Reversed coverage interval: {series['id']}")
        interval = series["interval_minutes"]
        if interval is not None:
            if interval <= 0:
                raise ValueError(f"Invalid sampling interval: {series['id']}")
            schedule = set()
            current = start
            while current <= end:
                schedule.add(current)
                current += timedelta(minutes=interval)
            actual = {aware(r["timestamp"]) for r in evidence["readings"]
                      if r["sensor_id"] == series["sensor_id"] and r["unit"] == "degC"
                      and start <= aware(r["timestamp"]) <= end}
            if actual - schedule or schedule - actual != {aware(t) for t in series["missing_timestamps"]}:
                raise ValueError(f"Reading schedule or declared gaps disagree: {series['id']}")
    for row in evidence["entities"]:
        for field in ("parent_id", "carrier_id", "site_id"):
            if row.get(field) and row[field] not in ids:
                raise ValueError(f"Unknown entity relationship: {row['id']}")
    for row in evidence["staging_notes"]:
        if row["pallet_id"] not in ids or row["position_id"] not in ids:
            raise ValueError(f"Unresolved staging note: {row['id']}")
    batches = {"ESM-2026-042", "ESM-2026-039", "SUH-2026-028", "SUH-2026-031",
               "PIU-2026-018", "SAM-2026-027", "BLD-2026-060"}
    for rows in (evidence["samples"], evidence["packaging"], evidence["ingredient_issues"], evidence["quantities"]):
        for row in rows:
            if row["batch_id"] not in batches:
                raise ValueError(f"Unknown canonical or recorded blend batch: {row['id']}")
            for field in ("wrapper_lot", "butter_lot", "sugar_lot"):
                if row.get(field) and row[field] not in ids:
                    raise ValueError(f"Unresolved material lot: {row['id']}")
    for quantity in evidence["quantities"]:
        if DECIMAL(quantity["packed_kg"]) != sum(DECIMAL(quantity[k]) for k in ("retained_kg", "dispatch_kg", "factory_kg")):
            raise ValueError(f"Finished account does not reconcile: {quantity['id']}")
    for c in evidence["cases"]:
        if c["shipment_id"] not in shipments or c["status"] != "open":
            raise ValueError(f"Case reference or open status changed: {c['id']}")

    for d in documents:
        prose = json.dumps(expanded_blocks(d, evidence), ensure_ascii=False)
        if re.search(r"\b(fictional|synthetic|dataset|D\d{2}|V2[-_]|clues|mystery)\b", prose, re.I):
            raise ValueError(f"Authoring or answer framing in participant document: {d['filename']}")


def register_fonts() -> None:
    fonts = Path(reportlab.__file__).resolve().parent / "fonts"
    for name, filename in (("Body", "Vera.ttf"), ("Bold", "VeraBd.ttf"), ("Italic", "VeraIt.ttf")):
        pdfmetrics.registerFont(TTFont(name, str(fonts / filename)))


def check_glyphs(text: str) -> None:
    font = pdfmetrics.getFont("Body")
    missing = sorted({c for c in text if not c.isspace() and ord(c) not in font.face.charToGlyph})
    if missing:
        raise ValueError(f"Portable font does not cover: {missing}")


def render(document: dict, evidence: dict, path: Path) -> None:
    accent, wash = PALETTES[document["genre"]]
    width = 499
    body = ParagraphStyle("body", fontName="Body", fontSize=9.5, leading=12.5, spaceAfter=6,
                          textColor=colors.HexColor("#24201E"))
    if document["genre"] in ("notebook", "letter"):
        body.fontName = "Times-Roman"
        body.fontSize = 10.5
        body.leading = 13.1
    section = ParagraphStyle("section", parent=body, fontName="Bold", fontSize=11.7,
                             leading=14, spaceBefore=5, spaceAfter=5, keepWithNext=True,
                             textColor=colors.HexColor(accent))
    small = ParagraphStyle("small", parent=body, fontSize=7.8, leading=10.8, spaceAfter=5)
    cell = ParagraphStyle("cell", parent=body, fontSize=7.8, leading=10.2, spaceAfter=0)
    header = ParagraphStyle("header", parent=cell, fontName="Bold", textColor=colors.white)
    title = ParagraphStyle("title", parent=body, fontName="Bold", fontSize=18,
                           leading=22, spaceAfter=8, textColor=colors.HexColor(accent))
    blocks = expanded_blocks(document, evidence)
    check_glyphs(json.dumps(document, ensure_ascii=False) + json.dumps(blocks, ensure_ascii=False))
    flow = [Paragraph(escape(document["title"]), title),
            Paragraph(escape(document["identity"]) + "<br/>" + escape(document["date"]), small),
            Spacer(1, 6)]
    for b in blocks:
        kind = b[0]
        if kind == "page":
            flow.append(PageBreak())
        elif kind in ("h", "p"):
            flow.append(Paragraph(escape(b[1]), section if kind == "h" else body))
        elif kind == "note":
            t = Table([[Paragraph(escape(b[1]), small)]], colWidths=[width])
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(wash)),
                ("LINEBEFORE", (0, 0), (0, -1), 2, colors.HexColor(accent)),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
            flow += [t, Spacer(1, 8)]
        elif kind == "table":
            heads, rows, widths = b[1:]
            n = len(heads)
            widths = widths or ([0.47, 0.53] if n == 2 else [1/n] * n)
            data = [[Paragraph(escape(str(v)), header) for v in heads]]
            data += [[Paragraph(escape(str(v)), cell) for v in row] for row in rows]
            t = Table(data, colWidths=[width*x for x in widths], repeatRows=1, hAlign="LEFT")
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(accent)),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor(wash)]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#D5D2CB"))]))
            flow += [t, Spacer(1, 8)]
        elif kind == "refs":
            continue
        elif kind == "link":
            flow.append(Paragraph(f'<b>{escape(b[1])}</b><br/><link href="{escape(b[2], quote=True)}">{escape(b[2])}</link>', small))

    def frame(canvas: Canvas, pdf: SimpleDocTemplate) -> None:
        canvas.saveState()
        canvas.setFont("Bold", 8)
        canvas.setFillColor(colors.HexColor(accent))
        canvas.drawString(48, 808, document["desk"])
        canvas.setStrokeColor(colors.HexColor(accent))
        canvas.line(48, 795, 547, 795)
        if pdf.page > 1:
            canvas.setFont("Body", 7.5)
            canvas.drawString(48, 782, document["title"])
        canvas.setStrokeColor(colors.HexColor("#D5D2CB"))
        canvas.line(48, 45, 547, 45)
        canvas.setFont("Body", 7)
        canvas.setFillColor(colors.HexColor("#5B5550"))
        identity = document["identity"] if len(document["identity"]) < 85 else "Trace Platform"
        canvas.drawString(48, 31, identity)
        canvas.drawRightString(547, 31, str(pdf.page))
        canvas.restoreState()

    pdf = SimpleDocTemplate(str(path), invariant=1, pagesize=(595, 842), leftMargin=48, rightMargin=48,
                            topMargin=75, bottomMargin=61, title=document["title"],
                            author=document["desk"], subject=f"{document['identity']} / language={document['language']}")
    pdf.build(flow, onFirstPage=frame, onLaterPages=frame, canvasmaker=partial(Canvas, invariant=1))


def normalized(text: str) -> str:
    return re.sub(r"\s+", "", text)


def validate_pdf(document: dict, evidence: dict, path: Path) -> int:
    with fitz.open(path) as pdf:
        text = "\n".join(page.get_text() for page in pdf)
        if "\x00" in text or "\ufffd" in text:
            raise ValueError(f"Unextractable glyph in {path.name}")
        expected = [document["title"], document["identity"], document["date"], document["desk"]]
        for block in expanded_blocks(document, evidence):
            if block[0] in ("p", "h", "note"):
                expected.append(block[1])
            elif block[0] == "table":
                expected.extend(str(x) for row in [block[1]] + block[2] for x in row)
            elif block[0] == "link":
                expected.extend(block[1:])
        if "Companion records" in text or "Registros relacionados" in text:
            raise ValueError(f"Authoring companion list exposed in {path.name}")
        for value in expected:
            if normalized(value) not in normalized(text):
                raise ValueError(f"PDF text missing in {path.name}: {value}")
        for page_number, page in enumerate(pdf, 1):
            if len(page.get_text().split()) < 70:
                raise ValueError(f"Sparse/orphan page: {path.name}:{page_number}")
            for b in page.get_text("dict")["blocks"]:
                for line in b.get("lines", []):
                    for span in line["spans"]:
                        x0, y0, x1, y1 = span["bbox"]
                        if x0 < 45 or x1 > 550 or y0 < 18 or y1 > 822:
                            raise ValueError(f"Text outside usable bounds: {path.name}:{page_number}: {span['text']}")
        return len(pdf)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Directory for exactly 40 generated PDFs")
    args = parser.parse_args()
    documents, evidence = load_source()
    validate_source(documents, evidence)
    register_fonts()
    for component in [args.output, *args.output.parents]:
        if component.is_symlink() or (hasattr(component, "is_junction") and component.is_junction()):
            raise ValueError(f"Output may not traverse a symbolic link or junction: {component}")
    output = args.output.resolve()
    if output == REPO or output == AUTHORING or output.is_symlink():
        raise ValueError("Output must be a dedicated PDF directory")
    for name in FILENAMES:
        target = output / name
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise ValueError(f"Unsafe output target: {target}")
    with tempfile.TemporaryDirectory(prefix="cocoarynth-pdf-") as temporary:
        staging = Path(temporary)
        pages = 0
        for d in documents:
            render(d, evidence, staging / d["filename"])
            pages += validate_pdf(d, evidence, staging / d["filename"])
        # Validate the entire set before writing any destination file.
        output.mkdir(parents=True, exist_ok=True)
        for name in sorted(FILENAMES):
            shutil.copyfile(staging / name, output / name)
    print(f"Generated 40 PDFs / {pages} pages: 32 English, 8 Spanish. Output: {output}")


if __name__ == "__main__":
    main()
