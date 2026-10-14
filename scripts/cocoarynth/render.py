"""Render the Cocoarynth drafts into PDFs, one per brief.

Drafts live in data/cocoarynth/drafts/<brief id>.md. A draft may start with a YAML front matter block
(between --- lines) for header fields such as email From/To. The body is Markdown, preprocessed with Jinja.
Available in drafts:
  {{ chart("name", "caption") }}  {{ photo("name", "caption") }}  {{ scan("name", "caption") }}
  {{ table("lot_register") }} and the other tables in TABLES below
  {{ W }} world data by file and id, e.g. W.beans.lots["MG26-L02"].received_kg

Usage: .venv-cocoarynth/bin/python scripts/cocoarynth/render.py [brief-id ...]
"""

import base64
import html
import io
import json
import sys
from datetime import date
from pathlib import Path

import jinja2
import markdown
import yaml
from PIL import Image
from playwright.sync_api import sync_playwright

DATA = Path(__file__).resolve().parents[2] / "data" / "cocoarynth"
OUTPUT = DATA / "documents"
MONTHS_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def load_world() -> dict:
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((DATA / "world").glob("*.json"))}


class Lookup(dict):
    __getattr__ = dict.__getitem__


class IdList(list):
    """A list of records that can also be indexed by record id."""

    def __getitem__(self, key):
        if isinstance(key, str):
            return next(item for item in self if item["id"] == key)
        return super().__getitem__(key)


def lookup(value):
    if isinstance(value, dict):
        return Lookup({k: lookup(v) for k, v in value.items()})
    if isinstance(value, list) and value and all(isinstance(i, dict) and "id" in i for i in value):
        return IdList(lookup(i) for i in value)
    if isinstance(value, list):
        return [lookup(v) for v in value]
    return value


RAW = load_world()
W = lookup(RAW)
ASSETS = yaml.safe_load((DATA / "briefs" / "assets.yaml").read_text(encoding="utf-8"))
PHOTOS = {a["name"]: DATA / a.get("path", f"assets/photos/{a['name']}.png") for a in ASSETS["photos"]}


def org_names() -> dict[str, str]:
    names = {"cocoarynth": RAW["company"]["company"]["name"]}
    for key in ("suppliers",):
        names |= {s["id"]: s["name"] for s in RAW["origins"][key]}
    names |= {p["id"]: p["name"] for p in RAW["company"]["partners"]}
    names |= {r["id"]: r["name"] for r in RAW["retail"]["retailers"]}
    return names


ORGS = org_names()
PEOPLE = {p["id"]: p for p in RAW["company"]["people"]}
BRAND = {"cocoarynth": "#3f2922", "rio-claro": "#2f6b4f", "akwapim-ridge": "#8a6d1f", "nuevo-horizonte": "#3d6e8a",
         "tsaravola": "#9c3d2e", "loma-verde": "#4f7a3a", "certiorganica": "#2e7d5b", "cascadia-labs": "#1f5f8b",
         "northwind": "#245a7a", "bluefin": "#1d4f91", "larkspur-market": "#5a3e8a", "pantry-lane": "#c0612b",
         "steeple-saucer": "#6b4f3a", "cacao-cabinet": "#8a2e4f", "hoshizora-foods": "#2b3f7a", "tidewater": "#2a6f6f", "fernleaf": "#3f7a3f"}
# Each issuing organization has its own house style; Cocoarynth's documents share the company template.
HOUSE = {"cocoarynth": "cocoarynth", "rio-claro": "cooperative", "nuevo-horizonte": "cooperative", "akwapim-ridge": "association",
         "loma-verde": "fieldteam", "tsaravola": "estate", "certiorganica": "certifier", "cascadia-labs": "lab",
         "bluefin": "forwarder", "tidewater": "forwarder", "fernleaf": "forwarder", "northwind": "carrier"}
HOUSE |= {r["id"]: "retail" for r in RAW["retail"]["retailers"]}
LOCATIONS = {p["id"]: p["location"] for p in RAW["company"]["partners"] if p.get("location")}


def font_face(family: str, path: Path, weight: int) -> str:
    data = base64.b64encode(path.read_bytes()).decode()
    return f"@font-face {{ font-family: '{family}'; src: url(data:font/ttf;base64,{data}) format('truetype'); font-weight: {weight}; }}\n"


def jpeg_uri(path: Path, max_width: int = 1400) -> str:
    image = Image.open(path).convert("RGB")
    if image.width > max_width:
        image = image.resize((max_width, int(image.height * max_width / image.width)))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()


def png_uri(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def figure(src: str, caption: str, css: str = "") -> str:
    cap = f"<figcaption>{html.escape(caption)}</figcaption>" if caption else ""
    return f'\n<figure class="{css}"><img src="{src}">{cap}</figure>\n'


def transparent_logo_uri(path: Path, max_width: int) -> str:
    """Make the logo's light, textured background transparent so it sits cleanly on any page color."""
    image = Image.open(path).convert("RGB")
    image = image.resize((max_width, int(image.height * max_width / image.width)), Image.LANCZOS)
    alpha = image.convert("L").point(lambda v: max(0, min(255, round((228 - v) * 255 / 48))))
    image.putalpha(alpha)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


BRAND_DIR = DATA / "assets" / "brand"
LOGO_MARK = jpeg_uri(BRAND_DIR / "cocoarynth-logo.png", 160)
LOGO_FULL = transparent_logo_uri(BRAND_DIR / "cocoarynth-logo-full.png", 700)
# Static weights: Chromium embeds a variable font as many Type 3 fonts, which doubles PDF size.
INTER_FACE = "".join(font_face("Inter", DATA / "assets" / "fonts" / f"Inter-{name}.ttf", weight)
                     for name, weight in (("Regular", 400), ("SemiBold", 600), ("Bold", 700), ("ExtraBold", 800)))


def chart(name: str, caption: str = "", width: str = "") -> str:
    return figure(png_uri(DATA / "assets" / "charts" / f"{name}.png"), caption, width)


def photo(name: str, caption: str = "", width: str = "") -> str:
    path = PHOTOS.get(name) or DATA / "assets" / "derived" / f"{name}.png"
    return figure(jpeg_uri(path), caption, width)


def scan(name: str, caption: str = "") -> str:
    derived = DATA / "assets" / "derived"
    files = sorted(derived.glob("ticket-*.jpg")) if name == "ticket-scans" else [derived / f"{name}.jpg"]
    return "".join(figure(jpeg_uri(f, 1600), caption, "scan") for f in files)


def md_table(headers: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n" + "\n".join(lines) + "\n"


def fmt_date(value: str, lang: str = "en") -> str:
    d = date.fromisoformat(value[:10])
    if lang == "es":
        return f"{d.day} de {MONTHS_ES[d.month - 1]} de {d.year}"
    return f"{d.day} {d.strftime('%B')} {d.year}"


def person(pid: str) -> str:
    return PEOPLE[pid]["name"] if pid in PEOPLE else ORGS.get(pid, pid)


def t_lot_register() -> str:
    rows = []
    farms = W.origins.farms
    for lot in RAW["beans"]["lots"]:
        tests = {t["type"]: t for t in lot["tests"]}
        moist = [t for t in lot["tests"] if t["type"] == "moisture"]
        cut = tests.get("cut_test")
        cut_text = f"{cut['well_fermented']}/{cut['slaty']}/{cut['mouldy']}/{cut['insect_damaged']}" if cut else "—"
        received = W.beans.consignments[lot["consignment"]]["factory_receipt"] if lot.get("consignment") else lot.get("received")
        decision = lot.get("released") or lot.get("rejected") or "—"
        rows.append([lot["id"], W.origins.origins[lot["origin"]]["country"], received, f"{lot['received_kg']:.1f}",
                     " → ".join(f"{t['value_pct']}%" for t in moist), cut_text,
                     tests.get("sensory_check", {}).get("result", "—"), lot["status"].replace("_", " "), decision])
    return md_table(["Lot", "Origin", "Received", "kg", "Moisture", "Cut test (well/slaty/mouldy/insect)", "Sensory", "Status", "Decision date"], rows)


def t_tickets(lot: str | None = None) -> str:
    rows = [[t["id"], t["date"], W.origins.farms[t["farm"]]["name"], t["wet_kg"], t["lot"]]
            for t in RAW["beans"]["collection_tickets"] if t["supplier"] == "rio-claro" and (lot is None or t["lot"] == lot)]
    return md_table(["Boleta", "Fecha", "Finca", "Cacao en baba (kg)", "Lote"], rows)


def t_findings(inspection: str, lang: str = "en") -> str:
    insp = W.origins.inspections[inspection]
    heads = (["Hallazgo", "Finca", "Severidad", "Descripción", "Acción correctiva", "Plazo", "Estado"] if lang == "es"
             else ["Finding", "Farm", "Severity", "Description", "Corrective action", "Due", "Status"])
    severity_es = {"major": "Mayor", "minor": "Menor", "observation": "Observación"}
    rows = [[f["id"], W.origins.farms[f["farm"]]["name"], severity_es[f["severity"]] if lang == "es" else f["severity"].title(),
             f["text"], f["corrective_action"], f.get("due") or "—", f["status"].replace("_", " ")] for f in insp["findings"]]
    return md_table(heads, rows)


def t_logger() -> str:
    readings = RAW["retail"]["loggers"][0]["readings"]
    half = (len(readings) + 1) // 2
    rows = []
    for i in range(half):
        left = readings[i]
        right = readings[i + half] if i + half < len(readings) else ["", ""]
        rows.append([left[0], left[1], right[0], right[1]])
    return md_table(["Time", "°C", "Time", "°C"], rows)


def t_panel() -> str:
    products = W.production.products
    samples = sorted(RAW["sensory"]["panels"][0]["samples"], key=lambda s: -s["overall"])
    return md_table(["Code", "Bar", "Overall (0–10)", "Panel notes"],
                    [[s["code"], products[s["product"]]["name"], s["overall"], s["notes"]] for s in samples])


def t_prices() -> str:
    prices = RAW["commercial"]["prices_landed_usd_kg"]
    ref = RAW["commercial"]["market_reference"]["by_year"]
    rows = [[W.origins.origins[o]["country"]] + [f"{p[y]:.2f}" if y in p else "—" for y in ("2024", "2025", "2026")] for o, p in prices.items()]
    rows.append(["World reference"] + [f"{ref[y]:.2f}" for y in ("2024", "2025", "2026")])
    return md_table(["Origin", "2024", "2025", "2026"], rows)


def t_purchases() -> str:
    data = RAW["commercial"]["purchases_kg"]
    rows = [[W.origins.origins[o]["country"]] + [f"{p[y]:,}" if y in p else "—" for y in ("2024", "2025", "2026")] for o, p in data.items()]
    return md_table(["Origin", "2024 (kg)", "2025 (kg)", "2026 to Sept (kg)"], rows)


def t_price_list() -> str:
    rows = [[p["id"], p["name"], f"${p['wholesale_usd']:.2f}", f"${p['retail_usd']:.2f}"]
            for p in RAW["production"]["products"] if p["wholesale_usd"]]
    return md_table(["Code", "Bar (70 g)", "Wholesale", "Suggested retail"], rows)


def t_sellin(product: str | None = None) -> str:
    sell = RAW["commercial"]["sell_in_units_2026"]
    retailers = W.retail.retailers
    rows = []
    for pid, by_retailer in sell["by_product_retailer"].items():
        if product and pid != product:
            continue
        for rid, series in by_retailer.items():
            rows.append([pid, retailers[rid]["name"]] + series + [sum(series)])
    return md_table(["Bar", "Retailer"] + sell["months"] + ["Total"], rows)


def t_margins() -> str:
    prices = {o: p["2026"] for o, p in RAW["commercial"]["prices_landed_usd_kg"].items() if "2026" in p}
    rows = []
    for p in RAW["production"]["products"]:
        if p["wholesale_usd"] and p["id"] != "MGNB":
            cost = 0.070 * p["cocoa_pct"] / 100 / 0.80 * prices[p["origin"]]
            rows.append([p["id"], f"${p['wholesale_usd']:.2f}", f"${prices[p['origin']]:.2f}", f"${cost:.2f}", f"${p['wholesale_usd'] - cost:.2f}"])
    return md_table(["Bar", "Wholesale", "Beans per kg", "Bean cost per bar", "After bean cost"], rows)


def t_cut_test(lot_id: str) -> str:
    cut = next(t for t in W.beans.lots[lot_id]["tests"] if t["type"] == "cut_test")
    keys = ["well_fermented", "partly_fermented", "slaty", "purple", "mouldy", "insect_damaged", "germinated", "flat"]
    return md_table(["Category", "Beans", "%"], [[k.replace("_", " ").capitalize(), cut[k], f"{100 * cut[k] / cut['beans']:.1f}"] for k in keys])


def t_redry() -> str:
    return md_table(["Date", "Moisture (%)"], [[fmt_date(d), v] for d, v in W.beans.lots["MG26-L02"]["redry_checks"]])


TABLES = {"lot_register": t_lot_register, "tickets": t_tickets, "findings": t_findings, "logger": t_logger, "panel": t_panel,
          "prices": t_prices, "purchases": t_purchases, "price_list": t_price_list, "sellin": t_sellin, "margins": t_margins,
          "cut_test": t_cut_test, "redry": t_redry}


def table(name: str, *args) -> str:
    return TABLES[name](*args)


def sellin_total(first_month: int, last_month: int) -> int:
    """Total 2026 sell-in for months first_month..last_month (1-based, inclusive)."""
    series = RAW["commercial"]["sell_in_units_2026"]["by_product_retailer"]
    return sum(sum(s[first_month - 1:last_month]) for by_retailer in series.values() for s in by_retailer.values())


CSS = """
@page { size: Letter; margin: 0.65in 0.7in 0.75in; }
@page landscape { size: Letter landscape; margin: 0.5in 0.6in; }
* { box-sizing: border-box; }
body { font-family: 'Helvetica Neue', Arial, sans-serif; color: #222; font-size: 10.2pt; line-height: 1.45; }
h1 { font-size: 17pt; margin: 4px 0 2px; color: var(--brand); }
h2 { font-size: 12.5pt; margin: 16px 0 5px; color: var(--brand); }
h3 { font-size: 10.8pt; margin: 12px 0 4px; }
p { margin: 5px 0 7px; } ul, ol { margin: 4px 0 8px; padding-left: 20px; } li { margin: 2px 0; }
table { border-collapse: collapse; width: 100%; margin: 8px 0 10px; font-size: 8.6pt; page-break-inside: auto; }
th, td { border: 1px solid #c9c2bb; padding: 3px 5px; text-align: left; vertical-align: top; }
th { background: #f3ece6; }
tr { page-break-inside: avoid; }
figure { margin: 10px 0; text-align: center; page-break-inside: avoid; }
figure img { max-width: 100%; max-height: 3.5in; }
figure.half img { max-width: 60%; } figure.scan img { max-height: 8.2in; border: 1px solid #ccc; }
figcaption { font-size: 8.4pt; color: #555; margin-top: 3px; }
blockquote { border-left: 3px solid var(--brand); margin: 8px 0; padding: 2px 10px; color: #444; background: #faf7f3; }
.letterhead { display: flex; justify-content: space-between; align-items: flex-end; border-bottom: 3px solid var(--brand); padding-bottom: 6px; margin-bottom: 10px; }
.org { font-weight: 700; font-size: 12pt; color: var(--brand); letter-spacing: .02em; }
.dept { font-size: 8.5pt; color: #666; text-transform: uppercase; letter-spacing: .08em; }
.meta { font-size: 8.6pt; color: #555; margin: 2px 0 12px; }
.meta span { margin-right: 14px; }
.box { border: 1.5px solid var(--brand); padding: 8px 10px; margin: 8px 0; }
.fields td:first-child { width: 28%; background: #f7f3ef; font-weight: 600; }
.email-header { width: auto; border: none; font-size: 9.5pt; margin: 0 0 6px; }
.email-header td { border: none; padding: 1px 10px 1px 0; }
.email-header td:first-child { color: #777; }
.email-subject { font-size: 14pt; font-weight: 700; margin: 4px 0 6px; }
.slide { page: landscape; page-break-after: always; height: 7.1in; overflow: hidden; padding: 0.15in 0.2in; border-top: 10px solid var(--brand); font-size: 13pt; }
.slide h1 { font-size: 32pt; margin-top: 1.6in; } .slide h1 + p { font-size: 14pt; }
.slide h2 { font-size: 22pt; margin-top: 4px; } .slide p, .slide li { font-size: 14pt; } .slide figure img { max-height: 3.3in; }
.slide table { font-size: 9pt; } .slide figcaption { font-size: 9pt; }
.cert-title { text-align: center; font-size: 15pt; font-weight: 700; letter-spacing: .08em; margin: 6px 0; color: var(--brand); }
.stamp { display: inline-block; border: 2px solid var(--brand); color: var(--brand); padding: 4px 12px; font-weight: 700; transform: rotate(-3deg); margin-top: 8px; }
.public h1 { font-size: 26pt; } .public .cover { background: var(--brand); color: white; padding: 24px; margin-bottom: 14px; }
.public .cover h1 { color: white; }

/* Cocoarynth house style, from the cocoarynth-trace app */
.house-cocoarynth { --cocoa: #3f2922; --coral: #db6b58; --yellow: #e8b94f; --green: #66845b; --cream: #fffdf8; --line: #ded7ca; --muted: #746a63;
  font-family: Inter, sans-serif; color: #2b211d; font-size: 9.6pt; }
.house-cocoarynth h1, .house-cocoarynth h2, .house-cocoarynth .cert-title { font-family: Georgia, 'Times New Roman', serif; color: var(--cocoa); font-weight: 700; }
.house-cocoarynth h1 { font-size: 20pt; line-height: 1.1; margin-top: 2px; }
.house-cocoarynth h2 { font-size: 13pt; border-bottom: 1px solid var(--line); padding-bottom: 2px; }
.house-cocoarynth h3 { color: var(--green); font-size: 8pt; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }
.house-cocoarynth table { border-top: 2px solid var(--cocoa); }
.house-cocoarynth th, .house-cocoarynth td { border: none; border-bottom: 1px solid var(--line); padding: 4px 6px; }
.house-cocoarynth th { background: #faf7f1; color: var(--muted); font-size: 7.2pt; letter-spacing: .04em; text-transform: uppercase; }
.house-cocoarynth .fields td:first-child { background: #faf7f1; color: var(--muted); }
.house-cocoarynth blockquote { border-left: 3px solid var(--yellow); background: var(--cream); color: #2b211d; }
.house-cocoarynth .box { border: 1px solid var(--line); border-top: 4px solid var(--green); border-radius: 6px; background: var(--cream); }
.house-cocoarynth .stamp { border-color: var(--coral); color: var(--coral); }
.house-cocoarynth figcaption { color: var(--muted); }
.house-cocoarynth .meta span { display: inline-block; background: #ebe2d4; color: var(--cocoa); border-radius: 99px; padding: 1px 9px; margin: 0 6px 0 0; font-weight: 600; font-size: 7.8pt; }
.brandbar { display: flex; align-items: center; gap: 10px; background: var(--cocoa); color: white; border-bottom: 4px solid var(--yellow); padding: 7px 12px; margin-bottom: 14px; }
.brandbar img { width: 40px; height: 40px; border-radius: 50%; }
.brandbar .org { color: white; font-family: Georgia, serif; font-size: 12.5pt; font-weight: 700; letter-spacing: .01em; }
.brandbar .tagline { color: var(--yellow); font-size: 6.6pt; letter-spacing: .16em; text-transform: uppercase; }
.brandbar .right { margin-left: auto; text-align: right; color: #dacfc8; font-size: 7.2pt; letter-spacing: .08em; text-transform: uppercase; line-height: 1.6; }
.house-cocoarynth .slide { background: #f7efe3; border-top: none; padding: 0; font-size: 13pt; }
.house-cocoarynth .slide > :not(.slide-band) { margin-left: 0.3in; margin-right: 0.3in; }
.slide-band { display: flex; align-items: center; gap: 8px; background: var(--cocoa); border-bottom: 4px solid var(--yellow); color: white; padding: 5px 0.3in; margin-bottom: 10px;
  font-family: Georgia, serif; font-size: 10pt; }
.slide-band img { width: 26px; height: 26px; border-radius: 50%; }
.slide-band span { margin-left: auto; color: var(--yellow); font-family: Inter, sans-serif; font-size: 7pt; letter-spacing: .16em; text-transform: uppercase; }
.house-cocoarynth .slide.title-slide { display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; border-bottom: 10px solid var(--cocoa); }
.title-slide img.full-logo { width: 2.9in; margin-bottom: -0.2in; }
.house-cocoarynth .slide.title-slide h1 { margin-top: 0; font-size: 30pt; }
.house-cocoarynth .slide h2 { font-size: 22pt; border-bottom: none; margin-top: 4px; }
.house-cocoarynth.public .cover { background: #f7efe3; color: var(--cocoa); border-bottom: 6px solid var(--cocoa); padding: 0 24px 18px; text-align: center; }
.house-cocoarynth.public .cover img { width: 3in; display: block; margin: 0 auto -0.25in; }
.house-cocoarynth.public .cover h1 { color: var(--cocoa); font-size: 26pt; }
.house-cocoarynth.public .cover .when { color: var(--muted); font-size: 9pt; letter-spacing: .12em; text-transform: uppercase; }

/* Río Claro cooperative: plain, typed, centered letterhead */
.house-cooperative { font-family: 'Times New Roman', Times, serif; font-size: 10.8pt; color: #1b1b1b; }
.house-cooperative .letterhead { display: block; text-align: center; border-bottom: 4px double var(--brand); }
.house-cooperative .org { font-size: 14pt; text-transform: uppercase; letter-spacing: .06em; }
.house-cooperative .dept { font-style: italic; text-transform: none; letter-spacing: 0; font-size: 10pt; color: #333; }
.house-cooperative h1 { text-align: center; font-size: 14pt; color: #1b1b1b; text-transform: uppercase; }
.house-cooperative h2 { font-size: 11.5pt; color: #1b1b1b; text-decoration: underline; }
.house-cooperative th, .house-cooperative td { border-color: #555; } .house-cooperative th { background: #e6e6e6; }
.house-cooperative .meta { text-align: center; color: #333; }

/* Akwapim Ridge association: Gill Sans word-processor report with a gold top bar and banded tables */
.house-association { font-family: 'Gill Sans', 'Gill Sans MT', sans-serif; font-size: 10.6pt; color: #222; }
.house-association .letterhead { border-top: 9px solid var(--brand); border-bottom: 1px solid #bbb; padding-top: 7px; align-items: center; }
.house-association .org { font-size: 15pt; font-weight: 600; color: #222; text-transform: uppercase; letter-spacing: .03em; }
.house-association .dept { color: var(--brand); font-weight: 600; }
.house-association h1 { color: #222; font-weight: 600; font-size: 16pt; }
.house-association h2 { color: var(--brand); font-weight: 600; }
.house-association h2::before { content: ""; display: inline-block; width: 9px; height: 9px; background: var(--brand); margin-right: 7px; }
.house-association th { background: var(--brand); color: white; } .house-association th, .house-association td { border-color: #cfc7b0; }
.house-association tbody tr:nth-child(even) td { background: #f8f4e6; }

/* Loma Verde field team: Trebuchet, rounded letterhead box, dotted headings */
.house-fieldteam { font-family: 'Trebuchet MS', sans-serif; font-size: 10pt; color: #24301f; }
.house-fieldteam .letterhead { border: 1.5px solid var(--brand); border-radius: 10px; background: #eef4e9; padding: 8px 14px; align-items: center; }
.house-fieldteam .org { font-size: 13pt; color: var(--brand); }
.house-fieldteam .dept { text-transform: none; letter-spacing: 0; color: #4b5a45; }
.house-fieldteam h1 { font-size: 15pt; } .house-fieldteam h2 { font-size: 11.5pt; border-bottom: 2px dotted var(--brand); padding-bottom: 2px; }
.house-fieldteam th { background: #dde9d4; } .house-fieldteam th, .house-fieldteam td { border-color: #b5c6a9; }

/* Tsaravola estate: small, polished letterhead */
.house-estate { font-family: Palatino, 'Palatino Linotype', 'Book Antiqua', serif; font-size: 10.4pt; color: #2a2220; }
.house-estate .letterhead { border-bottom: 1px solid var(--brand); }
.house-estate .org { font-variant: small-caps; font-size: 16pt; font-weight: 400; letter-spacing: .12em; }
.house-estate h1, .house-estate h2 { font-weight: 400; font-style: italic; }
.house-estate th { background: none; border-color: var(--brand); color: var(--brand); } .house-estate td { border-color: #d9cbc6; }

/* CertiOrgánica certifier: formal Verdana with a side bar */
.house-certifier { font-family: Verdana, Geneva, sans-serif; font-size: 8.8pt; color: #1c2a26; }
.house-certifier .letterhead { align-items: center; border-bottom: none; border-left: 12px solid var(--brand); background: #eef3f1; padding: 8px 12px; }
.house-certifier .org { font-size: 13pt; }
.house-certifier .dept { color: #44514d; }
.house-certifier h1 { font-size: 12.5pt; text-transform: uppercase; letter-spacing: .05em; color: #1c2a26; }
.house-certifier h2 { font-size: 9.5pt; background: var(--brand); color: white; padding: 3px 7px; text-transform: uppercase; letter-spacing: .05em; }
.house-certifier th { background: var(--brand); color: white; } .house-certifier th, .house-certifier td { border-color: #8a9894; }

/* Cascadia lab: clean Helvetica Neue with hairlines and a boxed certificate title */
.house-lab { font-family: 'Helvetica Neue', Helvetica, sans-serif; font-size: 9pt; color: #1a2833; }
.house-lab .letterhead { border-top: 1px solid #1a2833; border-bottom: 1px solid #1a2833; padding: 8px 0; align-items: center; }
.house-lab .org { font-weight: 300; font-size: 19pt; color: var(--brand); letter-spacing: -.01em; }
.house-lab .dept { color: #50606c; letter-spacing: .04em; }
.house-lab .cert-title { border: 1.5px solid var(--brand); color: var(--brand); font-weight: 500; font-size: 12pt; letter-spacing: .3em; padding: 5px; margin: 10px 0; }
.house-lab h2 { font-weight: 500; font-size: 10.5pt; color: #1a2833; text-transform: uppercase; letter-spacing: .08em; }
.house-lab th { background: #e7f0f7; font-weight: 500; } .house-lab th, .house-lab td { border: none; border-bottom: 0.75px solid #b7c7d3; }

/* Bluefin forwarder: industrial form with a boxed header and typed values */
.house-forwarder { font-family: 'Arial Narrow', Arial, sans-serif; font-size: 10pt; color: #111; }
.house-forwarder .letterhead { border: 2px solid #111; padding: 0; align-items: stretch; }
.house-forwarder .letterhead > div:first-child { background: var(--brand); padding: 7px 12px; flex: 1; }
.house-forwarder .letterhead > div:last-child { padding: 7px 12px; border-left: 2px solid #111; font-family: 'Courier New', monospace; display: flex; align-items: center; color: #111; font-size: 9.5pt; font-weight: 700; }
.house-forwarder .org { color: white; font-size: 15pt; font-weight: 800; font-style: italic; text-transform: uppercase; letter-spacing: .03em; }
.house-forwarder .letterhead > div:first-child .dept { color: #e8eef5; }
.house-forwarder h1 { font-size: 14pt; color: #111; text-transform: uppercase; }
.house-forwarder h2 { font-size: 10.5pt; color: #111; text-transform: uppercase; border-bottom: 1.5px solid #111; }
.house-forwarder th { background: #222; color: white; text-transform: uppercase; font-size: 7.6pt; } .house-forwarder th, .house-forwarder td { border-color: #111; }
.house-forwarder td { font-family: 'Courier New', monospace; }

/* Northwind carrier: Rockwell slab wordmark, two-tone rule, Charter body */
.house-carrier { font-family: Charter, 'Bitstream Charter', Georgia, serif; font-size: 10.5pt; color: #1d2a33; }
.house-carrier .letterhead { position: relative; border-bottom: 5px solid var(--brand); margin-bottom: 20px; align-items: center; }
.house-carrier .letterhead::after { content: ""; position: absolute; left: 0; right: 0; bottom: -10px; height: 2px; background: #8fbcd4; }
.house-carrier .org { font-family: Rockwell, 'Roboto Slab', serif; font-size: 19pt; font-weight: 700; color: var(--brand); }
.house-carrier .dept { font-family: Rockwell, serif; color: #4d6472; }
.house-carrier h1, .house-carrier h2 { font-family: Rockwell, serif; color: var(--brand); }
.house-carrier th { background: #dceaf2; } .house-carrier th, .house-carrier td { border-color: #9fb7c5; }

/* Emails: Cocoarynth's mail client prints the header; each sender's own client and signature set the body */
.house-retail { font-family: Arial, Helvetica, sans-serif; font-size: 10pt; color: #202124; }
.house-retail .email-subject { font-weight: 400; font-size: 16pt; }
.sender { margin: 8px 0 12px; }
.org-larkspur-market .sender { font-family: 'Avenir Next', Avenir, sans-serif; font-size: 10.5pt; color: #1f1f1f; }
.org-larkspur-market .sender > p:last-of-type { color: var(--brand); font-weight: 600; border-top: 2px solid var(--brand); padding-top: 4px; display: inline-block; }
.org-pantry-lane .sender { font-family: Arial, sans-serif; font-size: 9.5pt; border-top: 5px solid var(--brand); background: #fff7f0; padding: 6px 14px 4px; }
.org-pantry-lane .sender > p:last-of-type { color: var(--brand); font-weight: 700; text-transform: uppercase; letter-spacing: .06em; font-size: 8.5pt; }
.org-steeple-saucer .sender { font-family: Helvetica, sans-serif; font-size: 11.5pt; line-height: 1.55; color: #111; }
"""

LABELS = {
    "en": {"date": "Date", "by": "Prepared by", "ref": "Ref.", "page": "Page", "of": "of", "audience": "For"},
    "es": {"date": "Fecha", "by": "Preparado por", "ref": "Ref.", "page": "Página", "of": "de", "audience": "Para"},
}


def author_org(author: str) -> str:
    return PEOPLE[author]["org"] if author in PEOPLE else author


def header_html(brief: dict, front: dict) -> str:
    lang = brief["language"]
    labels = LABELS[lang]
    org = front.get("org") or author_org(brief["author"])
    dept = front.get("dept", "")
    when = fmt_date(str(brief["date"]), lang)
    kind = brief["type"]
    if kind == "email":
        rows = [("From", front.get("from", person(brief["author"]))), ("To", front.get("to", "")), ("Cc", front.get("cc", "")),
                ("Date", front.get("sent", when)), ("Attachments", front.get("attachments", ""))]
        cells = "".join(f"<tr><td>{k}:</td><td>{html.escape(v)}</td></tr>" for k, v in rows if v)
        return f'<div class="email-subject">{html.escape(brief["title"].removeprefix("Email: ").removeprefix("Email thread: "))}</div><table class="email-header">{cells}</table><hr>'
    ref = html.escape(front.get("ref", brief["id"]))
    if HOUSE.get(org) == "cocoarynth":
        letterhead = (f'<div class="brandbar"><img src="{LOGO_MARK}"><div><div class="org">{html.escape(ORGS[org])}</div>'
                      f'<div class="tagline">Lose yourself in chocolate</div></div><div class="right">{html.escape(dept)}<br>{ref}</div></div>')
    else:
        lines = [d for d in (dept, LOCATIONS.get(org, "")) if d]
        sub = "".join(f'<div class="dept">{html.escape(d)}</div>' for d in lines)
        letterhead = f'<div class="letterhead"><div><div class="org">{html.escape(ORGS.get(org, org))}</div>{sub}</div><div class="dept">{ref}</div></div>'
    if kind == "slide_deck":
        return ""
    if kind == "public_report":
        return f'<div class="cover"><img src="{LOGO_FULL}"><h1>{html.escape(brief["title"])}</h1><div class="when">{when}</div></div>'
    if kind == "lab_certificate":
        return letterhead + f'<div class="cert-title">{html.escape(front.get("heading", "CERTIFICATE OF ANALYSIS"))}</div>'
    if kind == "letter":
        return letterhead + f'<p style="text-align:right">{when}</p>'
    meta = f'<div class="meta"><span>{labels["date"]}: {when}</span><span>{labels["by"]}: {html.escape(person(brief["author"]))}</span>'
    if brief.get("audience"):
        meta += f'<span>{labels["audience"]}: {html.escape(brief["audience"])}</span>'
    return letterhead + f'<h1>{html.escape(brief["title"])}</h1>' + meta + "</div>"


def split_front(text: str) -> tuple[dict, str]:
    if text.startswith("---\n"):
        _, front, body = text.split("---\n", 2)
        return yaml.safe_load(front) or {}, body
    return {}, text


def body_html(brief: dict, body: str) -> str:
    env = jinja2.Environment(undefined=jinja2.StrictUndefined, autoescape=False)
    text = env.from_string(body).render(chart=chart, photo=photo, scan=scan, table=table, W=W, fmt_date=fmt_date, sellin_total=sellin_total)
    md = markdown.Markdown(extensions=["tables", "attr_list", "md_in_html", "sane_lists"] + (["nl2br"] if brief["type"] == "letter" else []))
    if brief["type"] == "slide_deck":
        slides = [s for s in text.split("\n## ") if s.strip()]
        parts = []
        band = f'<div class="slide-band"><img src="{LOGO_MARK}">Cocoarynth<span>Lose yourself in chocolate</span></div>'
        for i, slide in enumerate(slides):
            if i == 0 and slide.startswith("# "):
                parts.append(f'<section class="slide title-slide"><img class="full-logo" src="{LOGO_FULL}">{md.reset().convert(slide)}</section>')
            else:
                parts.append(f'<section class="slide">{band}{md.reset().convert("## " + slide)}</section>')
        return "".join(parts)
    converted = md.convert(text)
    if brief["type"] == "email":
        sender, hr, rest = converted.partition("<hr />")
        return f'<div class="sender">{sender}</div>{hr}{rest}'
    return converted


def render_brief(page, brief: dict, index: str) -> Path:
    draft = DATA / "drafts" / f"{brief['id']}.md"
    front, body = split_front(draft.read_text(encoding="utf-8"))
    org = front.get("org") or author_org(brief["author"])
    labels = LABELS[brief["language"]]
    house = HOUSE.get(org, "retail")
    classes = f"house-{house} org-{org}" + (" public" if brief["type"] == "public_report" else "")
    fonts = INTER_FACE if house == "cocoarynth" else ""
    document = (f"<html lang='{brief['language']}'><head><meta charset='utf-8'><style>{fonts}{CSS}</style></head>"
                f"<body class='{classes}' style='--brand:{BRAND.get(org, '#444')}'>{header_html(brief, front)}{body_html(brief, body)}</body></html>")
    out = OUTPUT / index / f"{brief['id']}.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)
    page.set_content(document)
    page.evaluate("() => document.fonts.ready.then(() => true)")
    footer_font = {"cocoarynth": "color:#3f2922;border-top:0.5px solid #ded7ca;padding-top:3px", "cooperative": "font-family:Times New Roman,serif",
                   "association": "font-family:Gill Sans,sans-serif", "fieldteam": "font-family:Trebuchet MS,sans-serif",
                   "estate": "font-family:Palatino,serif", "certifier": "font-family:Verdana,sans-serif", "lab": "font-family:Helvetica Neue,sans-serif",
                   "forwarder": "font-family:Arial Narrow,sans-serif", "carrier": "font-family:Charter,serif"}.get(house, "")
    footer = (f"<div style='font-size:7px;color:#888;width:100%;margin:0 0.7in;display:flex;justify-content:space-between;{footer_font}'>"
              f"<span>{html.escape(ORGS.get(org, org))} · {html.escape(brief['title'])}</span>"
              f"<span>{labels['page']} <span class='pageNumber'></span> {labels['of']} <span class='totalPages'></span></span></div>")
    page.pdf(path=str(out), print_background=True, prefer_css_page_size=True, display_header_footer=True,
             header_template="<div></div>", footer_template=footer,
             landscape=brief["type"] == "slide_deck")
    return out


def all_briefs() -> list[tuple[str, dict]]:
    out = []
    for path in sorted((DATA / "briefs").glob("cocoarynth-*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        out += [(doc["index"], b) for b in doc["briefs"]]
    return out


def main(selected: list[str]) -> None:
    briefs = [(i, b) for i, b in all_briefs() if not selected or b["id"] in selected]
    missing = [b["id"] for _, b in briefs if not (DATA / "drafts" / f"{b['id']}.md").is_file()]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        for index, brief in briefs:
            if brief["id"] in missing:
                continue
            out = render_brief(page, brief, index)
            print(f"{index}/{out.name} ({out.stat().st_size // 1024} KB)")
        browser.close()
    if missing:
        print(f"\nNo draft yet for {len(missing)} brief(s): {', '.join(missing)}")


if __name__ == "__main__":
    main(sys.argv[1:])
