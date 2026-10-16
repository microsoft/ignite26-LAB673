"""Draw every chart, map and diagram in data/cocoarynth/briefs/assets.yaml from the world data.

Usage: .venv-cocoarynth/bin/python scripts/cocoarynth/charts.py
"""

import json
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Patch

DATA = Path(__file__).resolve().parents[2] / "data" / "cocoarynth"
OUT = DATA / "assets" / "charts"
COLORS = {"ecuador": "#c58b3c", "ghana": "#7a4a2a", "peru": "#d4b04a", "madagascar": "#b5482f", "dominican-republic": "#6f8f5a"}
ORIGIN_LABEL = {"ecuador": "Ecuador", "ghana": "Ghana", "peru": "Peru", "madagascar": "Madagascar", "dominican-republic": "Dominican Rep."}
PRODUCT_COLORS = {"EC72": "#c58b3c", "EC85": "#8f5e22", "GH68": "#7a4a2a", "PE70": "#d4b04a", "MG70": "#b5482f", "MGNB": "#e07a5f"}
RETAILER_COLORS = {"cacao-cabinet": "#b5482f", "pantry-lane": "#d4b04a", "hoshizora-foods": "#4a5d7a",
                   "larkspur-market": "#7a4a2a", "steeple-saucer": "#6f8f5a"}

# parse_math off: "$4.90" must render as text, not mathtext.
plt.rcParams.update({"font.family": "Helvetica", "font.size": 9, "axes.spines.top": False, "axes.spines.right": False,
                     "text.parse_math": False, "axes.titlepad": 10})


def w(name: str) -> dict:
    return json.loads((DATA / "world" / f"{name}.json").read_text(encoding="utf-8"))


def save(fig, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{name}.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"chart {name}")


def logger_04() -> None:
    retail = w("retail")
    logger = retail["loggers"][0]
    times = [int(t[:2]) + int(t[3:]) / 60 for t, _ in logger["readings"]]
    values = [v for _, v in logger["readings"]]
    low, high = retail["storage_guidance"]["recommended_c"]
    risk = retail["storage_guidance"]["bloom_risk_above_c"]
    fig, ax = plt.subplots(figsize=(7.5, 3.4))
    ax.axhspan(low, high, color="#9cc9a4", alpha=0.35, label=f"Recommended {low}–{high} °C")
    ax.axhline(risk, color="#b5482f", linestyle="--", linewidth=1, label=f"Bloom risk above {risk} °C")
    ax.plot(times, values, color="#7a4a2a", linewidth=2, marker="o", markersize=2.5)
    peak = max(range(len(values)), key=values.__getitem__)
    ax.annotate(f"{values[peak]} °C at {logger['readings'][peak][0]}", (times[peak], values[peak]),
                xytext=(times[peak] + 1, values[peak] + 1.5), arrowprops={"arrowstyle": "->"}, fontsize=8)
    ax.set_xticks(range(6, 21, 2), [f"{h:02d}:00" for h in range(6, 21, 2)])
    ax.set_ylim(10, 38)
    ax.set_ylabel("Air temperature (°C)")
    ax.set_title(f"{logger['id']} · Overflow Bay 4, Riverbend depot · 14 July 2026", fontsize=10)
    ax.grid(alpha=0.3)
    ax.legend(loc="upper left", fontsize=7.5)
    save(fig, "logger-04")


def panel_samples() -> list[dict]:
    products = {p["id"]: p for p in w("production")["products"]}
    samples = w("sensory")["panels"][0]["samples"]
    for sample in samples:
        sample["origin"] = products[sample["product"]]["origin"]
    return sorted(samples, key=lambda s: s["overall"], reverse=True)


def panel_overall() -> None:
    samples = panel_samples()
    labels = [ORIGIN_LABEL[s["origin"]] + (" (trial)" if s["product"] == "DR70" else "") for s in samples][::-1]
    fig, ax = plt.subplots(figsize=(6.8, 2.8))
    bars = ax.barh(labels, [s["overall"] for s in samples][::-1], color=[COLORS[s["origin"]] for s in samples][::-1])
    ax.bar_label(bars, fmt="%.1f", padding=3)
    ax.set_xlim(0, 10)
    ax.set_xlabel("Mean overall quality (0–10), 9 panelists")
    ax.set_title("September 2026 blind tasting: overall score by origin", fontsize=10)
    save(fig, "panel-overall")


def radar(ax, attributes, series, label_size: float = 7.5, ring_labels: bool = True) -> None:
    angles = np.linspace(0, 2 * np.pi, len(attributes), endpoint=False).tolist()
    for label, values, color in series:
        closed = values + values[:1]
        ax.plot(angles + angles[:1], closed, color=color, linewidth=1.8, label=label)
        ax.fill(angles + angles[:1], closed, color=color, alpha=0.15)
    ax.set_xticks(angles, [a.replace("_", " ").title() for a in attributes], fontsize=label_size)
    ax.tick_params(axis="x", pad=7)
    ax.set_ylim(0, 10)
    if ring_labels:
        ax.set_yticks([2, 4, 6, 8], ["2", "4", "6", "8"], fontsize=6.5, color="#666")
        for tick in ax.get_yticklabels():
            tick.set_bbox({"facecolor": "white", "edgecolor": "none", "pad": 0.8, "alpha": 0.9})
        # Scale labels sit between Bitterness and Acidity, where profiles are usually low.
        ax.set_rlabel_position(np.degrees((angles[-2] + angles[-1]) / 2))
    else:
        ax.set_yticks([2, 4, 6, 8], [])


def panel_radars() -> None:
    attributes = [a for a in w("sensory")["attributes"] if a != "off_flavor"]
    samples = {s["origin"]: s for s in panel_samples()}
    fig, ax = plt.subplots(figsize=(5, 5), subplot_kw={"polar": True})
    radar(ax, attributes, [(ORIGIN_LABEL[o], [samples[o]["scores"][a] for a in attributes], COLORS[o]) for o in ("madagascar", "ghana")], 9, ring_labels=False)
    ax.legend(loc="upper right", bbox_to_anchor=(1.32, 1.12), fontsize=8)
    fig.text(0.5, 0.02, "Rings at 2, 4, 6 and 8 on a 0–10 scale", ha="center", fontsize=7.5, color="#666")
    save(fig, "panel-radar-madagascar-vs-ghana")

    fig, axes = plt.subplots(1, 5, figsize=(13, 3.3), subplot_kw={"polar": True})
    for ax, sample in zip(axes, panel_samples()):
        radar(ax, attributes, [(ORIGIN_LABEL[sample["origin"]], [sample["scores"][a] for a in attributes], COLORS[sample["origin"]])], 7, ring_labels=False)
        ax.set_title(f"{ORIGIN_LABEL[sample['origin']]} · {sample['overall']}", fontsize=10, y=1.22, fontweight="bold")
    fig.text(0.5, 0.04, "Rings at 2, 4, 6 and 8 on a 0–10 scale", ha="center", fontsize=7.5, color="#666")
    fig.subplots_adjust(wspace=0.55, top=0.76, bottom=0.14)
    save(fig, "panel-radar-all")


def redry_moisture() -> None:
    lot = next(l for l in w("beans")["lots"] if l["id"] == "MG26-L02")
    limit = w("beans")["receiving_limits"]["moisture_max_pct"]
    days = [date.fromisoformat(d) for d, _ in lot["redry_checks"]]
    values = [v for _, v in lot["redry_checks"]]
    fig, ax = plt.subplots(figsize=(7, 3))
    ax.plot(days, values, color="#b5482f", marker="o", linewidth=2)
    ax.axhline(limit, color="#333", linestyle="--", linewidth=1, label=f"Limit {limit}%")
    for day, value in zip(days, values):
        below = value < limit + 0.05
        ax.annotate(f"{value}", (day, value), xytext=(0, -13 if below else 7), textcoords="offset points", ha="center", fontsize=7.5)
    ax.set_ylabel("Moisture (% wet basis)")
    ax.set_ylim(6.7, 9.0)
    ax.set_title("MG26-L02 moisture during re-drying, August 2026", fontsize=10)
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%d %b"))
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    save(fig, "redry-moisture-mg26-l02")


def landed_price() -> None:
    commercial = w("commercial")
    years = ["2024", "2025", "2026"]
    ref = commercial["market_reference"]["by_year"]
    series = [("World reference", ref, "#9a9a9a")] + [
        (ORIGIN_LABEL[o], p, COLORS[o]) for o, p in commercial["prices_landed_usd_kg"].items()]
    fig, ax = plt.subplots(figsize=(8, 3.8))
    width = 0.14
    for i, (label, prices, color) in enumerate(series):
        xs = [j + (i - (len(series) - 1) / 2) * width for j, y in enumerate(years) if y in prices]
        bars = ax.bar(xs, [prices[y] for y in years if y in prices], width * 0.92, color=color, label=label,
                      hatch="//" if label == "World reference" else None, edgecolor="white" if label == "World reference" else None)
        ax.bar_label(bars, fmt="%.2f", fontsize=6.5, padding=2)
    ax.set_xticks(range(len(years)), years, fontsize=10)
    ax.set_ylabel("USD per kg")
    ax.set_title("Landed bean price by origin vs world reference price", fontsize=10)
    ax.legend(fontsize=7.5, ncol=6, loc="upper center", bbox_to_anchor=(0.5, -0.1), frameon=False)
    ax.set_ylim(0, 15.5)
    save(fig, "landed-price-by-origin")


def purchases() -> None:
    data = w("commercial")["purchases_kg"]
    years = ["2024", "2025", "2026"]
    fig, ax = plt.subplots(figsize=(6.5, 3.2))
    bottom = np.zeros(len(years))
    for origin, values in data.items():
        series = np.array([values.get(y, 0) for y in years])
        ax.bar(years, series, bottom=bottom, color=COLORS[origin], label=ORIGIN_LABEL[origin])
        bottom += series
    for i, total in enumerate(bottom):
        ax.annotate(f"{int(total):,} kg", (i, total), xytext=(0, 4), textcoords="offset points", ha="center", fontsize=8.5)
    ax.set_ylim(0, bottom.max() * 1.12)
    ax.yaxis.set_major_formatter(matplotlib.ticker.StrMethodFormatter("{x:,.0f}"))
    ax.set_ylabel("Dried beans purchased (kg)")
    ax.set_title("Bean purchases by origin (2026 through September)", fontsize=10)
    ax.legend(fontsize=7.5, loc="upper left", bbox_to_anchor=(1.01, 1), frameon=False)
    save(fig, "purchases-by-origin")


def sellin_by_product() -> None:
    sell = w("commercial")["sell_in_units_2026"]
    months = sell["months"]
    fig, ax = plt.subplots(figsize=(7.5, 3.4))
    bottom = np.zeros(len(months))
    for product, by_retailer in sell["by_product_retailer"].items():
        series = np.sum([np.array(v) for v in by_retailer.values()], axis=0)
        ax.bar(months, series, bottom=bottom, color=PRODUCT_COLORS[product], label=product)
        bottom += series
    for i, total in enumerate(bottom):
        ax.annotate(f"{int(total):,}", (i, total), xytext=(0, 3), textcoords="offset points", ha="center", fontsize=7.5)
    ax.set_ylim(0, bottom.max() * 1.1)
    ax.yaxis.set_major_formatter(matplotlib.ticker.StrMethodFormatter("{x:,.0f}"))
    ax.set_ylabel("Bars sold to retailers")
    ax.set_title("2026 sell-in by product", fontsize=10)
    ax.legend(fontsize=7.5, ncol=6, loc="upper center", bbox_to_anchor=(0.5, -0.08), frameon=False)
    save(fig, "sellin-by-product-2026")


def sellin_mg70() -> None:
    sell = w("commercial")["sell_in_units_2026"]
    retailers = {r["id"]: r["name"] for r in w("retail")["retailers"]}
    by_retailer = sell["by_product_retailer"]["MG70"]
    fig, ax = plt.subplots(figsize=(8, 3.4))
    width = 0.8 / len(by_retailer)
    x = np.arange(len(sell["months"]))
    for i, (retailer, series) in enumerate(by_retailer.items()):
        bars = ax.bar(x + (i - (len(by_retailer) - 1) / 2) * width, series, width * 0.92,
                      color=RETAILER_COLORS[retailer], label=retailers[retailer])
        ax.bar_label(bars, labels=[f"{v:,}" if v else "" for v in series], fontsize=6, padding=1.5)
    ax.set_xticks(x, sell["months"])
    ax.set_ylim(0, max(max(s) for s in by_retailer.values()) * 1.12)
    ax.yaxis.set_major_formatter(matplotlib.ticker.StrMethodFormatter("{x:,.0f}"))
    ax.set_ylabel("Bars")
    ax.set_title("Madagascar Tsaravola 70% (MG70) sell-in by retailer, 2026", fontsize=10)
    ax.legend(fontsize=7.5, ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.08), frameon=False)
    ax.text(0.01, 0.97, "Hoshizora Foods orders quarterly", transform=ax.transAxes, fontsize=7, color="#555", va="top")
    save(fig, "sellin-mg70-by-retailer")


def margin_per_bar() -> None:
    prices = {o: p["2026"] for o, p in w("commercial")["prices_landed_usd_kg"].items() if "2026" in p}
    rows = []
    for product in w("production")["products"]:
        if product["wholesale_usd"] and product["id"] != "MGNB":
            bean_cost = 0.070 * product["cocoa_pct"] / 100 / 0.80 * prices[product["origin"]]
            rows.append((product["id"], product["wholesale_usd"], bean_cost, product["origin"]))
    fig, ax = plt.subplots(figsize=(7, 3.2))
    names = [r[0] for r in rows]
    costs = ax.bar(names, [r[2] for r in rows], color="#9a9a9a")
    ax.bar_label(costs, labels=[f"${r[2]:.2f}" for r in rows], label_type="center", color="white", fontsize=7)
    margins = [r[1] - r[2] for r in rows]
    bars = ax.bar(names, margins, bottom=[r[2] for r in rows], color=[COLORS[r[3]] for r in rows])
    ax.bar_label(bars, labels=[f"${m:.2f}" for m in margins], label_type="center", color="white", fontsize=8.5, fontweight="bold")
    for i, r in enumerate(rows):
        ax.annotate(f"${r[1]:.2f}", (i, r[1]), xytext=(0, 3), textcoords="offset points", ha="center", fontsize=8)
    ax.set_ylabel("USD per 70 g bar")
    ax.set_title("2026 wholesale price per bar, split into bean cost and what remains", fontsize=10)
    ax.set_ylim(0, 6.4)
    handles = [Patch(color="#9a9a9a", label="Bean cost per bar"), Patch(color="#a8724a", label="Wholesale price minus bean cost (colored by origin)")]
    ax.legend(handles=handles, fontsize=7.5, loc="upper center", bbox_to_anchor=(0.5, -0.1), ncol=2, frameon=False)
    save(fig, "margin-per-bar")


def cut_tests() -> None:
    categories = ["well_fermented", "partly_fermented", "slaty", "purple", "mouldy", "insect_damaged", "germinated", "flat"]
    palette = ["#7a4a2a", "#c58b3c", "#7d7d7d", "#8e5ea2", "#4f7f3a", "#c0392b", "#e0b03a", "#bbbbbb"]
    lots = [(l["id"], next(t for t in l["tests"] if t["type"] == "cut_test")) for l in w("beans")["lots"]
            if any(t["type"] == "cut_test" for t in l["tests"])]
    fig, ax = plt.subplots(figsize=(7.5, 3.4))
    left = np.zeros(len(lots))
    for category, color in zip(categories, palette):
        values = np.array([t[category] for _, t in lots])
        ax.barh([l for l, _ in lots], values, left=left, color=color, label=category.replace("_", " ").capitalize())
        left += values
    ax.set_xlim(0, 300)
    ax.set_xlabel("Beans (of 300 cut)")
    ax.set_title("Cut-test results by bean lot, 2026", fontsize=10)
    ax.legend(fontsize=6.5, ncol=4, loc="upper center", bbox_to_anchor=(0.5, -0.18))
    save(fig, "cut-test-summary-2026")


def origins_map() -> None:
    points = {"ecuador": (-79.7, 0.9), "ghana": (-0.1, 6.0), "peru": (-78.5, -5.6), "madagascar": (48.3, -13.7), "dominican-republic": (-69.3, 18.8)}
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.set_xlim(-180, 180)
    ax.set_ylim(-60, 75)
    ax.axhspan(-20, 20, color="#e8d5b5", alpha=0.6, label="Cacao belt (20° N to 20° S)")
    ax.axhline(0, color="#999", linewidth=0.6)
    ax.grid(alpha=0.25)
    offsets = {"peru": (7, -11), "ecuador": (-8, 6), "dominican-republic": (7, 5)}
    for origin, (lon, lat) in points.items():
        ax.plot(lon, lat, "o", color=COLORS[origin], markersize=9)
        dx, dy = offsets.get(origin, (7, 5))
        ax.annotate(ORIGIN_LABEL[origin], (lon, lat), xytext=(dx, dy), textcoords="offset points", fontsize=8.5,
                    ha="right" if dx < 0 else "left")
    ax.plot(-122.7, 45.5, "*", color="#222", markersize=12)
    ax.annotate("Portland factory", (-122.7, 45.5), xytext=(6, 4), textcoords="offset points", fontsize=8)
    ax.set_xticks(range(-150, 181, 50))
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{abs(v):.0f}° {'W' if v < 0 else 'E'}" if v else "0°"))
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{abs(v):.0f}° {'S' if v < 0 else 'N'}" if v else "Equator"))
    ax.tick_params(labelsize=7.5)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title("Where Cocoarynth's cacao comes from", fontsize=10)
    ax.legend(fontsize=7, loc="lower left")
    save(fig, "origins-world-map")


def org_chart() -> None:
    import textwrap

    company = w("company")
    staff = [p for p in company["people"] if p["org"] == "cocoarynth"]
    fig, ax = plt.subplots(figsize=(11, 3.4))
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.add_patch(plt.Rectangle((0.36, 0.72), 0.28, 0.2, color="#7a4a2a"))
    ax.text(0.5, 0.82, "Cocoarynth Chocolate Works\nLeadership team", ha="center", va="center", color="white", fontsize=10)
    width = 1 / len(staff)
    for i, person in enumerate(staff):
        x = i * width + 0.006
        center = x + width / 2 - 0.006
        ax.plot([0.5, center], [0.72, 0.52], color="#999", linewidth=0.8)
        ax.add_patch(plt.Rectangle((x, 0.08), width - 0.012, 0.44, color="#f3ece6", ec="#7a4a2a"))
        role = textwrap.fill(person["role"], 16)
        ax.text(center, 0.3, f"{person['name']}\n\n{role}", ha="center", va="center", fontsize=8)
    save(fig, "org-chart")


if __name__ == "__main__":
    logger_04()
    panel_overall()
    panel_radars()
    redry_moisture()
    landed_price()
    purchases()
    sellin_by_product()
    sellin_mg70()
    margin_per_bar()
    cut_tests()
    origins_map()
    org_chart()
