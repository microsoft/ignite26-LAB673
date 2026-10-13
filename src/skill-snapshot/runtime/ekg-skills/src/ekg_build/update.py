"""Content-only updates to the published managed generation, in place.

The service re-extracts changed blobs but leaves leftovers that break Consume:
each indexer run keys graph triples with a new run prefix, so a changed
document's old triples are never matched by the service's stale-child cleanup,
and blob sources have no deletion tracking, so a removed blob keeps its chunks
and triples. The plan therefore binds every stale key before any write, and
cleanup deletes only those keys, after the indexer run has succeeded.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, unquote

from ekg_core.descriptors import descriptor_file
from ekg_core.execution import ApprovalRequired
from ekg_core.models import BuildSpec, OntologyMode, stable_id
from ekg_core.ontology import load_ontology
from ekg_core.telemetry import TelemetryRecorder
from .adapters import SearchRequestError
from .executor import _indexer_time_quota_checkpoint, _source_bytes, hash_json, source_provenance
from .generations import _generation_of
from .managed_pipeline import knowledge_source

REBUILD = "this needs a rebuild: run `ekg-build`"
INDEXER_POLLS = 120
INDEXER_DELAY_SECONDS = 15.0
# Deletes become visible to search after an index refresh, usually within a second or two.
REFRESH_POLLS = 10
REFRESH_DELAY_SECONDS = 2.0
_EXTRACTION_KEYS = ("graphName", "minEdgeConfidence", "pageDegreeOfParallelism")


class UpdateError(RuntimeError):
    pass


def _published(descriptor_path: str) -> tuple[dict[str, Any], str]:
    try:
        descriptor = json.loads(descriptor_file(descriptor_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise UpdateError(f"descriptor is not readable JSON: {descriptor_path}") from error
    endpoints = descriptor.get("endpoints") or {}
    generation = _generation_of(str(endpoints.get("knowledge_source") or ""))
    staged = (descriptor.get("source_provenance") or {}).get("staged")
    if generation is None or not isinstance(staged, dict) or not endpoints.get("graph_index"):
        raise UpdateError("the descriptor is not a published managed graph build; " + REBUILD)
    return descriptor, generation


def _definition_blockers(spec: BuildSpec, descriptor: dict[str, Any], generation: str,
                         live: dict[str, Any] | None) -> list[str]:
    endpoints = descriptor["endpoints"]
    if spec.ontology_mode is OntologyMode.NONE or spec.source_manifest is None:
        return ["update needs the build's ontology and an approved source manifest"]
    if (spec.target.search_endpoint or "").rstrip("/") != endpoints.get("search", "").rstrip("/") or (
            (spec.target.storage_endpoint or "").rstrip("/") != endpoints.get("storage", "").rstrip("/")):
        return ["the Search or Storage target differs from the published build; " + REBUILD]
    ontology = load_ontology(spec.ontology_mode, path=spec.ontology_path,
                             schema_org_profile=spec.schema_org_profile,
                             schema_org_version=spec.schema_org_version,
                             resolve_imports=spec.resolve_imports)
    if ontology is None or ontology.schema_id != (descriptor.get("ontology") or {}).get("schema_id"):
        return ["the ontology changed; " + REBUILD]
    if live is None:
        return ["the published knowledge source no longer exists; " + REBUILD]
    name = endpoints["knowledge_source"]
    want = _bound(knowledge_source(spec, name=name, ontology_name=f"ekg-ontology-{generation}",
                                   graph_name=name, prefix=generation))
    have = _bound(live)
    return [f"the {part} changed; {REBUILD}" for part in want if have[part] != want[part]][:1]


def _bound(definition: dict[str, Any]) -> dict[str, list[Any]]:
    """The Knowledge Source settings an in-place update must not change."""
    blob = definition.get("azureBlobParameters") or {}
    ingest = blob.get("ingestionParameters") or {}
    graph = ingest.get("graphExtraction") or {}

    def model(kind: str) -> list[Any]:
        found = (ingest.get(kind) or {}).get("azureOpenAIParameters") or {}
        return [found.get(key) for key in ("resourceUri", "deploymentId", "modelName")]

    return {"source location": [blob.get("containerName"), blob.get("folderPath")],
            "model deployments": model("embeddingModel") + model("chatCompletionModel"),
            "extraction settings": [graph.get(key) for key in _EXTRACTION_KEYS] + [
                (graph.get("ontology") or {}).get("indexName"),
                (((graph.get("grounding") or {}).get("index")) or {}).get("indexName"),
                (graph.get("extraction") or {}).get("reasoningEffort")]}


def _delta(old: dict[str, dict[str, str]], new: dict[str, dict[str, str]]) -> dict[str, list[str]]:
    return {
        "added": sorted(set(new) - set(old)),
        "changed": sorted(url for url in set(new) & set(old)
                          if new[url]["version_or_hash"] != old[url]["version_or_hash"]),
        "deleted": sorted(set(old) - set(new)),
    }


def _stale(dp: Any, endpoints: dict[str, str], touched: set[str],
           staged: set[str]) -> dict[str, Any]:
    """Keys to remove: chunks of changed/removed docs, and triples on any chunk that goes."""
    chunks = dp.scan(endpoints["content_index"], "uid,blob_url", "uid")
    triples = dp.scan(endpoints["graph_index"], "id,chunk_id", "id")
    stale_chunks = sorted(c["uid"] for c in chunks
                          if c.get("blob_url") in touched or c.get("blob_url") not in staged)
    keep = {c["uid"] for c in chunks} - set(stale_chunks)
    stale_triples = sorted(t["id"] for t in triples if t.get("chunk_id") not in keep)
    return {"chunks": stale_chunks, "triples": stale_triples,
            "kept_chunks": len(keep), "kept_triples": len(triples) - len(stale_triples)}


def update_plan(dp: Any, spec: BuildSpec, descriptor_path: str) -> dict[str, Any]:
    """Read-only: the delta to stage and every stale key cleanup may delete."""
    descriptor, generation = _published(descriptor_path)
    endpoints = descriptor["endpoints"]
    live = dp.get_knowledge_source(endpoints["knowledge_source"])
    blockers = _definition_blockers(spec, descriptor, generation, live)
    if not spec.build_journal:
        blockers.append("update needs --build-journal; its folder holds the update journal")
    new = source_provenance(spec, prefix=generation) if not blockers else {}
    delta = _delta(descriptor["source_provenance"]["staged"], new)
    stale = (_stale(dp, endpoints, set(delta["changed"]) | set(delta["deleted"]), set(new))
             if not blockers else {"chunks": [], "triples": [], "kept_chunks": 0, "kept_triples": 0})
    identity = {"search_endpoint": endpoints["search"].rstrip("/").lower(),
                "generation": generation,
                "delta": {key: [[url, new.get(url, {}).get("version_or_hash")] for url in urls]
                          for key, urls in delta.items()},
                "stale": {"chunks": stale["chunks"], "triples": stale["triples"]}}
    staged, removed = len(delta["added"]) + len(delta["changed"]), len(delta["deleted"])
    plan_id = stable_id("update-plan", identity)
    return {
        "plan_id": plan_id,
        "summary": (f"Update {staged} doc(s), remove {removed} doc(s); about "
                    f"{len(stale['triples'])} stale graph fact(s) and {len(stale['chunks'])} "
                    "stale chunk(s) will be cleaned; no new index slots."
                    if not blockers else f"Blocked: {blockers[0]}"),
        "next_step": ("Resolve the blocker, then run `ekg-build plan-update` again." if blockers else
                      "After approval, run `ekg-build update` with the same flags plus "
                      f"--plan-id {plan_id} --confirm-writes."),
        "generation": generation, "delta": delta, "stale": stale,
        "source_provenance": new, "blockers": blockers,
        "write": {"requires_approval": True, "stage": staged, "remove": removed,
                  "indexer_runs": 1 if staged or removed else 0,
                  "document_deletes": len(stale["chunks"]) + len(stale["triples"]),
                  "local": "the descriptor is rewritten with the new source mapping"},
        "undo": "rerun update with the previous source, or rebuild with `ekg-build`",
    }


def _journal_path(spec: BuildSpec, plan_id: str) -> Path:
    return Path(spec.build_journal or "").with_name(f"{plan_id}.json")


def _save(path: Path, record: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(record, sort_keys=True, indent=1), encoding="utf-8")
    os.replace(temporary, path)


def _stage(dp: Any, spec: BuildSpec, review: dict[str, Any], reader: Any) -> None:
    prefix = f"{spec.target.storage_endpoint}/{quote(spec.storage_container, safe='')}/"
    contents = dict(zip(review["source_provenance"], _source_bytes(spec, reader)))
    for url in review["delta"]["added"] + review["delta"]["changed"]:
        dp.stage(spec.storage_container, unquote(url.removeprefix(prefix)), contents[url],
                 overwrite=True)
    for url in review["delta"]["deleted"]:
        dp.delete_blob(spec.storage_container, unquote(url.removeprefix(prefix)))


def _last_run(dp: Any, indexer: str) -> dict[str, Any]:
    return (dp.indexer_status(indexer) or {}).get("lastResult") or {}


def _await_indexer(dp: Any, indexer: str, prior_start: str | None,
                   sleep: Callable[[float], None]) -> dict[str, Any] | None:
    for attempt in range(INDEXER_POLLS):
        run = _last_run(dp, indexer)
        if run.get("startTime") != prior_start and run.get("status") not in (None, "inProgress"):
            return run
        if attempt + 1 < INDEXER_POLLS:
            sleep(INDEXER_DELAY_SECONDS)
    return None


def _gate(dp: Any, endpoints: dict[str, str], review: dict[str, Any]) -> list[str]:
    chunks = dp.scan(endpoints["content_index"], "uid,blob_url", "uid")
    triples = dp.scan(endpoints["graph_index"], "id,chunk_id", "id")
    uids = {c["uid"] for c in chunks}
    stale_chunks, stale_triples = set(review["stale"]["chunks"]), set(review["stale"]["triples"])
    fresh = [c for c in chunks if c["uid"] not in stale_chunks
             and c.get("blob_url") in set(review["delta"]["added"]) | set(review["delta"]["changed"])]
    problems = []
    if uids & stale_chunks or {t["id"] for t in triples} & stale_triples:
        problems.append("stale keys are still served")
    if any(t.get("chunk_id") not in uids for t in triples):
        problems.append("graph facts point at missing chunks")
    if {c.get("blob_url") for c in chunks} != set(review["source_provenance"]):
        problems.append("served documents differ from the source")
    if len(chunks) - len(fresh) != review["stale"]["kept_chunks"]:
        problems.append("unchanged document chunks changed")
    fresh_uids = {c["uid"] for c in fresh}
    if sum(t.get("chunk_id") not in fresh_uids for t in triples) != review["stale"]["kept_triples"]:
        problems.append("unchanged document graph facts changed")
    return problems


def _reindexed(dp: Any, endpoints: dict[str, str], review: dict[str, Any]) -> int:
    """How many staged docs still have no chunk from the new run."""
    stale = set(review["stale"]["chunks"])
    served = {c.get("blob_url") for c in dp.scan(endpoints["content_index"], "uid,blob_url", "uid")
              if c["uid"] not in stale}
    return sum(url not in served for url in review["delta"]["added"] + review["delta"]["changed"])


def _publish(descriptor_path: str, descriptor: dict[str, Any], spec: BuildSpec,
             review: dict[str, Any]) -> None:
    provenance = {"manifest_digest": spec.source_manifest.digest,
                  "staged": review["source_provenance"]}
    provenance["mapping_digest"] = hash_json(provenance)
    updated = {**descriptor, "source_provenance": provenance,
               "endpoints": {**descriptor["endpoints"],
                             "source_manifest_digest": spec.source_manifest.digest}}
    _save(Path(descriptor_path), updated)


def _resume(dp: Any, spec: BuildSpec, descriptor_path: str, generation: str,
            path: Path, approved_plan_id: str) -> dict[str, Any]:
    if path.is_file():
        record = json.loads(path.read_text(encoding="utf-8"))
        if record["state"] != "approved":
            # Cleanup shrinks the stale set, so a resumed run re-checks only the source.
            if (record["state"] != "published" and record["plan"]["source_provenance"]
                    != source_provenance(spec, prefix=generation)):
                raise UpdateError("the source changed since this update was approved; "
                                  "run `ekg-build plan-update` again")
            return record
    review = update_plan(dp, spec, descriptor_path)
    if approved_plan_id != review["plan_id"]:
        raise ApprovalRequired(
            f"explicit approval of update plan {review['plan_id']} is required; "
            "the source or the served graph changed since review")
    if review["blockers"]:
        raise UpdateError(review["blockers"][0])
    record = {"plan": review, "state": "approved", "telemetry": []}
    _save(path, record)
    return record


def update(dp: Any, spec: BuildSpec, descriptor_path: str, *, approved_plan_id: str,
           confirmed: bool, reader: Any = None,
           sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Apply an approved update plan; every step is journaled so a rerun resumes."""
    if not confirmed:
        raise ApprovalRequired("update writes require explicit confirmation")
    descriptor, generation = _published(descriptor_path)
    endpoints = descriptor["endpoints"]
    path = _journal_path(spec, approved_plan_id)
    record = _resume(dp, spec, descriptor_path, generation, path, approved_plan_id)
    review, delta = record["plan"], record["plan"]["delta"]
    recorder = TelemetryRecorder("build")
    indexer = f"{endpoints['knowledge_source']}-indexer"

    def advance(state: str, **extra: Any) -> None:
        record.update(state=state, **extra)
        record["telemetry"] = record["telemetry"] + recorder.events
        recorder.events.clear()
        _save(path, record)

    def result(status: str, message: str, next_step: str) -> dict[str, Any]:
        return {"status": status, "summary": message, "next_step": next_step,
                "plan_id": approved_plan_id,
                "journal": str(path), "state": record["state"], "delta": delta,
                "telemetry": record["telemetry"]}

    if record["state"] == "approved":
        if not any(delta.values()):
            advance("indexed")
        else:
            with recorder.span("update-stage", resource="blob") as span:
                _stage(dp, spec, review, reader)
                span["counts"]["documents"] = sum(len(urls) for urls in delta.values())
            advance("staged")
    if record["state"] == "staged":
        prior = _last_run(dp, indexer).get("startTime")
        try:
            with recorder.span("update-indexer-run", resource="indexer"):
                dp.run_indexer(indexer)
        except SearchRequestError as error:
            if error.status != 409:
                raise
            return result("waiting", "The indexer is already running.",
                          "Rerun update with the same plan ID in a few minutes.")
        advance("indexing", prior_start=prior)
    if record["state"] == "indexing":
        with recorder.span("update-indexer-wait", resource="indexer") as span:
            run = _await_indexer(dp, indexer, record.get("prior_start"), sleep)
            span["counts"]["documents"] = (run or {}).get("itemsProcessed") or 0
        if run is None:
            advance("indexing")
            return result("waiting", "The indexer is still running.",
                          "Rerun update with the same plan ID to continue.")
        if _indexer_time_quota_checkpoint(run):
            advance("indexing")
            return result("waiting", "The indexer reached the normal 120-minute checkpoint.",
                          "Wait for the next scheduled continuation, then rerun update with "
                          "the same plan ID.")
        failed = run.get("itemsFailed") or len(run.get("errors") or ())
        if run.get("status") != "success" or failed:
            advance("staged")
            return result("stopped", f"The indexer reported {failed or 'a'} failure(s), so "
                                     "nothing was cleaned.",
                          "Fix the cause, then rerun update with the same plan ID.")
        missing = _reindexed(dp, endpoints, review)
        if missing:
            advance("staged")
            # An empty document yields no chunks, which looks the same as a skipped one.
            return result("stopped", f"{missing} document(s) have no chunks after the indexer "
                                     "run (for example an empty document), so nothing was "
                                     "cleaned.",
                          "Fix or remove those documents and run `ekg-build plan-update` again, or rerun "
                          "update with the previous source to undo.")
        advance("indexed")
    if record["state"] == "indexed":
        with recorder.span("update-cleanup", resource="search_index") as span:
            dp.delete_documents(endpoints["graph_index"], "id", review["stale"]["triples"])
            dp.delete_documents(endpoints["content_index"], "uid", review["stale"]["chunks"])
            span["counts"]["documents"] = (len(review["stale"]["triples"])
                                           + len(review["stale"]["chunks"]))
        advance("cleaned")
    if record["state"] == "cleaned":
        with recorder.span("update-verify", resource="search_index"):
            for attempt in range(REFRESH_POLLS):
                problems = _gate(dp, endpoints, review)
                if not problems or attempt + 1 == REFRESH_POLLS:
                    break
                sleep(REFRESH_DELAY_SECONDS)
        if problems:
            advance("inconsistent", problems=problems)
        else:
            advance("verified")
    if record["state"] == "inconsistent":
        return result("inconsistent", "The graph is inconsistent after cleanup ("
                      + "; ".join(record.get("problems") or ()) + ").",
                      "Rebuild with `ekg-build plan` and `ekg-build apply`.")
    if record["state"] == "verified":
        _publish(descriptor_path, descriptor, spec, review)
        advance("published", published_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    return result("updated", f"Updated {len(delta['added']) + len(delta['changed'])} doc(s) "
                             f"and removed {len(delta['deleted'])}; cleaned "
                             f"{len(review['stale']['triples'])} stale graph fact(s).",
                  "Nothing else to do; the descriptor now maps the new source.")


def updated_in_place(spec: BuildSpec) -> str | None:
    """When this Build's generation was later updated in place: its descriptor is current."""
    journal = Path(spec.build_journal or "")
    try:
        built = json.loads(journal.read_text(encoding="utf-8")).get("generation")
    except (OSError, ValueError, AttributeError):
        return None
    for path in sorted(journal.parent.glob("update-plan-*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if record.get("state") == "published" and (record.get("plan") or {}).get(
                "generation") == built:
            return record.get("published_at") or datetime.fromtimestamp(
                path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
    return None
