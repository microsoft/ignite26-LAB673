"""grounding-build align: re-stamp graph_name on every row of an existing grounding index.

Dry run by default. Apply needs the exact plan ID. Only `graph_name` and the `parent_id` sentinel (which mirrors it)
are merged; no row is created or deleted. Re-running is a no-op once every row is aligned, and an interrupted run is
continued by re-running with the same plan ID (rows already aligned are skipped).
"""

from __future__ import annotations

from typing import Any

from . import API_VERSION, state
from .azure import Azure, validate_endpoint
from .build import MAX_BATCH, _now, get_index
from .errors import ApprovalError, GroundingError, ServiceError
from .names import validate_index_name
from .plan import PLAN_PREFIX, _digest, approval_card, require_plan_id
from .schema import validate_definition

FACET_LIMIT = 50


def validate_graph_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise GroundingError("GRAPH_NAME_REQUIRED", "--graph-name is required",
                             "Use the graph name of the graph-extraction build that will use this index.")
    if len(name) > 200 or any(ord(c) < 32 for c in name):
        raise GroundingError("GRAPH_NAME_INVALID", "graph name must be 1..200 printable characters")
    return name


def odata_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def align_plan_id(endpoint: str, index: str, graph_name: str, to_change: int, current: dict[str, int]) -> str:
    return PLAN_PREFIX + _digest({"kind": "align", "endpoint": endpoint.lower(), "index": index, "graph": graph_name,
                                  "to_change": to_change, "current": sorted(current.items())})[:16]


def not_aligned_filter(graph_name: str, after_id: str = "") -> str:
    f = f"(graph_name ne {odata_quote(graph_name)} or graph_name eq null)"
    return f + (f" and id gt {odata_quote(after_id)}" if after_id else "")


def merge_document(doc_id: str, graph_name: str) -> dict[str, Any]:
    return {"@search.action": "merge", "id": doc_id, "graph_name": graph_name, "parent_id": graph_name}


def facet_counts(res: dict[str, Any]) -> dict[str, int]:
    facets = (res.get("@search.facets") or {}).get("graph_name") or []
    return {f.get("value"): int(f.get("count", 0)) for f in facets if f.get("value") is not None}


def _count(az: Azure, endpoint: str, index: str, flt: str = "") -> int:
    body: dict[str, Any] = {"search": "*", "top": 0, "count": True}
    if flt:
        body["filter"] = flt
    return int(az.search("POST", endpoint, f"/indexes/{index}/docs/search", body).get("@odata.count", 0))


def inspect_graph_names(az: Azure, endpoint: str, index: str, graph_name: str) -> dict[str, Any]:
    res = az.search("POST", endpoint, f"/indexes/{index}/docs/search",
                    {"search": "*", "top": 0, "count": True, "facets": [f"graph_name,count:{FACET_LIMIT}"]})
    total = int(res.get("@odata.count", 0))
    current = facet_counts(res)
    aligned = _count(az, endpoint, index, f"graph_name eq {odata_quote(graph_name)}")
    return {"total": total, "aligned": aligned, "to_change": total - aligned, "current": current,
            "facets_truncated": len(current) >= FACET_LIMIT}


def _require_edgelist(az: Azure, endpoint: str, index: str) -> None:
    validate_index_name(index, prefix="")
    defn = get_index(az, endpoint, index)
    if defn is None:
        raise GroundingError("GROUNDING_INDEX_NOT_FOUND", f"index {index!r} not found on {endpoint}")
    problems = validate_definition(defn)
    if problems:
        raise GroundingError("GROUNDING_PROFILE_INVALID", "index is not a valid edgeList grounding index",
                             "Rebuild it with `grounding-build plan`.", detail=problems[:10])


def make_align_plan(az: Azure, ident: dict[str, Any], *, endpoint: str, index: str, graph_name: str,
                    persist: bool = True) -> dict[str, Any]:
    endpoint = validate_endpoint(endpoint)
    graph_name = validate_graph_name(graph_name)
    _require_edgelist(az, endpoint, index)
    info = inspect_graph_names(az, endpoint, index, graph_name)
    plan_id = align_plan_id(endpoint, index, graph_name, info["to_change"], info["current"])
    changes = ([f"Set graph_name to {graph_name!r} on {info['to_change']} of {info['total']} rows of index {index} "
                f"(merge; no rows created or deleted)"] if info["to_change"] else [])
    notices = ["Rows already aligned are left untouched.",
               "Current graph_name values: " + (", ".join(f"{k!r} ({v})" for k, v in info["current"].items()) or "none")]
    if info["facets_truncated"]:
        notices.append(f"More than {FACET_LIMIT} distinct graph names; only the largest are listed.")
    plan: dict[str, Any] = {"ok": True, "kind": "align", "plan_id": plan_id, "tenant": ident["tenant"],
                            "subscription": ident["subscription"], "endpoint": endpoint, "index": index,
                            "graph_name": graph_name, "api_version": API_VERSION, "rows_total": info["total"],
                            "rows_to_change": info["to_change"], "rows_already_aligned": info["aligned"],
                            "current_graph_names": info["current"], "no_op": info["to_change"] == 0,
                            "changes": changes, "notices": notices, "created_at": _now()}
    if info["to_change"] == 0:
        plan["next_step"] = f"Already aligned. Check with: grounding-consume ready --index {index} --graph-name {graph_name}"
    else:
        plan["approval"] = approval_card(plan_id, f"align grounding index {index} to graph {graph_name}", changes,
                                         "no model calls; no new storage beyond the merged fields", notices)
        plan["next_step"] = f"grounding-build align --index {index} --graph-name {graph_name} --plan-id {plan_id}"
    if persist:
        state.save_plan(plan)
        plan["saved"] = True
    return plan


def apply_align(az: Azure, ident: dict[str, Any], plan_id: str | None, *, batch_size: int = MAX_BATCH,
                stop_after_batches: int | None = None) -> dict[str, Any]:
    if not 1 <= batch_size <= MAX_BATCH:
        raise GroundingError("BATCH_SIZE_INVALID", f"batch size must be 1..{MAX_BATCH}")
    if not plan_id:
        raise ApprovalError("PLAN_ID_REQUIRED", "--plan-id is required", "Run `grounding-build align` without "
                            "--plan-id, get approval, then re-run with the displayed plan ID.")
    plan = state.load_plan(plan_id)
    if plan is None or plan.get("kind") != "align":
        raise ApprovalError("PLAN_NOT_FOUND", f"no saved align plan {plan_id}", "Run `grounding-build align` first.")
    require_plan_id(plan_id, plan["plan_id"])
    if (ident["tenant"].lower(), ident["subscription"].lower()) != (plan["tenant"].lower(), plan["subscription"].lower()):
        raise GroundingError("IDENTITY_CHANGED", "tenant/subscription differ from those the plan was approved for")
    ep, index, graph = plan["endpoint"], plan["index"], plan["graph_name"]
    _require_edgelist(az, ep, index)
    journal = state.load_journal(plan_id) or {"plan_id": plan_id, "index": index, "phase": "started", "merged_docs": 0,
                                               "started_at": _now()}
    batches = 0
    last_id = ""
    while True:
        if stop_after_batches is not None and batches >= stop_after_batches:
            journal.update(phase="aligning", updated_at=_now())
            state.save_journal(plan_id, journal)
            return {"ok": True, "interrupted": True, "plan_id": plan_id, "merged_docs": journal["merged_docs"],
                    "next_step": f"grounding-build align --index {index} --graph-name {graph} --plan-id {plan_id}"}
        res = az.search("POST", ep, f"/indexes/{index}/docs/search",
                        {"search": "*", "filter": not_aligned_filter(graph, last_id), "orderby": "id", "select": "id",
                         "top": batch_size})
        rows = res.get("value", [])
        if not rows:
            break
        ids = [r["id"] for r in rows]
        out = az.search("POST", ep, f"/indexes/{index}/docs/index", {"value": [merge_document(i, graph) for i in ids]})
        failed = [r for r in out.get("value", []) if not r.get("status")]
        if failed:
            raise ServiceError("ALIGN_PARTIAL", f"{len(failed)} rows were rejected", "Re-run with the same plan ID; "
                               "merges are idempotent.", detail=failed[:5])
        last_id = ids[-1]
        batches += 1
        journal.update(phase="aligning", merged_docs=journal["merged_docs"] + len(ids), updated_at=_now())
        state.save_journal(plan_id, journal)
    info = inspect_graph_names(az, ep, index, graph)
    ok = info["to_change"] == 0
    journal.update(phase="complete" if ok else "verify_failed", updated_at=_now())
    state.save_journal(plan_id, journal)
    if not ok:
        raise ServiceError("ALIGN_VERIFY_FAILED", f"{info['to_change']} rows still carry another graph name",
                           "The index may still be settling; re-run with the same plan ID.", detail=info)
    return {"ok": True, "plan_id": plan_id, "index": index, "graph_name": graph, "merged_docs": journal["merged_docs"],
            "rows_total": info["total"], "rows_aligned": info["aligned"], "current_graph_names": info["current"],
            "next_step": f"grounding-consume ready --index {index} --graph-name {graph}"}
