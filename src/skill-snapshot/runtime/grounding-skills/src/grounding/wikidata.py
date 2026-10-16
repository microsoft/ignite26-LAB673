"""Bounded Wikidata bootstrap: resolve seeds, walk statements, emit raw edge rows.

Only the public Wikidata Action API is used (no HTML scraping, no dumps). Wikidata content is CC0.
"""

from __future__ import annotations

import re
import time
from typing import Any, Callable, Iterable

from .errors import GroundingError, ServiceError
from .normalize import WIKIDATA_EDGE_CAP

API_URL = "https://www.wikidata.org/w/api.php"
USER_AGENT = "grounding-skills/0.1 (https://github.com/microsoft/azure-skills; bounded seed queries, low rate) httpx"
NAMESPACE = "wikidata:CC0"
EDGE_CONFIDENCE = 0.9
MAX_DEPTH = 2
BATCH = 50
QID_RE = re.compile(r"^Q[1-9][0-9]*$")
KEPT_DATATYPES = {"wikibase-item", "string", "quantity", "time", "monolingualtext"}
LICENSE_NOTICE = "Wikidata content is CC0 (public domain dedication); no attribution or ShareAlike obligation."
DOMAIN_FIT_NOTICE = ("Generic Wikidata edges add noise for private or niche corpora. Use this bootstrap for demos "
                     "or corpora about broadly public topics only.")


def classify_seed(seed: str) -> str:
    return "qid" if QID_RE.match(seed.strip().upper()) else "title"


def validate_bounds(depth: int, edge_cap: int, seeds: list[str]) -> None:
    if not seeds:
        raise GroundingError("WIKIDATA_SEED_REQUIRED", "at least one seed (QID or title) is required",
                             "Full Wikidata dumps are refused; pass --seed.")
    if not 1 <= depth <= MAX_DEPTH:
        raise GroundingError("WIKIDATA_DEPTH_INVALID", f"depth must be 1..{MAX_DEPTH}")
    if not 1 <= edge_cap <= WIKIDATA_EDGE_CAP:
        raise GroundingError("WIKIDATA_CAP_INVALID", f"edge cap must be 1..{WIKIDATA_EDGE_CAP}")


def _time_to_iso(value: dict[str, Any]) -> str | None:
    """Wikidata time like '+2001-09-11T00:00:00Z'; precision below day is not representable reliably."""
    t = str(value.get("time", ""))
    m = re.match(r"^\+?(\d{4})-(\d{2})-(\d{2})T(\d{2}:\d{2}:\d{2})Z$", t)
    if not m or int(value.get("precision", 0)) < 11:
        return None
    y, mo, d, hms = m.groups()
    if mo == "00" or d == "00":
        return None
    return f"{y}-{mo}-{d}T{hms}Z"


def statements_from_entity(entity: dict[str, Any]) -> list[dict[str, Any]]:
    """Pure: convert one wbgetentities entity into statement dicts (no labels resolved yet).

    Each item: {pid, kind: item|string|double|datetime, target_id | value}.
    """
    out = []
    for pid, claims in (entity.get("claims") or {}).items():
        for c in claims:
            if c.get("rank") == "deprecated":
                continue
            snak = c.get("mainsnak") or {}
            if snak.get("snaktype") != "value" or snak.get("datatype") not in KEPT_DATATYPES:
                continue
            dv = (snak.get("datavalue") or {}).get("value")
            dt = snak["datatype"]
            item: dict[str, Any] = {"pid": pid}
            if dt == "wikibase-item" and isinstance(dv, dict) and dv.get("id"):
                item.update(kind="item", target_id=dv["id"])
            elif dt == "string" and isinstance(dv, str) and dv.strip():
                item.update(kind="string", value=dv)
            elif dt == "monolingualtext" and isinstance(dv, dict) and dv.get("language") == "en":
                item.update(kind="string", value=dv.get("text", ""))
            elif dt == "quantity" and isinstance(dv, dict) and "amount" in dv:
                try:
                    item.update(kind="double", value=float(dv["amount"]))
                except ValueError:
                    continue
            elif dt == "time" and isinstance(dv, dict):
                iso = _time_to_iso(dv)
                if iso is None:
                    continue
                item.update(kind="datetime", value=iso)
            else:
                continue
            out.append(item)
    return out


def edge_from_statement(subject_id: str, subject_label: str, st: dict[str, Any], labels: dict[str, str],
                        graph_name: str) -> dict[str, Any]:
    row: dict[str, Any] = {
        "subject": subject_label or subject_id, "subject_id": subject_id,
        "subject_display": subject_label or subject_id, "predicate": st["pid"],
        "confidence": EDGE_CONFIDENCE, "namespace": NAMESPACE, "graph_name": graph_name,
    }
    if st["kind"] == "item":
        tid = st["target_id"]
        lab = labels.get(tid) or tid
        row.update(object=lab, object_id=tid, object_display=lab)
    elif st["kind"] == "string":
        row.update(object=st["value"], object_string=st["value"])
    elif st["kind"] == "double":
        row.update(object=str(st["value"]), object_double=st["value"])
    else:
        row.update(object=st["value"], object_datetime=st["value"])
    return row


def graph_name_for(seed_ids: Iterable[str]) -> str:
    return ("wikidata-" + "-".join(sorted(s.lower() for s in seed_ids)))[:128]


class WikidataClient:
    def __init__(self, http: Any | None = None, min_interval: float = 0.25, sleep: Callable[[float], None] = time.sleep):
        import httpx
        self._http = http or httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60.0)
        self._min_interval = min_interval
        self._sleep = sleep
        self._last = 0.0
        self.requests = 0

    def _get(self, params: dict[str, Any]) -> dict[str, Any]:
        params = {**params, "format": "json", "maxlag": 5}
        for attempt in range(6):
            wait = self._min_interval - (time.monotonic() - self._last)
            if wait > 0:
                self._sleep(wait)
            self._last = time.monotonic()
            self.requests += 1
            r = self._http.get(API_URL, params=params, headers={"User-Agent": USER_AGENT})
            if r.status_code in (429, 503) or (r.status_code == 200 and r.json().get("error", {}).get("code") == "maxlag"):
                self._sleep(min(30.0, float(r.headers.get("Retry-After", 2 ** attempt))))
                continue
            if r.status_code != 200:
                raise ServiceError("WIKIDATA_HTTP", f"Wikidata API returned HTTP {r.status_code}")
            body = r.json()
            if "error" in body:
                raise ServiceError("WIKIDATA_ERROR", f"Wikidata API error: {body['error'].get('code')}")
            return body
        raise ServiceError("WIKIDATA_THROTTLED", "Wikidata API kept throttling; retry later with a smaller seed")

    def resolve_seed(self, seed: str) -> dict[str, str]:
        s = seed.strip()
        if classify_seed(s) == "qid":
            ents = self.get_entities([s.upper()], props="labels")
            e = ents.get(s.upper(), {})
            if "missing" in e:
                raise GroundingError("WIKIDATA_SEED_NOT_FOUND", f"{s} does not exist in Wikidata")
            return {"id": s.upper(), "label": _label(e) or s.upper(), "input": seed}
        body = self._get({"action": "wbsearchentities", "search": s, "language": "en", "type": "item", "limit": 1})
        hits = body.get("search") or []
        if not hits:
            raise GroundingError("WIKIDATA_SEED_NOT_FOUND", f"no Wikidata item matches title {seed!r}",
                                 "Use a QID, for example Q95 for Google.")
        return {"id": hits[0]["id"], "label": hits[0].get("label") or hits[0]["id"], "input": seed}

    def get_entities(self, ids: list[str], props: str) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for i in range(0, len(ids), BATCH):
            body = self._get({"action": "wbgetentities", "ids": "|".join(ids[i:i + BATCH]), "props": props,
                              "languages": "en"})
            out.update(body.get("entities", {}))
        return out

    def labels(self, ids: list[str]) -> dict[str, str]:
        return {k: _label(v) for k, v in self.get_entities(ids, "labels").items() if _label(v)}


def _label(entity: dict[str, Any]) -> str:
    return ((entity.get("labels") or {}).get("en") or {}).get("value", "")


def collect_edges(client: WikidataClient, seeds: list[str], depth: int, edge_cap: int
                  ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Walk statements from the seeds. Refuses (never truncates) when raw statements exceed the cap."""
    validate_bounds(depth, edge_cap, seeds)
    resolved = [client.resolve_seed(s) for s in seeds]
    graph = graph_name_for(r["id"] for r in resolved)
    seen: set[str] = set()
    frontier = [r["id"] for r in resolved]
    statements: list[tuple[str, dict[str, Any]]] = []
    subject_labels: dict[str, str] = {r["id"]: r["label"] for r in resolved}
    for hop in range(1, depth + 1):
        frontier = [q for q in dict.fromkeys(frontier) if q not in seen]
        seen.update(frontier)
        nxt: list[str] = []
        for qid, ent in client.get_entities(frontier, props="claims|labels").items():
            if "missing" in ent:
                continue
            subject_labels[qid] = _label(ent) or subject_labels.get(qid, qid)
            for st in statements_from_entity(ent):
                statements.append((qid, st))
                if st["kind"] == "item":
                    nxt.append(st["target_id"])
            if len(statements) > edge_cap:
                raise GroundingError(
                    "WIKIDATA_CAP_EXCEEDED",
                    f"seed expands to more than {edge_cap} statements at depth {hop}; refusing",
                    "Use fewer or narrower seeds, or a smaller depth.",
                    detail={"statements_seen": len(statements), "edge_cap": edge_cap, "depth": hop})
        frontier = nxt
    targets = sorted({st["target_id"] for _, st in statements if st["kind"] == "item"} - set(subject_labels))
    labels = {**subject_labels, **client.labels(targets)}
    rows = [edge_from_statement(q, labels.get(q, q), st, labels, graph) for q, st in statements]
    pid_counts: dict[str, int] = {}
    for _, st in statements:
        pid_counts[st["pid"]] = pid_counts.get(st["pid"], 0) + 1
    top = sorted(pid_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:15]
    plabels = client.labels([p for p, _ in top]) if top else {}
    info = {
        "seeds": resolved, "depth": depth, "edge_cap": edge_cap, "graph_name": graph,
        "statements": len(statements), "entities_expanded": len(seen), "api_requests": client.requests,
        "top_properties": [{"pid": p, "label": plabels.get(p, ""), "count": c} for p, c in top],
        "license": "CC0", "license_notice": LICENSE_NOTICE, "domain_fit_notice": DOMAIN_FIT_NOTICE,
    }
    return rows, info
