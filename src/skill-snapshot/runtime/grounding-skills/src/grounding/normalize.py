"""Edge normalization, dedupe, hashing and document conversion. Pure functions."""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from datetime import datetime, timezone
from typing import Any, Iterable

DEFAULT_EDGE_CAP = 200_000
WIKIDATA_EDGE_CAP = 50_000
SENTINEL_REF = "grounding"  # chunk_id (and graph_name fallback) for edges with no source chunk; see edgelist-schema.md
DEFAULT_CONFIDENCE = 1.0  # confidence roles are required; unscored edges get this

TEXT_KEYS = ("subject", "predicate", "object", "subject_type", "subject_id", "object_type", "object_id",
             "object_string", "namespace", "graph_name", "subject_display", "object_display")


def clean_text(value: Any) -> str:
    """Trim and NFC-normalize; None becomes the empty string."""
    if value is None:
        return ""
    return unicodedata.normalize("NFC", str(value)).strip()


def parse_confidence(value: Any) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f) or not 0.0 <= f <= 1.0:
        return None
    return f


def parse_datetime(value: Any) -> str | None:
    """Return an RFC 3339 UTC string, or None when the value is not a valid ISO 8601 timestamp."""
    s = clean_text(value)
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    s = clean_text(value).lower()
    if s in ("true", "1", "yes"):
        return True
    if s in ("false", "0", "no"):
        return False
    return None


def parse_double(value: Any) -> float | None:
    if value is None or isinstance(value, bool) or (isinstance(value, str) and not value.strip()):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def edge_key(e: dict[str, Any]) -> tuple:
    """Identity of an edge: subject, predicate and object, refined by ids and literal value when present."""
    return (e["subject"], e.get("subject_id", ""), e["predicate"], e["object"], e.get("object_id", ""),
            e.get("object_type", ""), e.get("object_double"), e.get("object_bool"), e.get("object_datetime", ""))


def edge_hash(e: dict[str, Any]) -> str:
    payload = json.dumps(edge_key(e), ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def doc_id(e: dict[str, Any]) -> str:
    return "edge-" + edge_hash(e)[:40]


LABEL_PREDICATE = "rdfs:label"


def label_triples(raw: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Derive `<id> rdfs:label <name>` rows from edges that carry subject_id/object_id.

    Name resolution matches the mention against `object` and returns the row's subject_id,
    so a label row has the canonical id as subject and the entity name as object.
    """
    out: list[dict[str, Any]] = []
    for row in raw:
        for side in ("subject", "object"):
            ident, name = clean_text(row.get(f"{side}_id")), clean_text(row.get(side))
            if not ident or not name or ident == name:
                continue
            out.append({"subject": ident, "predicate": LABEL_PREDICATE, "object": name, "subject_id": ident,
                        "subject_type": clean_text(row.get(f"{side}_type")), "confidence": row.get("confidence"),
                        "namespace": row.get("namespace", ""), "graph_name": row.get("graph_name", "")})
    return out


def normalize_edges(raw: Iterable[dict[str, Any]], *, cap: int = DEFAULT_EDGE_CAP,
                    default_namespace: str = "", default_graph_name: str = "") -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Normalize, drop invalid/self-loop edges, dedupe keeping max confidence, cap, and report drops."""
    report = {"input": 0, "dropped_empty": 0, "dropped_self_loop": 0, "dropped_duplicate": 0,
              "dropped_cap": 0, "invalid_confidence": 0, "invalid_literal": 0, "kept": 0}
    best: dict[tuple, dict[str, Any]] = {}
    for row in raw:
        report["input"] += 1
        e = {k: clean_text(row.get(k)) for k in TEXT_KEYS}
        lit_s = e["object_string"]
        d = parse_double(row.get("object_double"))
        b = parse_bool(row.get("object_bool")) if row.get("object_bool") not in (None, "") else None
        dt = parse_datetime(row.get("object_datetime"))
        for raw_key, parsed in (("object_double", d), ("object_bool", b), ("object_datetime", dt)):
            if row.get(raw_key) not in (None, "") and parsed is None:
                report["invalid_literal"] += 1
        if not e["object"]:
            e["object"] = lit_s or (str(d) if d is not None else "") or (str(b).lower() if b is not None else "") or (dt or "")
        if not e["subject"] or not e["predicate"] or not e["object"]:
            report["dropped_empty"] += 1
            continue
        if e["subject"].casefold() == e["object"].casefold() or (
                e["subject_id"] and e["subject_id"] == e["object_id"]):
            report["dropped_self_loop"] += 1
            continue
        if d is not None:
            e["object_double"] = d
        if b is not None:
            e["object_bool"] = b
        if dt is not None:
            e["object_datetime"] = dt
        raw_conf = row.get("confidence")
        conf = parse_confidence(raw_conf)
        if conf is None and raw_conf not in (None, ""):
            report["invalid_confidence"] += 1
        e["confidence"] = conf
        e["namespace"] = e["namespace"] or default_namespace
        e["graph_name"] = e["graph_name"] or default_graph_name
        key = edge_key(e)
        prev = best.get(key)
        if prev is None:
            best[key] = e
            continue
        report["dropped_duplicate"] += 1
        if (e["confidence"] if e["confidence"] is not None else -1.0) > (
                prev["confidence"] if prev["confidence"] is not None else -1.0):
            best[key] = e
    edges = sorted(best.values(), key=lambda x: (-(x["confidence"] if x["confidence"] is not None else -1.0),
                                                  json.dumps(edge_key(x), default=str)))
    if len(edges) > cap:
        report["dropped_cap"] = len(edges) - cap
        edges = edges[:cap]
    edges.sort(key=lambda x: json.dumps(edge_key(x), default=str))
    report["kept"] = len(edges)
    return edges, report


def to_document(e: dict[str, Any], *, include_empty_refs: bool = True) -> dict[str, Any]:
    """Convert a normalized edge to an index document with a deterministic id."""
    doc: dict[str, Any] = {
        "id": doc_id(e), "edge_hash": edge_hash(e), "subject": e["subject"], "predicate": e["predicate"],
        "object": e["object"],
    }
    for src, dst in (("subject_type", "subject_type"), ("subject_id", "subject_id"), ("object_type", "object_type"),
                     ("object_id", "object_id"), ("object_string", "object_string"), ("namespace", "namespace"),
                     ("graph_name", "graph_name"), ("subject_display", "subject_id_display_name"),
                     ("object_display", "object_id_display_name")):
        if e.get(src):
            doc[dst] = e[src]
    for k in ("object_double", "object_bool", "object_datetime"):
        if e.get(k) is not None:
            doc[k] = e[k]
    conf = e["confidence"] if e.get("confidence") is not None else DEFAULT_CONFIDENCE
    for k in ("edge_confidence", "s_confidence", "p_confidence", "o_confidence"):
        doc[k] = conf
    doc["graph_name"] = e.get("graph_name") or SENTINEL_REF
    if include_empty_refs:
        doc["chunk_id"] = SENTINEL_REF
        doc["parent_id"] = doc["graph_name"]
    return doc


def content_hash(edges: list[dict[str, Any]]) -> str:
    h = hashlib.sha256()
    for e in edges:
        h.update(json.dumps(to_document(e), sort_keys=True, ensure_ascii=False, default=str).encode())
    return h.hexdigest()
