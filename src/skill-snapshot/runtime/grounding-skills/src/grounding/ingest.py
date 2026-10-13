"""Parse bring-your-own edge files (CSV, JSONL, Parquet) into raw edge rows."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any, Iterator

from .errors import GroundingError

ALIASES = {
    "subject": ("subject", "s", "head", "source_entity", "from"),
    "predicate": ("predicate", "p", "relation", "relationship", "edge", "property"),
    "object": ("object", "o", "tail", "target_entity", "to"),
    "subject_type": ("subject_type", "s_type", "head_type"),
    "object_type": ("object_type", "o_type", "tail_type"),
    "subject_id": ("subject_id", "s_id", "head_id"),
    "object_id": ("object_id", "o_id", "tail_id"),
    "subject_display": ("subject_display", "subject_id_display_name", "subject_label"),
    "object_display": ("object_display", "object_id_display_name", "object_label"),
    "confidence": ("confidence", "edge_confidence", "score", "weight"),
    "namespace": ("source", "namespace", "origin"),
    "graph_name": ("graph_name", "graph"),
    "object_string": ("object_string",),
    "object_double": ("object_double",),
    "object_bool": ("object_bool",),
    "object_datetime": ("object_datetime",),
}
REQUIRED = ("subject", "predicate", "object")
SUPPORTED = {".csv": "csv", ".jsonl": "jsonl", ".ndjson": "jsonl", ".parquet": "parquet"}


def detect_format(path: Path, explicit: str | None = None) -> str:
    if explicit:
        if explicit not in ("csv", "jsonl", "parquet"):
            raise GroundingError("FORMAT_UNSUPPORTED", f"format {explicit!r} is not csv, jsonl or parquet")
        return explicit
    fmt = SUPPORTED.get(path.suffix.lower())
    if not fmt:
        raise GroundingError("FORMAT_UNSUPPORTED", f"cannot infer format from {path.suffix!r}",
                             "Pass --format csv|jsonl|parquet.")
    return fmt


def map_columns(columns: list[str]) -> dict[str, str]:
    """Map canonical field -> source column using case-insensitive aliases; raises when required ones are absent."""
    lowered = {c.strip().lower(): c for c in columns if isinstance(c, str)}
    mapping: dict[str, str] = {}
    for canon, names in ALIASES.items():
        for n in names:
            if n in lowered:
                mapping[canon] = lowered[n]
                break
    missing = [k for k in REQUIRED if k not in mapping]
    if missing:
        raise GroundingError("COLUMNS_MISSING", f"required columns not found: {', '.join(missing)}",
                             "Provide subject, predicate and object columns (see references/input-formats.md).",
                             detail={"columns": columns})
    return mapping


def _rows(path: Path, fmt: str) -> Iterator[dict[str, Any]]:
    if fmt == "csv":
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            yield from csv.DictReader(f)
    elif fmt == "jsonl":
        with path.open("r", encoding="utf-8-sig") as f:
            for n, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise GroundingError("JSONL_INVALID", f"line {n}: {exc.msg}") from exc
                if not isinstance(obj, dict):
                    raise GroundingError("JSONL_INVALID", f"line {n}: expected a JSON object")
                yield obj
    else:
        try:
            import pyarrow.parquet as pq
        except ImportError as exc:
            raise GroundingError("PARQUET_UNAVAILABLE", "Parquet support needs pyarrow",
                                 "pip install grounding-skills[parquet]") from exc
        pf = pq.ParquetFile(str(path))
        for batch in pf.iter_batches(batch_size=10_000):
            yield from batch.to_pylist()


ENTITY_ALIASES = {
    "id": ("id", "entity_id", "canonical_id", "subject_id"),
    "name": ("name", "entity", "label", "canonical_name", "subject", "entity_name"),
    "type": ("type", "entity_type", "class", "subject_type"),
    "aliases": ("aliases", "alias", "alt_labels", "synonyms"),
}
ALIAS_SPLIT = re.compile(r"\s*[|;]\s*")


def _match(lowered: dict[str, str], table: dict[str, tuple[str, ...]]) -> dict[str, str]:
    return {k: lowered[n] for k, names in table.items() for n in names if n in lowered}


def entity_columns(columns: list[str]) -> dict[str, str] | None:
    """Mapping for an entity list (id + name, no predicate/object), else None."""
    lowered = {c.strip().lower(): c for c in columns if isinstance(c, str)}
    if "predicate" in _match(lowered, ALIASES) or "object" in _match(lowered, ALIASES):
        return None
    m = _match(lowered, ENTITY_ALIASES)
    return m if "id" in m and "name" in m else None


def entity_rows(row: dict[str, Any], m: dict[str, str]) -> Iterator[dict[str, Any]]:
    """One `<id> rdfs:label <name>` row per name and alias of an entity."""
    ident = (row.get(m["id"]) or "").strip() if isinstance(row.get(m["id"]), str) else row.get(m["id"])
    names = [row.get(m["name"])]
    if "aliases" in m and row.get(m["aliases"]):
        names += ALIAS_SPLIT.split(str(row[m["aliases"]]))
    for n in names:
        if n and str(n).strip():
            yield {"subject": ident, "subject_id": ident, "predicate": "rdfs:label", "object": str(n).strip(),
                   "subject_type": row.get(m["type"]) if "type" in m else None}


def read_edges(path: str | Path, fmt: str | None = None) -> Iterator[dict[str, Any]]:
    """Yield raw edge rows keyed by canonical field names.

    An entity list (id and name columns, optional type and aliases) yields one label row per name and alias.
    """
    p = Path(path)
    if not p.is_file():
        raise GroundingError("FILE_NOT_FOUND", f"edge file not found: {p.name}")
    fmt = detect_format(p, fmt)
    cache: dict[tuple, dict[str, str]] = {}
    entity_cache: dict[tuple, dict[str, str] | None] = {}
    for row in _rows(p, fmt):
        sig = tuple(row.keys())
        if sig not in entity_cache:
            entity_cache[sig] = entity_columns(list(sig))
        if entity_cache[sig]:
            yield from entity_rows(row, entity_cache[sig])
            continue
        if sig not in cache:
            cache[sig] = map_columns(list(sig))
        mapping = cache[sig]
        yield {canon: row.get(col) for canon, col in mapping.items()}
