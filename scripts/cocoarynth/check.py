"""Check rendered Cocoarynth PDFs against the briefs, and corpora.json against the briefs and mysteries.

Usage: .venv-cocoarynth/bin/python scripts/cocoarynth/check.py [--write-corpora]
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import pymupdf
import yaml

DATA = Path(__file__).resolve().parents[2] / "data" / "cocoarynth"
MAX_PDF_BYTES = 2_000_000
problems: list[str] = []


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).replace("\u00a0", " ").lower()


def expected_corpora(briefs: dict, mysteries: list[dict]) -> dict[str, list[str]]:
    corpora: dict[str, list[str]] = defaultdict(list)
    for bid, (index, _) in sorted(briefs.items()):
        corpora[index].append(f"documents/{index}/{bid}.pdf")
    part_a = {name.removesuffix(".pdf") for m in mysteries for e in m["evidence"] if e.get("part_a_file") for name in e["documents"]}
    file_source = sorted(f"documents/{briefs[bid][0]}/{bid}.pdf" for bid in part_a)
    return dict(sorted(corpora.items())) | {"file-source": file_source}


def check_corpora(briefs: dict, mysteries: list[dict]) -> None:
    """corpora.json drives lab ingestion, so it must list exactly the rendered briefs."""
    expected = expected_corpora(briefs, mysteries)
    path = DATA / "corpora.json"
    if "--write-corpora" in sys.argv:
        path.write_text(json.dumps(expected, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Wrote {path.relative_to(DATA.parents[1])}")
    elif json.loads(path.read_text(encoding="utf-8")) != expected:
        problems.append("corpora.json doesn't match the briefs; rerun with --write-corpora")


def main() -> None:
    briefs = {}
    for path in sorted((DATA / "briefs").glob("cocoarynth-*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for brief in doc["briefs"]:
            briefs[brief["id"]] = (doc["index"], brief)

    texts: dict[str, str] = {}
    pages = 0
    for bid, (index, brief) in briefs.items():
        draft = DATA / "drafts" / f"{bid}.md"
        pdf = DATA / "documents" / index / f"{bid}.pdf"
        if not draft.is_file():
            problems.append(f"{bid}: no draft")
            continue
        source = draft.read_text(encoding="utf-8")
        for visual in brief["visuals"]:
            if f'"{visual["asset"]}"' not in source:
                problems.append(f"{bid}: draft doesn't use visual {visual['asset']}")
        if not pdf.is_file() or pdf.stat().st_mtime < draft.stat().st_mtime:
            problems.append(f"{bid}: PDF missing or older than its draft")
            continue
        if pdf.stat().st_size > MAX_PDF_BYTES:
            problems.append(f"{bid}: PDF is {pdf.stat().st_size // 1024} KB")
        document = pymupdf.open(pdf)
        pages += len(document)
        texts[bid] = normalize(" ".join(page.get_text() for page in document))
        if len(texts[bid]) < 400:
            problems.append(f"{bid}: very little extractable text ({len(texts[bid])} chars)")

    questions = yaml.safe_load((DATA / "questions.yaml").read_text(encoding="utf-8"))
    check_corpora(briefs, questions["mysteries"])

    print(f"\n{len(texts)} PDFs, {pages} pages")
    if problems:
        print(f"{len(problems)} problem(s):")
        for problem in problems:
            print(f"  - {problem}")
        sys.exit(1)
    print("All PDFs present and fresh, and corpora.json matches the briefs.")


if __name__ == "__main__":
    main()
