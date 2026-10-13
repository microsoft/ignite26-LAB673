"""Approval-gated Build: export, cluster, upload, verify and publish one generation."""

from __future__ import annotations

import tempfile
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from grz_adapters.native_adapter import (
    NativeBuildAdapter,
    PartialCoverage,
)
from grz_build import load_snapshot
from grz_build.inputs import Snapshot
from grz_build.naming import NamingBudget, NamingResult, enrich_assigned_communities, name_communities
from grz_build.naming_azure import MAX_LABEL_CHARS, naming_contexts
from grz_build.planner import approve_plan, plan
from grz_build.readback import check_readback
from grz_build.reader_grants import missing_readers
from grz_build.sidecar_documents import (
    community_documents, documents_bytes, generation_id, hierarchy_digest, manifest_payload,
    provisional_documents_bytes, sidecar_record,
    staging_bytes_estimate,
)
from grz_consume.checks import documents_digest, normalize_document
from grz_core.adapters import BuildStore
from grz_core.contracts import (
    BuildProfile, ContractError, Descriptor, SourceIdentity, digest, validate_alias,
)
from grz_core.state import State

UPLOAD_BATCH_SIZE = 500


def _visibility_basis(planned: dict[str, Any]) -> str:
    return (planned.get("source_binding") or {}).get("visibility_basis", "per-document")


def _source_binding(store: BuildStore, inspected: dict[str, Any]) -> dict[str, Any] | None:
    binder = getattr(store, "source_binding", None)
    return binder(inspected) if callable(binder) else None


def _ambiguous_write(exc: BaseException) -> bool:
    """A timeout or 5xx may have landed server-side, so the journal must not call it failed."""
    current: BaseException | None = exc
    while current is not None:
        status = getattr(current, "status_code", getattr(getattr(current, "response", None), "status_code", None))
        if status == 408 or (isinstance(status, int) and status >= 500):
            return True
        name = type(current).__name__.lower()
        if "timeout" in name or "connection" in name:
            return True
        current = current.__cause__
    return False


def _journaled_write(state: State, plan_id: str, generation: str | None, stage: str, phase: str, target: str,
                     action: Callable[[], None], *, key_digest: str | None = None,
                     detail: dict[str, Any] | None = None) -> None:
    """Journal intent, run one write, then journal its outcome; never retry here."""
    state.record_write(plan_id, generation, stage, phase, target, key_digest=key_digest, detail=detail)
    try:
        action()
    except BaseException as exc:
        state.record_write(plan_id, generation, stage, phase, target, key_digest=key_digest,
                           status="ambiguous" if _ambiguous_write(exc) else "failed",
                           error_code=getattr(exc, "code", "WRITE_FAILED"))
        raise
    state.record_write(plan_id, generation, stage, phase, target, key_digest=key_digest, status="confirmed")


def _check_upload(results: list[dict[str, Any]], expected: int, message: str) -> None:
    if len(results) != expected or any(not result.get("succeeded") for result in results):
        raise ContractError("UPLOAD_FAILED", message)


class BuildService:
    def __init__(self, store: BuildStore, state: State, workspace: Path, *, alias: str = "grz-active",
                 native_adapter: NativeBuildAdapter | None = None):
        self.store, self.state, self.workspace = store, state, Path(workspace)
        self.alias = alias
        self.native_adapter = native_adapter or NativeBuildAdapter()
        self.workspace.mkdir(parents=True, exist_ok=True)

    def inspect(self, source: SourceIdentity) -> dict[str, Any]:
        source.validate()
        return self.store.inspect(source)

    def plan(self, source: SourceIdentity, profile: BuildProfile,
             naming_budget: NamingBudget | None = None) -> dict[str, Any]:
        inspected = self.inspect(source)
        return plan(source, profile, target_service=source.service, alias=self.alias,
                    inspected=inspected, naming_budget=naming_budget)

    def _await_ids(self, index: str, expected_ids: set[str], timeout_seconds: float = 120) -> list[dict[str, Any]]:
        # Search indexing is near-real-time: uploaded keys, and the document count, can lag the upload.
        deadline = time.monotonic() + timeout_seconds
        delay = 0.25
        while True:
            try:
                observed = self.store.readback(index)
            except ContractError as exc:
                if exc.code != "READBACK_NOT_SETTLED" or time.monotonic() >= deadline:
                    raise
                observed = None
            if observed is not None and {d["id"] for d in observed} == expected_ids and len(observed) == len(expected_ids):
                return observed
            if time.monotonic() >= deadline:
                raise ContractError("READBACK_MISMATCH", "Physical index records not visible before timeout")
            time.sleep(min(delay, max(0, deadline - time.monotonic())))
            delay = min(delay * 2, 8)

    def compute_local_sidecar(
        self,
        planned: dict[str, Any],
        plan_id: str,
        approved_budget_bytes: int,
        *,
        naming_provider: Callable[[str, float], NamingResult] | None = None,
        naming_approved: bool = False,
    ) -> tuple[Descriptor, list[dict[str, Any]], dict[str, Any], PartialCoverage]:
        """Compute the full local sidecar without publishing or uploading to an Azure output index.

        Keeps Azure output-index publication separate from local sidecar computation.
        """
        approve_plan(planned, plan_id, approved_budget_bytes)
        source = SourceIdentity(**planned["source"])
        profile = BuildProfile(**planned["profile"])
        inspected = self.inspect(source)
        binding = self._check_source_matches_plan(planned, inspected)
        timings: dict[str, int] = {}
        with tempfile.TemporaryDirectory(prefix="grz-export-", dir=self.workspace) as folder:
            snapshot = self._export_frozen(source, Path(folder), binding if binding is not None else inspected, timings)
            generation, index, documents, manifest_doc, coverage = self._build_documents(
                planned, snapshot, source, profile, approved_budget_bytes, naming_provider, naming_approved,
                scratch_dir=Path(folder),
            )
            descriptor = Descriptor(
                physical_index=index,
                generation_id=generation,
                source_service=source.service,
                source_index=source.index,
                embedding_model_id=source.embedding_model_id,
                dimension=source.dimension,
                visibility=source.visibility,
                visibility_basis=_visibility_basis(planned),
            )
            return descriptor, documents, manifest_doc, coverage

    def apply(self, planned: dict[str, Any], plan_id: str, approved_budget_bytes: int, *,
              naming_provider: Callable[[str, float], NamingResult] | None = None,
              naming_approved: bool = False, resume_after_reconcile: bool = False) -> Descriptor:
        approve_plan(planned, plan_id, approved_budget_bytes)
        if planned.get("target_index") and self.state.unresolved_writes(plan_id) and (not resume_after_reconcile or not self.state.has_reconcile(plan_id)):
            raise ContractError("RECONCILE_REQUIRED", "Run reconcile and pass --resume-after-reconcile before retrying unresolved writes")
        source = SourceIdentity(**planned["source"])
        profile = BuildProfile(**planned["profile"])
        with self.state.publisher_lock():
            before = self.inspect(source)
            binding = self._check_source_matches_plan(planned, before)
            self._check_target_index_free(planned, plan_id)
            baseline_alias = self.store.resolve_alias(planned["alias"])
            if baseline_alias is not None and not str(baseline_alias).startswith("grz-"):
                raise ContractError("ALIAS_FOREIGN", "Refusing to publish over an alias bound to a non-GRZ index")
            self.state.record(plan_id, None, "apply", "running", expected={"evidence": source.expected_count})
            timings: dict[str, int] = {}
            generation: str | None = None
            try:
                with tempfile.TemporaryDirectory(prefix="grz-export-", dir=self.workspace) as folder:
                    snapshot = self._export_frozen(source, Path(folder), binding if binding is not None else before,
                                                   timings)
                    phase_started = time.perf_counter()
                    generation, index, documents, manifest_doc, _coverage = self._build_documents(
                        planned, snapshot, source, profile, approved_budget_bytes, naming_provider, naming_approved,
                        scratch_dir=Path(folder))
                    self._upload_generation(plan_id, generation, index, documents, manifest_doc, source,
                                            (planned.get("reader_grants") or {}).get("grant", []))
                    timings["build_and_upload"] = int((time.perf_counter() - phase_started) * 1000)
                    counts = manifest_doc["payload"]["counts"]
                    return self._save_candidate(planned, plan_id, generation, index, source, baseline_alias,
                                                timings, counts)
            except (ContractError, ValueError, OSError) as exc:
                self.state.record(plan_id, generation, "apply", "failed", error_code=getattr(exc, "code", "BUILD_FAILED"))
                raise

    def _check_source_matches_plan(self, planned: dict[str, Any], inspected: dict[str, Any]) -> dict[str, Any] | None:
        binding = _source_binding(self.store, inspected)
        if binding is not None:
            if binding != planned.get("source_binding"):
                raise ContractError("SOURCE_CHANGED", "Source definition, count or vector binding changed since approved plan")
        elif digest(inspected) != planned["source_inspection_digest"]:
            raise ContractError("SOURCE_CHANGED", "Source schema or field mapping changed since approved plan")
        return binding

    def _check_target_index_free(self, planned: dict[str, Any], plan_id: str) -> None:
        target_index = planned.get("target_index")
        target_exists = getattr(self.store, "target_exists", None)
        if target_index and callable(target_exists) and target_exists(target_index) and not self.state.owns_index(plan_id, target_index):
            raise ContractError("INDEX_COLLISION", "Planned target index already exists outside this journal")

    def _export_frozen(self, source: SourceIdentity, folder: Path, pre_export: dict[str, Any],
                       timings: dict[str, int]) -> Snapshot:
        """Export, then re-inspect: any change to the source during export invalidates the snapshot."""
        started = time.perf_counter()
        manifest = self.store.export_snapshot(source, folder)
        timings["export"] = int((time.perf_counter() - started) * 1000)
        snapshot = load_snapshot(manifest)
        after_export = self.inspect(source)
        after_binding = _source_binding(self.store, after_export)
        if snapshot.source != source or (after_binding if after_binding is not None else after_export) != pre_export:
            raise ContractError("SOURCE_CHANGED", "Frozen source identity/schema/stats changed during export")
        return snapshot

    def _cluster_native(
        self,
        planned: dict[str, Any],
        snapshot: Snapshot,
        source: SourceIdentity,
        profile: BuildProfile,
        scratch_dir: Path,
    ) -> tuple[list[dict[str, Any]], PartialCoverage]:
        """Cluster vectors using the native binary orchestration adapter."""
        from grz_adapters.native_adapter import build_native_config

        native_out = scratch_dir / "native-output"
        native_out.mkdir(parents=True, exist_ok=True)
        config = build_native_config(
            endpoint=getattr(self.store, "endpoint", f"https://{source.service}.search.windows.net"),
            source_index=source.index,
            vector_field=planned.get("source", {}).get("vector_field") or "vector",
            output_directory=native_out,
            auth_mode=planned.get("auth_mode", "defaultAzureCredential"),
            tenant_id=getattr(self.store, "tenant_id", None),
        )
        hierarchy, coverage, _cli_res = self.native_adapter.build_from_config(config, dimension=source.dimension)
        return hierarchy, coverage

    def _build_documents(self, planned: dict[str, Any], snapshot: Snapshot, source: SourceIdentity,
                         profile: BuildProfile, approved_budget_bytes: int,
                         naming_provider: Callable[[str, float], NamingResult] | None,
                         naming_approved: bool,
                         scratch_dir: Path | None = None) -> tuple[str, str, list[dict[str, Any]], dict[str, Any], PartialCoverage]:
        scratch = scratch_dir or self.workspace
        centroids, coverage = self._cluster_native(planned, snapshot, source, profile, scratch)
        staging_bytes = staging_bytes_estimate(snapshot, centroids, source.dimension)
        if staging_bytes > profile.memory_budget_bytes:
            raise ContractError("MEMORY_BUDGET_EXCEEDED", "Predicted sidecar document staging exceeds configured memory")
        budget_spec = planned.get("naming_budget")
        if budget_spec is not None and naming_provider is None:
            raise ContractError("NAMING_PROVIDER_REQUIRED", "Approved naming plan needs an injected provider")
        if budget_spec is not None:
            # Stop before any model spend: naming can't shrink the documents below this bound.
            bound = provisional_documents_bytes(centroids, snapshot, source, MAX_LABEL_CHARS)
            if bound > approved_budget_bytes:
                raise ContractError("BUDGET_APPROVAL_REQUIRED",
                                    f"Documents could reach {bound} bytes, over the approved {approved_budget_bytes}; "
                                    "no model calls or index writes were made")
        local_keys = [f"{level}:{local}" for level, communities in enumerate(centroids) for local in sorted(communities)]
        contexts, reserve_tokens, reserve_spend = None, 0, 0.0
        model = planned.get("naming_model")
        if model is not None and naming_provider is not None:
            contexts = naming_contexts(snapshot, centroids, members_per_prompt=model["members_per_prompt"],
                                       excerpt_chars=model["excerpt_chars"])
            local_keys = list(contexts)
            # Roughly 4 characters per token, plus the system prompt, rounded up.
            reserve_tokens = max(len(c) for c in contexts.values()) // 3 + 200 + model["max_output_tokens"]
            reserve_spend = reserve_tokens * max(model["input_price_per_1m"], model["output_price_per_1m"]) / 1_000_000
        labels = enrich_assigned_communities(local_keys, naming_provider, NamingBudget(**budget_spec) if budget_spec else None,
                                             approved=naming_approved, contexts=contexts, reserve_tokens=reserve_tokens,
                                             reserve_spend=reserve_spend)
        hierarchy = hierarchy_digest(centroids)
        generation = generation_id(snapshot, profile, hierarchy, labels)
        index = planned.get("target_index") or self.store.generation_index_name(generation)
        documents = community_documents(generation, centroids, labels, snapshot, source)
        actual = documents_bytes(documents)
        if actual > approved_budget_bytes:
            raise ContractError("BUDGET_APPROVAL_REQUIRED",
                                f"Documents are {actual} bytes, over the approved {approved_budget_bytes}; no index writes were made")
        payload = manifest_payload(
            generation=generation, index=index, source=source, documents=documents, snapshot=snapshot,
            hierarchy=hierarchy, labels=labels, graph_edges=coverage.observed_node_count, levels=len(centroids),
            staging_bytes=staging_bytes, visibility_basis=_visibility_basis(planned),
            partial_coverage=asdict(coverage))
        return generation, index, documents, sidecar_record(generation, "manifest", "reserved-manifest", payload=payload), coverage

    def _upload_generation(self, plan_id: str, generation: str, index: str, documents: list[dict[str, Any]],
                           manifest_doc: dict[str, Any], source: SourceIdentity,
                           readers: list[dict[str, Any]] = ()) -> None:
        """Create the index, grant planned readers, upload community/evidence docs, then add the manifest."""
        present = self._existing_or_new_index(plan_id, generation, index, [*documents, manifest_doc], source)
        self._grant_readers(plan_id, generation, index, readers)
        for start in range(0, len(documents), UPLOAD_BATCH_SIZE):
            batch = [d for d in documents[start:start + UPLOAD_BATCH_SIZE] if d["id"] not in present]
            if batch:
                _journaled_write(
                    self.state, plan_id, generation, "apply", "upload-batch", index,
                    lambda batch=batch: _check_upload(self.store.upload_batch(index, batch), len(batch),
                                                      "Unresolved partial document upload"),
                    key_digest=digest([d["id"] for d in batch]), detail={"count": len(batch)})
        manifest_present = manifest_doc["id"] in present
        visible = self._await_ids(index, {d["id"] for d in documents} | ({manifest_doc["id"]} if manifest_present else set()))
        uploaded = [d for d in visible if d["kind"] != "manifest"]
        if len(uploaded) != len(documents) or documents_digest(uploaded) != manifest_doc["payload"]["documents_digest"]:
            raise ContractError("READBACK_MISMATCH", "Uploaded records not visible or not identical")
        if not manifest_present:
            _journaled_write(
                self.state, plan_id, generation, "apply", "manifest-upload", index,
                lambda: _check_upload(self.store.upload_batch(index, [manifest_doc]), 1, "Manifest upload failed"),
                key_digest=digest([manifest_doc["id"]]))
        self._await_ids(index, {d["id"] for d in [*documents, manifest_doc]})
        self.verify(generation, index, source)

    def _grant_readers(self, plan_id: str, generation: str, index: str, readers: list[dict[str, Any]]) -> None:
        """Index-scoped reader roles don't follow the alias, so each planned reader is granted per generation."""
        if not readers:
            return
        grants = getattr(self.store, "reader_grants", None)
        if grants is None:
            raise ContractError("READER_GRANTS_UNSUPPORTED", "This backend can't grant readers; re-plan without readers")
        for wanted in readers:
            _journaled_write(self.state, plan_id, generation, "apply", "reader-grant", index,
                             lambda wanted=wanted: grants.grant(index, wanted),
                             key_digest=digest([wanted["principal_id"], wanted["role_definition_id"]]),
                             detail={"principal_id": wanted["principal_id"], "role": wanted["role"]})

    def _check_readers_follow(self, record: dict[str, Any], current: str | None, new_index: str) -> None:
        """Refuse cutover while anyone reading the published index can't read the new one."""
        grants = getattr(self.store, "reader_grants", None)
        if grants is None or not current or current == new_index:
            return
        dropped = (record.get("reader_grants") or {}).get("dropped", [])
        missing = missing_readers(grants.list(current), grants.list(new_index), dropped)
        if missing:
            raise ContractError("READERS_MISSING", f"{len(missing)} reader(s) can't read {new_index} yet: "
                                f"{', '.join(missing)}. Next step: run apply again with the same plan, or re-plan "
                                "with --drop-reader for each one you mean to remove.")

    def _existing_or_new_index(self, plan_id: str, generation: str, index: str,
                               expected: list[dict[str, Any]], source: SourceIdentity) -> set[str]:
        """Resume only missing immutable keys; reject changed content or index-name collisions."""
        expected_by_id = {d["id"]: d for d in expected}
        try:
            existing = self.store.readback(index)
        except ContractError as exc:
            if exc.code != "INDEX_MISSING":
                raise
            _journaled_write(self.state, plan_id, generation, "apply", "create-index", index,
                             lambda: self.store.create_generation_index(index, source.dimension))
            return set()
        if any(d["generation_id"] != generation for d in existing):
            raise ContractError("INDEX_COLLISION", "Truncated index-name digest collision")
        if len({d["id"] for d in existing}) != len(existing):
            raise ContractError("READBACK_MISMATCH", "Duplicate keys in generation index")
        if any(d["id"] not in expected_by_id or normalize_document(d) != normalize_document(expected_by_id[d["id"]])
               for d in existing):
            raise ContractError("REPRODUCIBILITY_DEVIATION", "Existing generation output differs")
        return {d["id"] for d in existing}

    def _save_candidate(self, planned: dict[str, Any], plan_id: str, generation: str, index: str,
                        source: SourceIdentity, baseline_alias: str | None, timings: dict[str, int],
                        counts: dict[str, int]) -> Descriptor:
        descriptor = Descriptor(index, generation, source.service, source.index,
                                source.embedding_model_id, source.dimension,
                                visibility_basis=_visibility_basis(planned))
        built_at = datetime.now(timezone.utc).isoformat()
        candidate = {
            "descriptor": descriptor.to_dict(),
            "expected_alias": baseline_alias, "alias": planned["alias"], "plan_id": plan_id,
            "status": "verified", "source": asdict(source), "source_binding": planned.get("source_binding"),
            "alias_binding": planned.get("alias_binding"), "timings_ms": timings, "built_at": built_at,
        }
        if planned.get("reader_grants"):
            candidate["reader_grants"] = planned["reader_grants"]
        try:
            previous = self.state.generation(generation)
        except ContractError as exc:
            if exc.code != "GENERATION_UNKNOWN":
                raise
            self.state.save_generation(generation, candidate)
        else:
            if (previous["descriptor"] != candidate["descriptor"] or previous["plan_id"] != plan_id
                    or previous["source"] != candidate["source"]):
                raise ContractError("GENERATION_CHANGED", "Saved generation approval/identity differs")
        self.state.record(plan_id, generation, "apply", "verified", expected=counts, observed=counts, evidence_ids=[index])
        self.state.record_write(plan_id, generation, "apply", "built-at", index, status="confirmed", detail={"built_at": built_at})
        return descriptor
    def verify(self, generation: str, index: str, source: SourceIdentity) -> dict[str, int]:
        started = time.perf_counter()
        documents = self.store.readback(index)
        counts = check_readback(documents, generation, source)
        self.store.verify(index, documents)
        probe = getattr(self.store, "compatibility_probe", None)
        if callable(probe):
            representatives = [doc for doc in documents if doc.get("kind") == "representative"]
            probe(index, generation, representatives, 5)
        try:
            record = self.state.generation(generation)
            operation_id = record.get("plan_id", generation)
        except ContractError:
            operation_id = generation
        self.state.record(operation_id, generation, "verify", "verified", expected=counts, observed=counts, evidence_ids=[index])
        self.state.record_write(operation_id, generation, "verify", "readback", index, status="confirmed", detail={"timings_ms": {"verify": int((time.perf_counter() - started) * 1000)}})
        return counts

    def publish(self, generation: str, *, approved: bool = False) -> Descriptor:
        if not approved:
            raise ContractError("PUBLISH_APPROVAL_REQUIRED", "Alias cutover requires separate approval")
        with self.state.publisher_lock():
            record = self.state.generation(generation)
            descriptor = Descriptor(**record["descriptor"])
            source = SourceIdentity(**record["source"]) if "source" in record else None
            if source is None:
                raise ContractError("SOURCE_IDENTITY_MISSING", "Cannot verify physical index without saved source contract")
            if not any(e.get("generation_id") == generation and e.get("stage") == "verify" and e.get("state") == "verified" for e in self.state.events()):
                raise ContractError("PUBLICATION_VERIFY_REQUIRED", "Verify must be journaled before alias cutover")
            self.verify(generation, descriptor.physical_index, source)
            expected = record["expected_alias"]
            current = self.store.resolve_alias(record["alias"])
            if record["status"] == "published" and current == descriptor.physical_index:
                return descriptor
            validate_alias(record["alias"])
            if current is not None and not str(current).startswith("grz-"):
                raise ContractError("ALIAS_FOREIGN", "Serving alias points at a non-GRZ index")
            if current != expected:
                raise ContractError("ALIAS_CHANGED", "Another publisher changed serving index")
            self._check_readers_follow(record, current, descriptor.physical_index)
            _journaled_write(self.state, record["plan_id"], generation, "publish", "alias-cutover",
                             descriptor.physical_index,
                             lambda: self.store.switch_alias(record["alias"], expected, descriptor.physical_index))
            if self.store.resolve_alias(record["alias"]) != descriptor.physical_index:
                if expected:
                    self.store.switch_alias(record["alias"], descriptor.physical_index, expected)
                raise ContractError("ALIAS_VERIFY_FAILED", "Cutover not confirmed; inspect current alias")
            record["status"] = "published"
            self.state.save_generation(generation, record)
            self.state.record(record["plan_id"], generation, "publish", "published",
                              evidence_ids=[descriptor.physical_index])
            return descriptor

    def status(self, alias: str = "grz-active") -> dict[str, Any]:
        events = self.state.events()
        latest = {event["generation_id"]: event for event in events if event["generation_id"]}
        incomplete = [generation for generation, event in latest.items() if event["state"] == "failed"]
        return {"alias": alias, "active_physical_index": self.store.resolve_alias(alias),
                "incomplete_generations": incomplete, "events": events, "writes": self.state.write_events(),
                "recovery": "Retry the same approved plan for missing immutable keys; inspect failed indexes; never delete automatically"}

    def reconcile(self, planned: dict[str, Any]) -> dict[str, Any]:
        plan_id = planned["plan_id"]
        target = planned.get("target_index")
        if not target:
            raise ContractError("RECONCILE_UNSUPPORTED", "Reconcile requires a planned target index")
        try:
            docs = self.store.readback(target)
        except ContractError as exc:
            if exc.code == "INDEX_MISSING":
                docs = []
            else:
                raise
        present = sorted(doc.get("id") for doc in docs if isinstance(doc, dict) and doc.get("id"))
        intents = [e for e in self.state.write_events() if e.get("plan_id") == plan_id and e.get("status") == "intent"
                   and e.get("phase") in {"upload-batch", "manifest-upload"}]
        intended_count = sum(int((e.get("detail") or {}).get("count", 1)) for e in intents)
        summary = {"target_index": target, "target_exists": bool(docs),
                   "intended_count": intended_count, "present_count": len(present),
                   "missing_count": max(intended_count - len(present), 0),
                   "present_digest": digest(present),
                   "unresolved": self.state.unresolved_writes(plan_id)}
        self.state.record_write(plan_id, None, "reconcile", "readback", target, status="reconciled", detail=summary)
        return summary
