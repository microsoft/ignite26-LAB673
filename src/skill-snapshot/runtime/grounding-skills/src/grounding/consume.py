"""grounding-consume: read-only check, inspect and sample of a grounding index."""

from __future__ import annotations

from collections import Counter
from typing import Any

from . import API_VERSION, state
from .azure import Azure
from .build import doc_count, get_index
from .errors import GroundingError
from .names import validate_index_name
from .schema import validate_definition

SAMPLE_FIELDS = ["subject", "predicate", "object", "subject_id", "object_id", "edge_confidence", "namespace",
                 "graph_name"]


def _require_index(az: Azure, endpoint: str, index: str) -> dict[str, Any]:
    validate_index_name(index, prefix="")
    defn = get_index(az, endpoint, index)
    if defn is None:
        raise GroundingError("GROUNDING_INDEX_NOT_FOUND", f"index {index!r} not found on {endpoint}")
    return defn


def check(az: Azure, endpoint: str, index: str) -> dict[str, Any]:
    defn = _require_index(az, endpoint, index)
    problems = validate_definition(defn)
    count = doc_count(az, endpoint, index)
    res = az.search("POST", endpoint, f"/indexes/{index}/docs/search", {"search": "*", "top": 1, "select": "id,subject,predicate,object"})
    sample_ok = bool(res.get("value"))
    desc = state.load_descriptor(index)
    expected = desc["edge_count"] if desc else None
    if count == 0:
        problems.append("INDEX_EMPTY: index has no documents")
    if expected is not None and count != expected:
        problems.append(f"COUNT_MISMATCH: {count} documents, descriptor expects {expected}")
    return {"ok": not problems and sample_ok, "index": index, "endpoint": endpoint, "api_version": API_VERSION,
            "profile_kind": (defn.get("graphProfile") or {}).get("kind"), "document_count": count,
            "sample_query_ok": sample_ok, "descriptor_found": desc is not None, "problems": problems}


def inspect(az: Azure, endpoint: str, index: str) -> dict[str, Any]:
    defn = _require_index(az, endpoint, index)
    stats = az.search("GET", endpoint, f"/indexes/{index}/stats")
    res = az.search("POST", endpoint, f"/indexes/{index}/docs/search",
                    {"search": "*", "top": 200, "select": "predicate,namespace,graph_name,edge_confidence"})
    docs = res.get("value", [])
    return {"ok": True, "index": index, "endpoint": endpoint, "api_version": API_VERSION,
            "graph_profile": defn.get("graphProfile"), "fields": [f["name"] for f in defn.get("fields", [])],
            "document_count": stats.get("documentCount"), "storage_size_bytes": stats.get("storageSize"),
            "sampled_documents": len(docs),
            "sampled_namespaces": dict(Counter(d.get("namespace") for d in docs if d.get("namespace"))),
            "sampled_graph_names": dict(Counter(d.get("graph_name") for d in docs if d.get("graph_name"))),
            "sampled_top_predicates": dict(Counter(d.get("predicate") for d in docs).most_common(10)),
            "descriptor": state.load_descriptor(index)}


def sample(az: Azure, endpoint: str, index: str, n: int = 10, query: str = "*", predicate: str = "") -> dict[str, Any]:
    if not 1 <= n <= 100:
        raise GroundingError("SAMPLE_SIZE_INVALID", "n must be 1..100")
    _require_index(az, endpoint, index)
    body: dict[str, Any] = {"search": query or "*", "top": n, "select": ",".join(SAMPLE_FIELDS)}
    if predicate:
        if "'" in predicate:
            raise GroundingError("PREDICATE_INVALID", "predicate must not contain a single quote")
        body["filter"] = f"predicate eq '{predicate}'"
    res = az.search("POST", endpoint, f"/indexes/{index}/docs/search", body)
    edges = [{k: v for k, v in d.items() if not k.startswith("@")} for d in res.get("value", [])]
    return {"ok": True, "index": index, "count": len(edges), "edges": edges}


LABEL_FILTER = "(predicate eq 'rdfs:label' or predicate eq 'skos:altLabel') and subject_id ne null"


def _count(az: Azure, endpoint: str, index: str, flt: str = "") -> int:
    body: dict[str, Any] = {"search": "*", "top": 0, "count": True}
    if flt:
        body["filter"] = flt
    return int(az.search("POST", endpoint, f"/indexes/{index}/docs/search", body).get("@odata.count", 0))


def decide_ready(*, profile_problems: list[str], total: int, label_rows: int, graph_name: str, labels_in_graph: int,
                 rows_in_graph: int, distinct: dict[str, int], index: str) -> dict[str, Any]:
    """Pure decision logic: PASS/FAIL per check and the single next step."""
    checks = [{"check": "edgelist_profile", "status": "PASS" if not profile_problems else "FAIL",
               "detail": "; ".join(profile_problems[:3]) or "edgeList profile present"},
              {"check": "label_rows", "status": "PASS" if label_rows else "FAIL",
               "detail": f"{label_rows} rdfs:label/skos:altLabel rows with subject_id"}]
    if graph_name:
        share = round(rows_in_graph / total, 4) if total else 0.0
        checks.append({"check": "graph_name_match", "status": "PASS" if labels_in_graph else "FAIL",
                       "detail": f"{labels_in_graph} label rows and {rows_in_graph}/{total} rows ({share:.0%}) carry "
                                 f"graph_name {graph_name!r}"
                                 + ("" if rows_in_graph == total else "; other rows keep other graph names "
                                    "(run align to include them)")})
    else:
        checks.append({"check": "graph_name_match", "status": "SKIP", "detail": "no --graph-name given"})
    failed = {c["check"] for c in checks if c["status"] == "FAIL"}
    gn = graph_name or "<graph-extraction build graph name>"
    if "edgelist_profile" in failed:
        step = "Rebuild: this index is not a valid edgeList grounding index. Run `grounding-build plan` with a new --index."
    elif "label_rows" in failed:
        step = (f"Rebuild into a new index with label rows: `grounding-build plan --file <edges with subject_id/object_id "
                f"columns> --with-labels --graph-name {gn} --index <new grounding- name>`.")
    elif "graph_name_match" in failed:
        step = f"Run `grounding-build align --index {index} --graph-name {graph_name}` and approve the plan."
    elif not graph_name:
        step = f"Re-run `grounding-consume ready --index {index} --graph-name <graph-extraction build graph name>`."
    else:
        step = "Ready: reference this index from the graph-extraction build."
    return {"ok": not failed, "result": "FAIL" if failed else "PASS", "checks": checks, "next_step": step}


def ready(az: Azure, endpoint: str, index: str, graph_name: str = "") -> dict[str, Any]:
    defn = _require_index(az, endpoint, index)
    problems = validate_definition(defn)
    total = doc_count(az, endpoint, index)
    res = az.search("POST", endpoint, f"/indexes/{index}/docs/search",
                    {"search": "*", "top": 0, "count": True, "facets": ["graph_name,count:20"]})
    distinct = {f["value"]: int(f["count"]) for f in (res.get("@search.facets") or {}).get("graph_name", [])
                if f.get("value") is not None}
    label_rows = _count(az, endpoint, index, LABEL_FILTER)
    in_graph = labels_in_graph = 0
    if graph_name:
        q = "'" + graph_name.replace("'", "''") + "'"
        in_graph = _count(az, endpoint, index, f"graph_name eq {q}")
        labels_in_graph = _count(az, endpoint, index, f"graph_name eq {q} and {LABEL_FILTER}")
    out = decide_ready(profile_problems=problems, total=total, label_rows=label_rows, graph_name=graph_name,
                       labels_in_graph=labels_in_graph, rows_in_graph=in_graph, distinct=distinct, index=index)
    out.update({"index": index, "endpoint": endpoint, "document_count": total, "label_rows": label_rows,
                "distinct_graph_names": distinct})
    return out
