from ekg_core.models import BuildSpec, OntologyMode
from ekg_core.telemetry import TelemetryRecorder, adapter_http_stats

from .managed_pipeline import SEARCH_API_VERSION
from .preview import search_resource_id
from .executor import (
    BuildError, _advance_source_journal, _complete_journal, _merge_telemetry, _read_attempt_journal,
    _require_managed_entitlement, _source_record, _synchronization_event, generation, index_names, plan,
)

def reconcile(executor, spec: BuildSpec) -> dict:
        if spec.ontology_mode is OntologyMode.NONE:
            raise BuildError("reconciliation requires an ontology-backed managed build")
        desired = plan(spec)
        if desired.blocked_by:
            raise BuildError("; ".join(desired.blocked_by))
        if spec.source_manifest is not None:
            record, original = _read_attempt_journal(spec)
            expected = _source_record(spec, "attempt_requested")
            same_run = all(record.get(key) == expected[key] for key in (
                "version", "run_id", "plan_id", "scope", "generation",
                "knowledge_source", "preview_entitlement", "create_request_hash",
            ))
            if same_run and record.get("state") == "verified":
                verified = executor.verify(spec)
                return {**verified, "plan_id": desired.plan_id, "journal_state": "verified",
                        "already_verified": True}
            if not same_run or record.get("state") not in {
                "attempt_requested", "staging", "indexing", "synchronizing", "failed",
            }:
                raise BuildError("source journal differs from exact run or cannot be reconciled")
            recorder = TelemetryRecorder("build", adapter_http_stats(executor.adapter))
            with recorder.span("reconcile_targets"):
                executor._source_targets(spec)
            if getattr(executor.adapter, "search_api_version", SEARCH_API_VERSION) != SEARCH_API_VERSION:
                raise BuildError("managed graph requires exact preview API version")
            try:
                status = executor.adapter.knowledge_source_status(index_names(spec)["knowledge_source"])
            except Exception:  # telemetry is best-effort; verification below is authoritative
                status = {}
            if isinstance(status, dict):
                recorder.add(_synchronization_event(status.get("lastSynchronizationState") or {}))
            with recorder.span("verify"):
                verified = executor.verify(spec)
            prior = record.get("telemetry") if isinstance(record.get("telemetry"), list) else []
            _advance_source_journal(spec, original, state="verified", counts=verified["counts"],
                                    telemetry=_merge_telemetry(prior, recorder.events))
            return {**verified, "plan_id": desired.plan_id, "journal_state": "verified"}
        names = index_names(spec)
        record, original = _read_attempt_journal(spec)
        expected = {
            "generation": generation(spec),
            "knowledge_source": names["knowledge_source"],
            "plan_id": desired.plan_id,
            "search_resource_id": search_resource_id(spec),
            "tenant_id": spec.tenant_id,
            "preview_entitlement": "unverified_before_attempt",
            "state": "attempt_requested",
        }
        if record != expected:
            raise BuildError("managed build attempt journal differs from the exact plan, "
                             "generation, service identity or attempt state")
        version = getattr(executor.adapter, "search_api_version", SEARCH_API_VERSION)
        if version != SEARCH_API_VERSION:
            raise BuildError(f"managed graph requires Search {SEARCH_API_VERSION}")
        service_evidence = _require_managed_entitlement(spec, executor.adapter)
        verified = executor.verify(spec)
        _complete_journal(spec, names["knowledge_source"], original)
        return {**verified, "plan_id": desired.plan_id, "service": service_evidence,
                "journal_state": "verified"}
