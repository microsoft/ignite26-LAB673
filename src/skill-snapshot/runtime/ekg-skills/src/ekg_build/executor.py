from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ekg_core.execution import ApplyResult, ApprovalRequired
from ekg_core.models import BuildSpec, Event, OntologyMode, SourceKind, stable_id
from ekg_core.ontology import load_ontology
from ekg_core.telemetry import TelemetryRecorder, adapter_http_stats, service_window_event

from .adapters import DataPlane, SearchRequestError
from .managed_pipeline import (
    EDGE_FIELDS, SEARCH_API_VERSION, generated, knowledge_source, ontology_index,
    ontology_rows,
)
from .planner import plan, verification_blockers
from .preflight import ResourceReader, preflight
from .blob_sources import BlobReader, inventory_blob_prefix, read_pinned_blob, recheck_blob_inventory
from .local_sources import approved_local_bytes, approved_local_sample
from .preview import probe_error, search_resource_id


class BuildError(RuntimeError):
    pass


def _require_managed_entitlement(spec: BuildSpec, adapter: DataPlane) -> dict[str, Any]:
    reason = probe_error(spec)
    if reason:
        raise BuildError(reason)
    resource_id = search_resource_id(spec)
    observed = adapter.inspect_search_service(resource_id, spec.tenant_id)
    if not isinstance(observed, dict):
        raise BuildError("Search service GET failed; no writes permitted")
    properties = observed.get("properties")
    sku = observed.get("sku")
    if not isinstance(properties, dict) or not isinstance(sku, dict):
        raise BuildError("Search service metadata is malformed; no writes permitted")
    name = resource_id.rsplit("/", 1)[-1]
    if (
        str(observed.get("id", "")).casefold() != resource_id.casefold()
        or str(observed.get("name", "")).casefold() != name.casefold()
        or str(observed.get("location", "")).replace(" ", "").casefold() !=
            str(spec.target.location or "").casefold()
        or not isinstance(sku.get("name"), str)
        or sku["name"].casefold() != spec.search_sku.casefold()
        or str(properties.get("provisioningState", "")).casefold() != "succeeded"
        or properties.get("endpoint") != spec.target.search_endpoint
    ):
        raise BuildError("exact Search service identity, region, SKU or endpoint differs; no writes permitted")
    return {"status": "guarded_attempt_requires_approval", "technically_verified": False,
            "evidence_origin": "fresh_arm_service_identity_only",
            "resource_id": resource_id, "region": observed["location"], "sku": sku["name"],
            "tenant_id": spec.tenant_id}


COUNT_VISIBILITY_ATTEMPTS = 12
COUNT_VISIBILITY_DELAY_SECONDS = 5.0


def _await_index_count(adapter: DataPlane, name: str, expected: int) -> None:
    # Search accepts uploads before they are searchable; poll reads only, never rewrite.
    observed = -1
    for attempt in range(COUNT_VISIBILITY_ATTEMPTS):
        observed = adapter.count(name)
        if observed >= expected:
            break
        if attempt + 1 < COUNT_VISIBILITY_ATTEMPTS:
            time.sleep(COUNT_VISIBILITY_DELAY_SECONDS)
    if observed != expected:
        raise BuildError(
            f"ontology index count differs from approved rows (observed {observed}, expected {expected})"
        )


def _failure_detail(error: Exception) -> dict[str, str]:
    detail = {"error_type": type(error).__name__}
    if isinstance(error, BuildError):
        detail["error_message"] = str(error)
    elif isinstance(error, SearchRequestError):
        detail["error_message"] = f"Search request failed with HTTP {error.status}"
    return detail


def corpus_files(source: str) -> list[tuple[str, bytes]]:
    path = Path(source)
    if path.is_file():
        paths, base = [path], path.parent
    elif path.is_dir():
        paths, base = sorted(p for p in path.rglob("*") if p.is_file()), path
    else:
        raise ValueError(f"corpus source does not exist: {source}")
    if not paths:
        raise ValueError("corpus is empty")
    if any(p.suffix.lower() not in {".txt", ".md"} for p in paths):
        raise ValueError("initial build supports only UTF-8 .txt and .md corpus files")
    return [(p.relative_to(base).as_posix(), p.read_bytes()) for p in paths]


def generation(spec: BuildSpec) -> str:
    if spec.source_manifest is not None:
        ontology = load_ontology(
            spec.ontology_mode, path=spec.ontology_path,
            schema_org_profile=spec.schema_org_profile,
            schema_org_version=spec.schema_org_version,
            resolve_imports=spec.resolve_imports,
        )
        return stable_id("ekg", {
            "spec": {**{k: v for k, v in asdict(spec).items()
                        if k != "readers" and not (k in ("trial", "grounding_index") and v is None)},
                     "source_manifest": spec.source_manifest.digest},
            "ontology_schema_id": ontology.schema_id if ontology else None,
        })[-16:]
    digest = hashlib.sha256()
    for name, data in corpus_files(spec.corpus_source):
        digest.update(name.encode())
        digest.update(hashlib.sha256(data).digest())
    if spec.ontology_mode is OntologyMode.OWL_FILE:
        digest.update(Path(spec.ontology_path or "").read_bytes())
    return stable_id("ekg", {
        "spec": spec,
        "corpus_hash": digest.hexdigest(),
    })[-16:]


def staging_prefix(spec: BuildSpec) -> str:
    """Blob folder the generation's documents are staged under; trials stay apart."""
    return f"trial/{generation(spec)}" if spec.trial is not None else generation(spec)


def index_names(spec: BuildSpec) -> dict[str, str]:
    suffix = generation(spec)
    if spec.ontology_mode is OntologyMode.NONE:
        return {"content": f"ekg-content-{suffix}"}
    return {"ontology": f"ekg-ontology-{suffix}",
            "knowledge_source": f"ekg-managed-{suffix}"}


def source_provenance(spec: BuildSpec, prefix: str | None = None) -> dict[str, dict[str, str]]:
    """Deterministic one-to-one generation-scoped staging identity."""
    manifest = spec.source_manifest
    if manifest is None or not spec.target.storage_endpoint:
        raise BuildError("approved source manifest and destination are required")
    prefix = prefix or staging_prefix(spec)
    result = {}
    for item in manifest.items:
        suffix = ".md" if item.media_type.split(";", 1)[0].lower() == "text/markdown" else ".txt"
        name = f"{prefix}/{item.source_id}{suffix}"
        url = (f"{spec.target.storage_endpoint}/{quote(spec.storage_container, safe='')}/"
               f"{quote(name, safe='/')}")
        if url in result:
            raise BuildError("SOURCE_MAPPING_AMBIGUOUS: duplicate staging destination")
        result[url] = {
            "source_id": item.source_id, "original_uri": item.original_uri,
            "citation_uri": item.citation_uri, "version_or_hash": item.version_or_hash,
        }
    return result


def _source_bytes(spec: BuildSpec, reader: BlobReader | None) -> tuple[bytes, ...]:
    manifest = spec.source_manifest
    if manifest is None or spec.source is None:
        raise BuildError("SOURCE_MANIFEST_REQUIRED: inventory source before approval")
    if spec.source.kind in {SourceKind.LOCAL_PATH, SourceKind.ZIP_ARCHIVE}:
        if spec.trial is not None:
            return tuple(value.content for value in approved_local_sample(
                manifest, spec.trial.corpus_digest))
        return tuple(value.content for value in approved_local_bytes(manifest, manifest.digest))
    if spec.source.kind is SourceKind.BLOB_PREFIX:
        if reader is None:
            raise BuildError("SOURCE_READER_REQUIRED: Blob route requires a pinned reader")
        tenant = spec.tenant_id
        if tenant is None:
            raise BuildError("TENANT_MISMATCH: Blob source requires an explicit tenant")
        inventory = inventory_blob_prefix(spec.source, reader, tenant_id=tenant)
        if spec.trial is not None:
            current = {item.source_id: item for item in inventory.manifest.items}
            if (inventory.manifest.digest != spec.trial.corpus_digest
                    or any(current.get(item.source_id) != item for item in manifest.items)):
                raise BuildError("SOURCE_DRIFT: Blob inventory differs from approved manifest")
        elif inventory.manifest.digest != manifest.digest or inventory.manifest.items != manifest.items:
            raise BuildError("SOURCE_DRIFT: Blob inventory differs from approved manifest")
        recheck_blob_inventory(inventory, reader, tenant_id=tenant)
        pins = {pin.source_id: pin for pin in inventory.pins}
        return tuple(read_pinned_blob(inventory, pins[item.source_id], reader,
                                      tenant_id=tenant).data
                     for item in manifest.items)
    raise BuildError("UNSUPPORTED_GRAPH_ROUTE: source kind cannot be staged")


def _source_record(spec: BuildSpec, state: str) -> dict[str, Any]:
    desired = plan(spec)
    names = index_names(spec)
    definition = knowledge_source(
        spec, name=names["knowledge_source"], ontology_name=names["ontology"],
        graph_name=names["knowledge_source"], prefix=staging_prefix(spec),
    )
    return {
        "version": 2, "run_id": f"build-{generation(spec)}", "plan_id": desired.plan_id,
        "scope": desired.scope, "generation": generation(spec),
        "knowledge_source": names["knowledge_source"],
        "create_request_hash": hash_json(definition), "create_receipt": None,
        "preview_entitlement": "unverified_before_attempt", "state": state,
        "counts": {}, "timings_ms": {}, "readers": list(spec.readers),
    }


def _create_source_journal(spec: BuildSpec) -> bytes:
    if not spec.build_journal:
        raise BuildError("source graph requires a durable build journal")
    path = Path(spec.build_journal)
    if spec.source and spec.source.kind in {SourceKind.LOCAL_PATH, SourceKind.ZIP_ARCHIVE}:
        source_path = Path(spec.source.reference).resolve()
        if path.resolve() == source_path or (
            source_path.is_dir() and path.resolve().is_relative_to(source_path)
        ):
            raise BuildError("build journal must be outside the caller-owned source")
    return _journal(spec, _source_record(spec, "attempt_requested"))


def _advance_source_journal(spec: BuildSpec, original: bytes, **changes: Any) -> bytes:
    path = Path(spec.build_journal or "")
    if path.read_bytes() != original:
        raise BuildError("build journal changed during the run")
    record = json.loads(original)
    if any(key in changes for key in (
        "scope", "plan_id", "generation", "run_id", "create_request_hash",
    )):
        raise BuildError("immutable journal identity cannot be changed")
    updated = json.dumps({**record, **changes}, sort_keys=True).encode("utf-8")
    temporary = path.with_name(path.name + ".next.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        if path.read_bytes() != original:
            raise BuildError("build journal changed during the run")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return updated


def hash_json(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _identity_readback_matches(observed: Any, expected: dict[str, str]) -> bool:
    return observed == expected or observed == {
        **expected, "federatedIdentityClientId": None,
    }


def _document_schema(name: str, dimensions: int | None) -> dict[str, Any]:
    fields: list[dict[str, Any]] = [
        {"name": "id", "type": "Edm.String", "key": True, "filterable": True},
        {"name": "name", "type": "Edm.String", "searchable": True},
        {"name": "text", "type": "Edm.String", "searchable": True},
        {"name": "source", "type": "Edm.String", "filterable": True},
        {"name": "provenance", "type": "Edm.String"},
    ]
    result: dict[str, Any] = {"name": name, "fields": fields}
    if dimensions:
        fields.append({"name": "embedding", "type": "Collection(Edm.Single)",
                       "searchable": True, "dimensions": dimensions,
                       "vectorSearchProfile": "vector-profile"})
        result["vectorSearch"] = {
            "algorithms": [{"name": "hnsw", "kind": "hnsw"}],
            "profiles": [{"name": "vector-profile", "algorithm": "hnsw"}],
        }
    return result


def _journal(spec: BuildSpec, record: dict[str, Any]) -> bytes:
    if not spec.build_journal:
        raise BuildError("managed builds require a journal")
    path = Path(spec.build_journal)
    corpus = Path(spec.corpus_source)
    if spec.source is None and corpus.is_dir() and path.resolve().is_relative_to(corpus.resolve()):
        raise BuildError("managed build journal must be outside the corpus")
    original = json.dumps(record, sort_keys=True).encode("utf-8")
    with path.open("xb") as stream:
        stream.write(original)
        stream.flush()
        os.fsync(stream.fileno())
    return original


def _read_attempt_journal(spec: BuildSpec) -> tuple[dict[str, Any], bytes]:
    path = Path(spec.build_journal or "")
    if not path.is_file():
        raise BuildError("managed build attempt journal is missing")
    corpus = Path(spec.corpus_source)
    if spec.source is None and corpus.is_dir() and path.resolve().is_relative_to(corpus.resolve()):
        raise BuildError("managed build journal must be outside the corpus")
    original = path.read_bytes()
    try:
        record = json.loads(original)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BuildError("managed build attempt journal is malformed") from error
    if not isinstance(record, dict):
        raise BuildError("managed build attempt journal is malformed")
    return record, original


def _complete_journal(spec: BuildSpec, name: str, original: bytes) -> None:
    path = Path(spec.build_journal or "")
    temporary = path.with_name(path.name + ".verified.tmp")
    if path.read_bytes() != original:
        raise BuildError("managed build attempt journal changed during verification")
    record = json.loads(original)
    if record.get("state") != "attempt_requested" or record.get("knowledge_source") != name:
        raise BuildError("managed build attempt journal changed state or knowledge source")
    created = False
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            created = True
            json.dump({**record, "state": "verified"}, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        if path.read_bytes() != original:
            raise BuildError("managed build attempt journal changed during verification")
        os.replace(temporary, path)
    finally:
        if created:
            temporary.unlink(missing_ok=True)


def _state_text(item: dict[str, Any]) -> str:
    parts = [item.get("errorMessage"), item.get("message"), item.get("details")]
    for key in ("errors", "itemErrors", "warnings"):
        for entry in item.get(key) or []:
            if isinstance(entry, dict):
                parts.extend([entry.get("errorMessage"), entry.get("message"), entry.get("details")])
            else:
                parts.append(entry)
    return " ".join(str(part) for part in parts if part).casefold()


def _indexer_time_quota_checkpoint(item: dict[str, Any]) -> bool:
    status = str(
        item.get("status") or item.get("synchronizationStatus") or item.get("state") or ""
    ).lower()
    text = _state_text(item)
    return (
        status == "transientfailure"
        and "indexer execution time quota" in text
        and "120 minutes" in text
    )


def _sync_checkpoint(status: dict[str, Any]) -> dict[str, Any] | None:
    current = status.get("currentSynchronizationState") or {}
    last = status.get("lastSynchronizationState") or {}
    for item in (current, last):
        if isinstance(item, dict) and _indexer_time_quota_checkpoint(item):
            return item
    return None


def _sync_status(status: dict[str, Any]) -> dict[str, Any] | None:
    state = status.get("lastSynchronizationState") or {}
    current = status.get("currentSynchronizationState") or {}
    if not isinstance(state, dict) or not isinstance(current, dict):
        raise BuildError("managed synchronization status is malformed")
    for item in (state, current):
        if _indexer_time_quota_checkpoint(item):
            continue
        if (item.get("errors") or item.get("itemErrors") or
                item.get("itemsUpdatesFailed", 0) or item.get("itemsFailed", 0)):
            raise BuildError("managed synchronization reported failed items")
        status_name = str(
            item.get("status") or item.get("synchronizationStatus") or item.get("state") or ""
        ).lower()
        if status_name in {
            "failed", "failure", "error", "partialsuccess",
            "transientfailure", "persistentfailure", "cancelled", "canceled",
        }:
            raise BuildError("managed synchronization failed")
    if current and (
        not current.get("endTime") or
        str(current.get("status") or current.get("synchronizationStatus")
            or current.get("state") or "").lower() in {"running", "inprogress"}
        or _indexer_time_quota_checkpoint(current)
    ):
        return None
    if state.get("endTime"):
        if _indexer_time_quota_checkpoint(state):
            return None
        terminal = str(
            state.get("status") or state.get("synchronizationStatus")
            or state.get("state") or ""
        ).lower()
        if terminal and terminal not in {"success", "succeeded", "completed", "complete"}:
            raise BuildError("managed synchronization ended without a success status")
        return state
    return None


def _synchronization_event(state: dict[str, Any]) -> dict[str, Any] | None:
    """Service-side managed synchronization window from Knowledge Source status."""
    if not isinstance(state, dict):
        return None
    counts = {key: value for key, value in (
        ("items_processed", state.get("itemsUpdatesProcessed")),
        ("items_failed", state.get("itemsUpdatesFailed")),
        ("items_skipped", state.get("itemsSkipped")),
    ) if isinstance(value, int) and not isinstance(value, bool)}
    return service_window_event(
        "build", "managed_synchronization", state.get("startTime"), state.get("endTime"),
        origin="live_knowledge_source_status", counts=counts,
    )


def _merge_telemetry(prior: list[Any], new: list[dict[str, Any]]) -> list[Any]:
    """Append new events, replacing an earlier service window for the same synchronization."""
    windows = {(event.get("operation"), event.get("started_at")) for event in new
               if isinstance(event, dict) and event.get("origin") == "live_knowledge_source_status"}
    kept = [event for event in prior if not (
        isinstance(event, dict) and (event.get("operation"), event.get("started_at")) in windows)]
    return [*kept, *new]



class BuildExecutor:
    def __init__(self, adapter: DataPlane, *,
                 blob_reader: BlobReader | None = None,
                 target_reader: ResourceReader | None = None,
                 upload_concurrency: int = 16) -> None:
        self.adapter = adapter
        self.blob_reader = blob_reader
        self.target_reader = target_reader
        self.upload_concurrency = upload_concurrency

    def _source_targets(self, spec: BuildSpec) -> dict[str, Any]:
        if self.target_reader is None or not hasattr(self.target_reader, "inspect_resource"):
            raise BuildError("TARGET_VERIFICATION_REQUIRED: exact Search, Storage and OpenAI ARM reader required")
        inspected = preflight(spec, self.target_reader)
        if inspected.status == "blocked":
            raise BuildError("; ".join(inspected.events[0].data["blockers"]))
        evidence = inspected.events[0].data["evidence"]
        if not all(evidence.get(key) is True for key in (
            "search_arm_observed", "storage_arm_observed", "openai_arm_observed",
        )):
            raise BuildError("TARGET_VERIFICATION_REQUIRED: all exact target identities must be observed")
        return _require_managed_entitlement(spec, self.adapter)

    def inspect(self, spec: BuildSpec) -> dict[str, Any]:
        desired = plan(spec)
        if desired.route is not None and desired.blocked_by:
            return preflight(spec).to_dict()
        if spec.ontology_mode is not OntologyMode.NONE:
            if desired.blocked_by:
                return {"plan_id": desired.plan_id, "status": "blocked",
                        "blocked_by": list(desired.blocked_by)}
            return {"plan_id": desired.plan_id,
                    **_require_managed_entitlement(spec, self.adapter)}
        names = index_names(spec)
        if spec.ontology_mode is OntologyMode.NONE:
            return {"plan_id": desired.plan_id,
                    "indexes": {"content": self.adapter.get_index(names["content"])}}

    def apply(self, spec: BuildSpec, *, approved_plan_id: str,
              approved: bool = False, wait_for_sync: bool = True) -> ApplyResult:
        desired = plan(spec)
        if desired.blocked_by:
            raise BuildError("; ".join(desired.blocked_by))
        if approved_plan_id != desired.plan_id or not approved:
            raise ApprovalRequired(f"explicit approval of plan {desired.plan_id} is required")
        if spec.vector_retrieval and not spec.embedding_deployment:
            raise BuildError("vector builds require an embedding deployment")
        if spec.ontology_mode is OntologyMode.NONE:
            return self._apply_documents(spec)
        if spec.source_manifest is not None:
            return self._apply_source(spec, wait_for_sync=wait_for_sync)
        return self._apply_managed(spec)

    def progress(self, spec: BuildSpec) -> dict[str, Any]:
        from .wait_progress import progress
        return progress(self, spec)

    def reconcile(self, spec: BuildSpec) -> dict[str, Any]:
        from .reconcile import reconcile
        return reconcile(self, spec)

    def _apply_source(self, spec: BuildSpec, *, wait_for_sync: bool = True) -> ApplyResult:
        from .staging import _apply_source
        return _apply_source(self, spec, wait_for_sync=wait_for_sync)

    def _apply_managed(self, spec: BuildSpec) -> ApplyResult:
        from .staging import _apply_managed
        return _apply_managed(self, spec)

    def _apply_documents(self, spec: BuildSpec) -> ApplyResult:
        from .staging import _apply_documents
        return _apply_documents(self, spec)

    def verify(self, spec: BuildSpec) -> dict[str, Any]:
        from .verify_publish import verify
        return verify(self, spec)


def _raise_incomplete() -> None:
    raise BuildError("managed synchronization is incomplete")
