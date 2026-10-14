"""Generate and derive the photo and scan assets listed in data/cocoarynth/briefs/assets.yaml.

Usage:
  .venv-cocoarynth/bin/python scripts/cocoarynth/images.py photos   # MAI photos that don't exist yet
  .venv-cocoarynth/bin/python scripts/cocoarynth/images.py derived  # wrapper labels and scanned forms
"""

import base64
import io
import json
import os
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np
import requests
import yaml
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFilter, ImageFont

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data" / "cocoarynth"
ASSETS = DATA / "assets"
FONTS = Path("/System/Library/Fonts/Supplemental")
LANDSCAPE = (1248, 832)


def asset_catalog() -> dict:
    return yaml.safe_load((DATA / "briefs" / "assets.yaml").read_text(encoding="utf-8"))


def photo_path(asset: dict) -> Path:
    return DATA / asset.get("path", f"assets/photos/{asset['name']}.png")


def generate_photos() -> None:
    load_dotenv(REPO / ".env", override=True)
    endpoint = f"https://{os.environ['MAI_IMAGE_ENDPOINT']}.services.ai.azure.com/mai/v1/images/generations"
    headers = {"Content-Type": "application/json", "api-key": os.environ["MAI_IMAGE_KEY"]}
    for asset in asset_catalog()["photos"]:
        path = photo_path(asset)
        if path.is_file():
            continue
        width, height = asset.get("size", LANDSCAPE)
        body = {"prompt": asset["prompt"], "width": width, "height": height, "model": "MAI-Image-2.5"}
        for attempt in range(3):
            response = requests.post(endpoint, headers=headers, json=body, timeout=300)
            if response.status_code < 500 and response.status_code != 429:
                break
            print(f"{asset['name']}: HTTP {response.status_code}, retrying", flush=True)
        if response.status_code >= 400:
            print(f"{asset['name']}: HTTP {response.status_code} {response.text[:300]}", flush=True)
            continue
        image = Image.open(io.BytesIO(base64.b64decode(response.json()["data"][0]["b64_json"])))
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path)
        print(f"{asset['name']}: saved {path.relative_to(REPO)} {image.size}", flush=True)


def world(name: str) -> dict:
    return json.loads((DATA / "world" / f"{name}.json").read_text(encoding="utf-8"))


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), size)


PANEL = (1400, 560)
PANEL_INK = (58, 36, 24)


# 5x7 dot-matrix glyphs, as used by the inkjet coders that print lot codes on packaging.
DOT_GLYPHS = {
    "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    "3": ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "5": ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
    "6": ["00110", "01000", "10000", "11110", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00010", "01100"],
    "B": ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
    "C": ["01110", "10001", "10000", "10000", "10000", "10001", "01110"],
    "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    "G": ["01110", "10001", "10000", "10111", "10001", "10001", "01111"],
    "H": ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
    "L": ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    "M": ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
    "O": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "P": ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    "T": ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    "-": ["00000", "00000", "00000", "11111", "00000", "00000", "00000"],
    "/": ["00001", "00001", "00010", "00100", "01000", "10000", "10000"],
    " ": ["00000"] * 7,
}


def dot_matrix(draw: ImageDraw.ImageDraw, text: str, xy: tuple[int, int], pitch: int) -> None:
    """Draw text in 5x7 inkjet dots; pitch is the distance between dot centers."""
    radius = pitch * 0.4
    x0, y0 = xy
    for ch in text:
        for row, bits in enumerate(DOT_GLYPHS[ch]):
            for col, bit in enumerate(bits):
                if bit == "1":
                    cx, cy = x0 + col * pitch, y0 + row * pitch
                    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=(20, 20, 24, 235))
        x0 += 6 * pitch


def back_panel(product: dict, batch: str, best_by: str, seed: int) -> Image.Image:
    rng = np.random.default_rng(seed)
    panel = Image.new("RGBA", PANEL, (0, 0, 0, 0))
    draw = ImageDraw.Draw(panel)
    ink = (*PANEL_INK, 255)
    draw.text((70, 60), "C O C O A R Y N T H", font=font("Arial Bold.ttf", 46), fill=ink)
    draw.text((70, 130), product["name"].split(" (")[0], font=font("Arial Bold.ttf", 52), fill=ink)
    draw.text((70, 200), "Single-origin dark chocolate · Net wt 70 g (2.47 oz)", font=font("Arial.ttf", 30), fill=ink)
    small = font("Arial.ttf", 25)
    lines = ["Ingredients: cocoa beans, organic cane sugar.", "Made in a facility that also handles milk and tree nuts.",
             "Store cool and dry, 15–20 °C. Made in Portland, Oregon, USA.", "cocoarynth.example"]
    for i, line in enumerate(lines):
        draw.text((70, 270 + i * 36), line, font=small, fill=ink)
    x = 900
    for _ in range(64):
        width = int(rng.choice([3, 3, 5, 7]))
        if rng.random() > 0.45:
            draw.rectangle([x, 60, x + width - 1, 170], fill=(20, 20, 20, 255))
        x += width
    draw.text((905, 176), "8 61734 20" + str(seed % 10) + "68 " + str(seed % 7), font=font("Arial.ttf", 26), fill=(20, 20, 20, 255))
    draw.rectangle([880, 250, 1360, 520], outline=ink, width=3)
    draw.text((896, 258), "LOT / BEST BY", font=font("Arial.ttf", 24), fill=ink)
    code = Image.new("RGBA", (470, 220), (0, 0, 0, 0))
    code_draw = ImageDraw.Draw(code)
    dot_matrix(code_draw, f"LOT {batch}", (10, 20), 5.6)
    dot_matrix(code_draw, f"BB {best_by}", (10, 110), 5.6)
    code = code.rotate(rng.uniform(-1.2, 1.2), resample=Image.BICUBIC, expand=True)
    panel.alpha_composite(code, (892, 290))
    return panel


def wrapper_label(asset: dict) -> None:
    import handwriting as hw

    batches = {b["id"]: b for b in world("production")["batches"]}
    products = {p["id"]: p for p in world("production")["products"]}
    batch = batches[asset["batch"]]
    packed = date.fromisoformat(batch["packed"])
    best_by = f"{packed.month:02d}/{packed.year + 1}"
    catalog = {a["name"]: a for a in asset_catalog()["photos"]}
    photo = Image.open(photo_path(catalog[asset["from"]])).convert("RGB")
    panel = back_panel(products[batch["product"]], batch["id"], best_by, seed=sum(map(ord, batch["id"])))
    w, h = PANEL
    coeffs = hw.perspective_coeffs([(0, 0), (w, 0), (w, h), (0, h)], [tuple(p) for p in asset["quad"]])
    warped = panel.transform(photo.size, Image.PERSPECTIVE, coeffs, Image.BICUBIC).filter(ImageFilter.GaussianBlur(0.5))
    ink = np.asarray(warped, np.float32)
    base = np.asarray(photo, np.float32)
    alpha = ink[..., 3:4] / 255.0 * 0.92
    # Multiply blend keeps the paper's texture and lighting under the ink.
    out = base * (1 - alpha) + base * (ink[..., :3] / 255.0) * alpha
    target = ASSETS / "derived" / f"{asset['name']}.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(out.clip(0, 255).astype(np.uint8)).save(target)
    print(f"{asset['name']}: saved {target.relative_to(REPO)}")


SCALE = 2


def printed_form(page, html: str, width: int) -> tuple[Image.Image, dict[str, tuple[float, float, float, float]]]:
    """Screenshot a printed form and return the pixel box of every element marked data-k."""
    page.set_viewport_size({"width": width, "height": 100})
    page.set_content(f"<html><head><meta charset='utf-8'></head><body style='margin:0;background:white'>{html}</body></html>")
    page.wait_for_timeout(150)
    boxes = page.evaluate(
        "Array.from(document.querySelectorAll('[data-k]')).map(e => {"
        "const r = e.getBoundingClientRect(); return [e.dataset.k, r.x, r.y, r.width, r.height]; })"
    )
    image = Image.open(io.BytesIO(page.screenshot(full_page=True))).convert("RGB")
    return image, {k: (x * SCALE, y * SCALE, w * SCALE, h * SCALE) for k, x, y, w, h in boxes}


def fit(writer, hand, text: str, width: float):
    
    while hand.size > 22 and writer.measure(text, hand) > width:
        hand = replace(hand, size=hand.size - 2)
    return hand


def write_in(writer, boxes, key: str, text: str, hand, inset: float = 10, lift: float = 9) -> None:
    x, y, w, h = boxes[key]
    hand = fit(writer, hand, text, w - 2 * inset)
    writer.write(text, x + inset + writer.rng.uniform(0, 14), y + h - lift + writer.rng.normal(0, 2), hand)


TICKET_FORM = """
<div style="width:1000px;padding:26px 34px;font-family:Arial, Helvetica, sans-serif;color:#2b2b2b">
 <div style="display:flex;justify-content:space-between;align-items:flex-start;border-bottom:3px solid #2b2b2b;padding-bottom:8px">
  <div><div style="font-size:30px;font-weight:700;letter-spacing:.04em">BOLETA DE ACOPIO</div>
   <div style="font-size:16px">Cooperativa Agroartesanal Río Claro · Centro de acopio · Esmeraldas, Ecuador</div></div>
  <div style="text-align:right"><div style="font-size:13px">N.º</div>
   <div style="font-family:'Courier New', monospace;font-weight:700;font-size:30px;color:#b02a2a">{number}</div></div>
 </div>
 <table style="width:100%;border-collapse:collapse;margin-top:14px;font-size:17px">
  {rows}
 </table>
 <div style="display:flex;gap:40px;margin-top:34px;font-size:15px">
  <div style="flex:1"><div data-k="recibido" style="height:54px;border-bottom:1.5px solid #333"></div>Recibido por (nombre y firma)</div>
  <div style="flex:1"><div data-k="firma" style="height:54px;border-bottom:1.5px solid #333"></div>Firma del productor</div>
 </div>
 <div style="font-size:11px;color:#555;margin-top:18px">Original: productor · Copia: centro de acopio · Conserve esta boleta para su liquidación.</div>
</div>"""
TICKET_FIELDS = [("fecha", "Fecha"), ("productor", "Productor"), ("finca", "Finca"), ("kg", "Cacao en baba (kg)"), ("lote", "Código de lote"), ("obs", "Observaciones")]
MONTHS_ES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def ticket_scans(page) -> None:
    import handwriting as hw

    people = {p["id"]: p for p in world("company")["people"]}
    farms = {f["id"]: f for f in world("origins")["farms"]}
    rows = "".join(
        f"<tr><td style='width:240px;padding:16px 0 4px;vertical-align:bottom'>{label}:</td>"
        f"<td data-k='{key}' style='border-bottom:1.5px solid #555;height:44px'></td></tr>"
        for key, label in TICKET_FIELDS
    )
    marisol = hw.Hand("Caveat.ttf", 68, slant=4, wobble=2.4)
    tickets = [t for t in world("beans")["collection_tickets"] if t["supplier"] == "rio-claro"]
    for i, ticket in enumerate(tickets):
        year, month, day = ticket["date"].split("-")
        farm = farms[ticket["farm"]]
        farmer = people[farm["farmer"]]["name"]
        receiver = people[ticket["received_by"]]["name"]
        form, boxes = printed_form(page, TICKET_FORM.format(number=ticket["id"].split("-")[1], rows=rows), 1070)
        writer = hw.Writer(form.size, seed=100 + i)
        write_in(writer, boxes, "fecha", f"{int(day)} {MONTHS_ES[int(month) - 1]} {year}", marisol)
        write_in(writer, boxes, "productor", farmer, marisol)
        write_in(writer, boxes, "finca", farm["name"].replace("Finca ", ""), marisol)
        # Codes and weights are printed carefully in capitals so they stay readable.
        write_in(writer, boxes, "kg", str(ticket["wet_kg"]), hw.Hand("Kalam-Regular.ttf", 58, slant=3, wobble=1.2, size_jitter=0.03))
        write_in(writer, boxes, "lote", ticket["lot"], hw.Hand("Kalam-Regular.ttf", 56, slant=3, wobble=1.2, size_jitter=0.03, spacing=1.06))
        write_in(writer, boxes, "obs", ticket["notes"], marisol)
        write_in(writer, boxes, "recibido", f"{receiver.split()[0][0]}. {receiver.split()[-1]}", marisol)
        initials = "".join(w[0] for w in farmer.split())
        write_in(writer, boxes, "firma", f"{initials[0]}. {farmer.split()[-1]}",
                 hw.Hand("NothingYouCouldDo.ttf", 60, ink=hw.BLACK_PEN, slant=10, wobble=3.5, jitter_deg=4))
        damp = (0.62, 0.55, 0.16) if "mojada" in ticket["notes"] else None
        image = hw.scan(form, writer.finish(), seed=200 + i, angle=[1.3, -0.9, 0.6][i % 3],
                        fold_at=0.46 if i % 2 else None, water=damp)
        out = ASSETS / "derived" / f"ticket-{ticket['id']}.jpg"
        image.save(out, quality=74)
        print(f"ticket {ticket['id']}: saved {out.relative_to(REPO)}")


FIELD_NOTES = [
    ("20 de mayo de 2026 — Visita de campo", True),
    ("Finca El Guayabo (Miguel Reyes)", True),
    ("– Después de 2 semanas de lluvia instaló una secadora a leña.", False),
    ("– La chimenea está a unos 4 m de los tendales de secado.", False),
    ("– En la tarde el humo pasa por encima del cacao. ¡Ojo!", False),
    ("– Recomiendo mover los tendales 30 m contra el viento y subir la chimenea por encima del techo.", False),
    ("Finca Loma Verde (Ramón Castillo): todo en orden.", True),
    ("— Y. Peña", False),
]


def field_notes_scan() -> None:
    import handwriting as hw

    width, height, rule, top, margin = 1600, 1010, 58, 150, 170
    form = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(form)
    for y in range(top, height - 40, rule):
        draw.line([(0, y), (width, y)], fill=(160, 190, 222), width=2)
    draw.line([(margin - 20, 0), (margin - 20, height)], fill=(222, 120, 120), width=2)
    for x in range(120, width, 110):
        draw.ellipse([x - 14, 34, x + 14, 62], fill=(205, 205, 205))
    writer = hw.Writer(form.size, seed=321)
    yanelis = hw.Hand("ReenieBeanie.ttf", 64, slant=2, wobble=2.6, jitter_deg=3)
    baseline = top + rule - 10
    for text, underline in FIELD_NOTES:
        if text.startswith("— "):
            writer.write(text, width - 420, baseline + rule, yanelis)
            continue
        indent = margin + (34 if text.startswith("–") else 0)
        end = writer.write_wrapped(text, indent, baseline, width - indent - 80, rule, yanelis)
        if underline:
            writer.underline(indent, indent + min(writer.measure(text, yanelis), width - indent - 80), baseline + 10, yanelis)
        baseline = end + rule
    image = hw.scan(form, writer.finish(1.6), seed=322, angle=-1.2, fold_at=None)
    out = ASSETS / "derived" / "field-notes-scan.jpg"
    image.save(out, quality=72)
    print(f"field notes: saved {out.relative_to(REPO)}")


DEPOT_ROWS = [
    ("06:50", "TC-118", "Produce (berries)", "Cold Room 2", "09:40", "M.R."),
    ("07:10", "TC-121", "Produce (cherries)", "Cold Room 2", "—", "M.R."),
    ("07:30", "LM-P02", "Chocolate – Cocoarynth", "Overflow Bay 4 (CR2 full)", "20:10", "D.W."),
    ("09:15", "BK-044", "Dry goods", "Bay 1", "11:00", "D.W."),
    ("11:20", "TC-126", "Produce (peaches)", "Cold Room 2", "—", "M.R."),
    ("13:05", "PL-310", "Paper products", "Bay 2", "16:30", "D.W."),
]
DEPOT_COLUMNS = [("In", 90), ("Pallet", 140), ("Contents", 300), ("Staged at", 330), ("Out", 90), ("Init.", 80)]


def depot_log_scan(page) -> None:
    import handwriting as hw

    head = "".join(f"<th style='border:1.5px solid #333;padding:6px;background:#e9e9e9;width:{w}px'>{h}</th>" for h, w in DEPOT_COLUMNS)
    body = "".join(
        "<tr>" + "".join(f"<td data-k='r{r}c{c}' style='border:1.5px solid #333;height:58px'></td>" for c in range(len(DEPOT_COLUMNS))) + "</tr>"
        for r in range(len(DEPOT_ROWS) + 3)
    )
    html = f"""<div style="width:1120px;padding:26px 34px;font-family:Arial, Helvetica, sans-serif;color:#2b2b2b">
 <div style="display:flex;justify-content:space-between;border-bottom:3px solid #245a7a;padding-bottom:6px">
  <b style="font-size:24px;color:#245a7a">NORTHWIND COLD FREIGHT</b><span style="font-size:15px">Riverbend Depot, Pasco WA · Form RD-7 Handling log</span></div>
 <div style="display:flex;gap:24px;margin:16px 0 4px;font-size:16px">
  <div>Date: <span data-k="date" style="display:inline-block;width:200px;border-bottom:1.5px solid #333;height:34px"></span></div>
  <div>Supervisor: <span data-k="sup" style="display:inline-block;width:240px;border-bottom:1.5px solid #333;height:34px"></span></div></div>
 <div data-k="banner" style="height:58px"></div>
 <table style="border-collapse:collapse;width:100%;font-size:15px"><tr>{head}</tr>{body}</table>
 <div style="margin-top:12px;font-size:15px">Notes:</div>
 <div data-k="note1" style="border-bottom:1.5px solid #999;height:46px"></div>
 <div data-k="note2" style="border-bottom:1.5px solid #999;height:46px"></div>
 <div style="font-size:11px;color:#555;margin-top:10px">Temperature-sensitive cargo must be staged in Cold Room 1 or 2. Escalate to shift lead if full.</div>
</div>"""
    form, boxes = printed_form(page, html, 1190)
    writer = hw.Writer(form.size, seed=555)
    dana = hw.Hand("ShadowsIntoLight.ttf", 54, slant=-2, wobble=2.0, spacing=1.1)
    mr = hw.Hand("Kalam-Regular.ttf", 40, ink=hw.BLACK_PEN, slant=5, wobble=1.6, size_jitter=0.04)
    write_in(writer, boxes, "date", "7/14/26", dana)
    write_in(writer, boxes, "sup", "Dana Whitfield", dana)
    x, y, w, h = boxes["banner"]
    writer.write("HEAT ADVISORY TODAY — high 39°C", x + 330, y + h - 12,
                 hw.Hand("Kalam-Regular.ttf", 46, ink=hw.RED_MARKER, slant=-3, wobble=1.2), tilt=-1.5)
    for r, row in enumerate(DEPOT_ROWS):
        hand = dana if row[-1] == "D.W." else mr
        for c, value in enumerate(row):
            # Shadows Into Light has small old-style numerals; enlarge them so times stay legible.
            cell_hand = replace(hand, size=int(hand.size * 1.35)) if hand is dana and value[:1].isdigit() else hand
            write_in(writer, boxes, f"r{r}c{c}", value, cell_hand, inset=8, lift=14)
    write_in(writer, boxes, "note1", "LM-P02 onward truck moved to evening. CR2 full w/ produce — put in Bay 4.", dana, lift=8)
    write_in(writer, boxes, "note2", "Logger LOGGER-04 on pallet.  — D.W.", dana, lift=8)
    image = hw.scan(form, writer.finish(), seed=556, angle=0.7, fold_at=0.33)
    out = ASSETS / "derived" / "depot-log-scan.jpg"
    image.save(out, quality=72)
    print(f"depot log: saved {out.relative_to(REPO)}")


def derive() -> None:
    from playwright.sync_api import sync_playwright

    sys.path.insert(0, str(Path(__file__).parent))
    for asset in asset_catalog()["derived"]:
        if "batch" in asset:
            wrapper_label(asset)
    field_notes_scan()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(device_scale_factor=SCALE)
        ticket_scans(page)
        depot_log_scan(page)
        browser.close()


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "photos":
        generate_photos()
    elif command == "derived":
        derive()
    else:
        raise SystemExit(__doc__)
