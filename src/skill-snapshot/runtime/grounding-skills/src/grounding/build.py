"""grounding-build: plan (dry-run), apply, status and resume for a grounding index."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

from . import API_VERSION, SCHEMA_VERSION
from . import state
from .azure import Azure, validate_endpoint
from .errors import ApprovalError, GroundingError, ServiceError
from .ingest import read_edges
from .names import validate_index_name
from .normalize import (DEFAULT_EDGE_CAP, WIKIDATA_EDGE_CAP, content_hash, edge_key, label_triples, normalize_edges, to_document)
from .plan import approval_card, build_plan_id, estimate_storage_bytes, require_plan_id
from .schema import build_index_definition, definitions_equivalent, validate_definition, validate_document
from .wikidata import (DOMAIN_FIT_NOTICE, LICENSE_NOTICE, NAMESPACE as WIKIDATA_NS, WikidataClient, collect_edges)

MAX_BATCH = 1000
VERIFY_TIMEOUT = 120.0


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _counter(stats: dict[str, Any], key: str) -> tuple[int | None, int | None]:
    c = (stats.get("counters") or {}).get(key) or {}
    return c.get("usage"), c.get("quota")


def get_index(az: Azure, endpoint: str, name: str) -> dict[str, Any] | None:
    r = az.search("GET", endpoint, f"/indexes/{name}", allow=(404,))
    return None if r.get("_status") == 404 else r


def doc_count(az: Azure, endpoint: str, name: str) -> int:
    r = az.search("GET", endpoint, f"/indexes/{name}/docs/$count")
    raw = r.get("text", "") if isinstance(r, dict) else r
    return int(str(raw).lstrip("\ufeff").strip())


def headroom(az: Azure, endpoint: str, est_bytes: int) -> dict[str, Any]:
    stats = az.search("GET", endpoint, "/servicestats")
    iu, iq = _counter(stats, "indexesCount")
    su, sq = _counter(stats, "storageSize")
    info = {"indexes_used": iu, "indexes_quota": iq, "storage_used_bytes": su, "storage_quota_bytes": sq}
    if iu is not None and iq is not None and iu >= iq:
        raise GroundingError("INDEX_QUOTA_REACHED", f"service has {iu}/{iq} indexes", "Free an index or use a larger tier.",
                             detail=info)
    if su is not None and sq is not None and su + est_bytes > sq:
        raise GroundingError("STORAGE_QUOTA_EXCEEDED",
                             f"estimated {est_bytes} bytes does not fit in remaining {sq - su} bytes",
                             "Use a smaller edge file or a larger tier.", detail=info)
    return info


def load_edges(*, file: str = "", fmt: str | None = None, wikidata_seeds: list[str] | None = None, depth: int = 1,
               edge_cap: int | None = None, source_label: str = "byo", graph_name: str = "",
               license_text: str = "", wikidata_client: WikidataClient | None = None, with_labels: bool | None = None
               ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Ingest + normalize. Exactly one of file / wikidata_seeds.

    `graph_name`, when given, overrides the graph name of every edge so it can match the target build.
    `with_labels`: True forces rdfs:label rows (derived from subject_id/object_id), False disables them, None (default)
    adds them automatically when any edge carries subject_id/object_id.
    """
    if bool(file) == bool(wikidata_seeds):
        raise GroundingError("SOURCE_REQUIRED", "give exactly one of --file or --wikidata with --seed")

    def prepare(rows):
        rows = list(rows)
        if graph_name:
            for r in rows:
                r["graph_name"] = graph_name
        return rows

    def add_labels(edges, report, notices):
        """Label rows are added after the cap so they cannot crowd out real edges."""
        report["label_rows_added"] = 0
        has_ids = any(e.get("subject_id") or e.get("object_id") for e in edges)
        report["labels"] = "off" if with_labels is False else "forced" if with_labels else "auto" if has_ids else "skipped"
        if with_labels is False:
            return edges
        if with_labels is None and not has_ids:
            notices.append("No edge has subject_id/object_id, so no label rows were added and a graph-extraction build "
                           "cannot resolve names against this index. Add *_id columns to resolve names.")
            return edges
        labels, _ = normalize_edges(label_triples(edges), cap=max(len(edges), 1) * 2, default_graph_name=graph_name)
        seen = {edge_key(e) for e in edges}
        new = [e for e in labels if edge_key(e) not in seen]
        report["label_rows_added"] = len(new)
        report["kept"] += len(new)
        has_label_rows = any(e.get("predicate") in ("rdfs:label", "skos:altLabel") and e.get("subject_id")
                             for e in edges)
        if not new and not has_label_rows:
            notices.append("--with-labels added no label rows: no edge has subject_id/object_id columns, so name "
                           "resolution will find nothing.")
        return sorted(edges + new, key=lambda x: json.dumps(edge_key(x), default=str))

    if file:
        cap = edge_cap or DEFAULT_EDGE_CAP
        edges, report = normalize_edges(prepare(read_edges(file, fmt)), cap=cap,
                                        default_namespace=f"byo:{source_label}", default_graph_name=graph_name)
        info = {"mode": "file", "edge_cap": cap, "license": license_text or "unspecified (owner-supplied)",
                "notices": ["BYO edges are indexed as supplied; confirm you may use them."]}
        edges = add_labels(edges, report, info["notices"])
        return edges, {"report": report, "source": info}
    cap = edge_cap or WIKIDATA_EDGE_CAP
    rows, winfo = collect_edges(wikidata_client or WikidataClient(), wikidata_seeds or [], depth, cap)
    edges, report = normalize_edges(prepare(rows), cap=cap, default_graph_name=graph_name)
    winfo["mode"] = "wikidata"
    winfo["notices"] = [LICENSE_NOTICE, DOMAIN_FIT_NOTICE]
    edges = add_labels(edges, report, winfo["notices"])
    return edges, {"report": report, "source": winfo}


def make_plan(az: Azure, ident: dict[str, Any], *, endpoint: str, index_name: str, edges: list[dict[str, Any]],
              extra: dict[str, Any], persist: bool = True) -> dict[str, Any]:
    endpoint = validate_endpoint(endpoint)
    validate_index_name(index_name)
    if not edges:
        raise GroundingError("NO_EDGES", "no valid edges remain after normalization", detail=extra["report"])
    problems: list[str] = []
    for e in edges:
        problems += validate_document(to_document(e))
        if len(problems) > 20:
            break
    if problems:
        raise GroundingError("EDGES_INVALID", "edges fail schema validation", detail=problems[:20])
    graph = next((e["graph_name"] for e in edges if e.get("graph_name")), "") or index_name
    for e in edges:
        e["graph_name"] = e.get("graph_name") or graph
    chash = content_hash(edges)
    plan_id = build_plan_id(chash, endpoint, index_name, graph)
    est = estimate_storage_bytes(edges)
    existing = get_index(az, endpoint, index_name)
    journal = state.load_journal(plan_id)
    resumable = False
    if existing is not None:
        owned = journal is not None and definitions_equivalent(build_index_definition(index_name), existing)
        if not owned:
            raise GroundingError("INDEX_EXISTS", f"index {index_name!r} already exists on the service and is not "
                                 "owned by this plan; refusing to overwrite", "Choose a different --index name.")
        resumable = True
    room = headroom(az, endpoint, est)
    source = extra["source"]
    changes = [f"Create index {index_name} with an edgeList graph profile (API {API_VERSION})"
               if existing is None else f"Index {index_name} exists and belongs to this plan: resume",
               f"Upload {len(edges)} edges in batches of up to {MAX_BATCH} (mergeOrUpload, deterministic ids)",
               "Verify document count, graph profile and a sample query"]
    cost = (f"no model or embedding calls; ~{est / 1e6:.1f} MB estimated index storage; index slot "
            f"{room['indexes_used']}/{room['indexes_quota']} used")
    notices = list(source.get("notices", []))
    plan = {"ok": True, "kind": "build", "plan_id": plan_id, "tenant": ident["tenant"],
            "subscription": ident["subscription"], "endpoint": endpoint, "index": index_name, "graph_name": graph,
            "schema_version": SCHEMA_VERSION, "api_version": API_VERSION, "content_hash": chash,
            "edge_count": len(edges), "estimated_storage_bytes": est, "headroom": room, "report": extra["report"],
            "source": {k: v for k, v in source.items() if k != "notices"}, "resumable": resumable,
            "changes": changes, "cost": cost, "notices": notices,
            "approval": approval_card(plan_id, f"grounding index {index_name} ({len(edges)} edges)", changes, cost,
                                      notices),
            "created_at": _now()}
    if persist:
        state.save_plan(plan)
        state.save_edges(plan_id, edges)
        plan["saved"] = True
    return plan


# --------------------------------------------------------------------------------------------------------------
def _load_approved(plan_id: str | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not plan_id:
        raise ApprovalError("PLAN_ID_REQUIRED", "--plan-id is required", "Run `grounding-build plan`, get approval, "
                            "then re-run with the displayed plan ID.")
    plan = state.load_plan(plan_id)
    if plan is None:
        raise ApprovalError("PLAN_NOT_FOUND", f"no saved plan {plan_id}", "Run `grounding-build plan` first.")
    edges = state.load_edges(plan_id)
    if content_hash(edges) != plan["content_hash"] or build_plan_id(
            content_hash(edges), plan["endpoint"], plan["index"], plan["graph_name"]) != plan_id:
        raise ApprovalError("PLAN_TAMPERED", "saved edges no longer match the approved plan ID",
                            "Re-run `grounding-build plan` and approve the new ID.")
    return plan, edges


def _upload(az: Azure, plan: dict[str, Any], edges: list[dict[str, Any]], journal: dict[str, Any], batch_size: int,
            stop_after: int | None) -> bool:
    if journal.get("next_batch", 0) > 0 and journal.get("batch_size"):
        batch_size = journal["batch_size"]  # next_batch indexes the original batch size
    docs = [to_document(e) for e in edges]
    batches = [docs[i:i + batch_size] for i in range(0, len(docs), batch_size)]
    journal["total_batches"], journal["batch_size"] = len(batches), batch_size
    done_this_run = 0
    for i in range(journal.get("next_batch", 0), len(batches)):
        if stop_after is not None and done_this_run >= stop_after:
            journal["phase"] = "uploading"
            state.save_journal(plan["plan_id"], journal)
            return False
        body = {"value": [{"@search.action": "mergeOrUpload", **d} for d in batches[i]]}
        res = az.search("POST", plan["endpoint"], f"/indexes/{plan['index']}/docs/index", body)
        failed = [r for r in res.get("value", []) if not r.get("status")]
        if failed:
            raise ServiceError("UPLOAD_PARTIAL", f"{len(failed)} documents were rejected in batch {i}",
                               "Re-run resume; uploads are idempotent.", detail=failed[:5])
        journal["next_batch"] = i + 1
        journal["uploaded_docs"] = min(len(docs), (i + 1) * batch_size)
        journal["phase"] = "uploading"
        journal["updated_at"] = _now()
        state.save_journal(plan["plan_id"], journal)
        done_this_run += 1
    return True


def verify(az: Azure, plan: dict[str, Any], timeout: float = VERIFY_TIMEOUT) -> dict[str, Any]:
    ep, name = plan["endpoint"], plan["index"]
    end = time.monotonic() + timeout
    count = -1
    while time.monotonic() < end:
        count = doc_count(az, ep, name)
        if count == plan["edge_count"]:
            break
        time.sleep(3)
    defn = get_index(az, ep, name)
    problems = validate_definition(defn) if defn else ["index missing"]
    sample = az.search("POST", ep, f"/indexes/{name}/docs/search", {"search": "*", "top": 3})
    ok = count == plan["edge_count"] and not problems and bool(sample.get("value"))
    return {"ok": ok, "document_count": count, "expected": plan["edge_count"], "profile_problems": problems,
            "sample_ok": bool(sample.get("value"))}


def _descriptor(plan: dict[str, Any], ver: dict[str, Any]) -> dict[str, Any]:
    src = plan["source"]
    return {"index": plan["index"], "service": plan["endpoint"].split("//")[1].split(".")[0],
            "endpoint": plan["endpoint"], "api_version": plan["api_version"], "schema_version": plan["schema_version"],
            "plan_id": plan["plan_id"], "edge_count": plan["edge_count"], "document_count": ver["document_count"],
            "graph_name": plan["graph_name"], "source_mode": src.get("mode"),
            "license": src.get("license", "unspecified"), "edge_report": plan["report"], "created_at": _now()}


def apply(az: Azure, ident: dict[str, Any], plan_id: str | None, *, batch_size: int = MAX_BATCH,
          stop_after_batches: int | None = None, resume: bool = False) -> dict[str, Any]:
    if not 1 <= batch_size <= MAX_BATCH:
        raise GroundingError("BATCH_SIZE_INVALID", f"batch size must be 1..{MAX_BATCH}")
    plan, edges = _load_approved(plan_id)
    if (ident["tenant"].lower(), ident["subscription"].lower()) != (plan["tenant"].lower(), plan["subscription"].lower()):
        raise GroundingError("IDENTITY_CHANGED", "tenant/subscription differ from those the plan was approved for")
    journal = state.load_journal(plan["plan_id"])
    ep, name = plan["endpoint"], plan["index"]
    existing = get_index(az, ep, name)
    planned = build_index_definition(name)
    if journal and journal.get("phase") == "complete" and not resume:
        ver = verify(az, plan, timeout=10)
        return {"ok": ver["ok"], "plan_id": plan["plan_id"], "already_applied": True, "verify": ver,
                "descriptor": state.load_descriptor(name)}
    if resume:
        if not journal:
            raise GroundingError("NO_JOURNAL", "nothing to resume for this plan ID", "Use apply instead.")
        if existing is None or not definitions_equivalent(planned, existing):
            raise GroundingError("INDEX_DIVERGED", "remote index is missing or differs from the planned definition; "
                                 "refusing to continue")
        remote = doc_count(az, ep, name)
        if remote > plan["edge_count"]:
            raise GroundingError("INDEX_DIVERGED", f"remote has {remote} documents, plan has {plan['edge_count']}")
    else:
        if existing is not None:
            if journal:
                raise GroundingError("RESUME_REQUIRED", "this plan was already started; use `grounding-build resume`")
            raise GroundingError("INDEX_EXISTS", f"index {name!r} exists and is not owned by this plan; refusing")
        headroom(az, ep, plan["estimated_storage_bytes"])
        bad = validate_definition(planned)
        if bad:
            raise GroundingError("SCHEMA_INVALID", "planned index definition violates the edgeList contract: " + "; ".join(bad))
        journal = {"plan_id": plan["plan_id"], "index": name, "phase": "created_pending", "next_batch": 0,
                   "uploaded_docs": 0, "started_at": _now()}
        state.save_journal(plan["plan_id"], journal)
        az.search("POST", ep, "/indexes", planned)
        journal["phase"] = "index_created"
        state.save_journal(plan["plan_id"], journal)
    finished = _upload(az, plan, edges, journal, batch_size, stop_after_batches)
    if not finished:
        return {"ok": True, "interrupted": True, "plan_id": plan["plan_id"], "uploaded_docs": journal["uploaded_docs"],
                "next_step": f"grounding-build resume --plan-id {plan['plan_id']}"}
    journal["phase"] = "uploaded"
    state.save_journal(plan["plan_id"], journal)
    ver = verify(az, plan)
    if not ver["ok"]:
        if 0 <= ver["document_count"] < plan["edge_count"]:
            journal.update(next_batch=0, uploaded_docs=0, phase="verify_failed", updated_at=_now())
            state.save_journal(plan["plan_id"], journal)  # uploads are idempotent; resume re-sends everything
        raise ServiceError("VERIFY_FAILED", "post-upload verification failed", "Run `grounding-build resume` or "
                           "`grounding-consume check`.", detail=ver)
    desc = _descriptor(plan, ver)
    state.save_descriptor(name, desc)
    journal.update(phase="complete", updated_at=_now())
    state.save_journal(plan["plan_id"], journal)
    return {"ok": True, "plan_id": plan["plan_id"], "resumed": resume, "verify": ver, "descriptor": desc,
            "delete_command_for_operator": delete_hint(plan),
            "next_step": f"grounding-consume check --index {name}"}


def delete_hint(plan: dict[str, Any]) -> str:
    return (f"To retire this index (this plugin never deletes), an operator can run: az rest --method delete "
            f"--resource https://search.azure.com --url \"{plan['endpoint']}/indexes/{plan['index']}"
            f"?api-version={API_VERSION}\"")


def status(plan_id: str | None = None) -> dict[str, Any]:
    """Local journal only; no Azure calls."""
    if plan_id:
        plan, j = state.load_plan(plan_id), state.load_journal(plan_id)
        if plan is None:
            raise GroundingError("PLAN_NOT_FOUND", f"no saved plan {plan_id}")
        return {"ok": True, "plan_id": plan_id, "index": plan["index"], "edge_count": plan.get("edge_count", plan.get("rows_total")),
                "kind": plan.get("kind", "build"), "phase": (j or {}).get("phase", "planned"), "journal": j}
    root = state.state_dir() / "plans"
    items = []
    for d in sorted(root.glob("pln-*")) if root.is_dir() else []:
        p, j = state.load_plan(d.name), state.load_journal(d.name)
        if p:
            items.append({"plan_id": d.name, "index": p["index"], "kind": p.get("kind", "build"),
                          "edge_count": p.get("edge_count", p.get("rows_total")),
                          "phase": (j or {}).get("phase", "planned")})
    return {"ok": True, "plans": items}
