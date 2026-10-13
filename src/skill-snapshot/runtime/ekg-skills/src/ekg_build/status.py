"""Read-only, journal-backed build status; local records are not live Azure evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ekg_core.models import BuildSpec, SourceKind
from .planner import plan
from .preflight import scope


_SCOPE_KEYS = {
    "source_kind", "source_id", "source_resource_id", "manifest_digest",
    "document_count", "requested_outcome", "knowledge_source_kind", "tenant_id",
    "subscription_id", "search_resource_id", "storage_resource_id",
    "openai_resource_id", "storage_container", "staging_prefix", "search_endpoint",
    "storage_endpoint", "openai_endpoint", "ontology_schema_id",
}
_ERROR_CODES = {"SOURCE_DRIFT", "REMOTE_OUTCOME_UNVERIFIED", "BUILD_ATTEMPT_FAILED"}


def read_build_status(journal_path: str, run_id: str) -> dict[str, Any]:
    """Read a durable run by ID without constructing an Azure client."""
    if (not isinstance(journal_path, str) or not journal_path
            or not isinstance(run_id, str) or not run_id):
        raise ValueError("status requires a journal path and run ID")
    scope: dict[str, Any] = {}
    base: dict[str, Any] = {
        "phase": "build.status", "status": "unverified", "code": "JOURNAL_UNVERIFIED",
        "run_id": run_id, "plan_id": None, "scope": scope,
        "evidence": {"origin": "local_build_journal"}, "uncertainty": [
            "A local journal does not attest current remote state.",
        ],
        "counts": {}, "timings_ms": {},
        "next_action": "Inspect the journal and reconcile the exact run read-only before further writes.",
    }
    try:
        record = json.loads(Path(journal_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return base
    if not isinstance(record, dict) or record.get("run_id") != run_id:
        return base
    if record.get("version") != 2 or record.get("state") not in {
        "attempt_requested", "staging", "indexing", "synchronizing", "verified", "failed",
    } or not isinstance(record.get("scope"), dict) or not isinstance(record.get("plan_id"), str):
        return base
    scope = record["scope"]
    if (set(scope) != _SCOPE_KEYS
            or any(value is not None and not isinstance(value, (str, int))
                   or isinstance(value, bool) for value in scope.values())
            or not isinstance(scope.get("manifest_digest"), str)
            or not isinstance(scope.get("staging_prefix"), str)):
        return base
    state = record["state"]
    counts = record.get("counts")
    timings = record.get("timings_ms")
    if (not isinstance(counts, dict) or not isinstance(timings, dict)
            or any(key not in {"source", "staged", "ontology", "content", "graph"}
                   or not isinstance(value, int) or isinstance(value, bool) or value < 0
                   for key, value in counts.items())
            or any(key not in {"stage_ms", "ontology_ms", "synchronization_ms",
                               "verify_ms", "time_to_build_ms"}
                   or not isinstance(value, (float, int)) or isinstance(value, bool)
                   or value < 0 for key, value in timings.items())
            or state == "failed" and record.get("error_code") not in _ERROR_CODES):
        return base
    if state == "verified":
        receipt = record.get("create_receipt")
        if (not isinstance(record.get("create_request_hash"), str)
                or not record["create_request_hash"].startswith("sha256:")
                or not isinstance(receipt, dict)
                or set(receipt) != {"name", "kind", "etag"}
                or receipt.get("name") != record.get("knowledge_source")
                or receipt.get("kind") != "azureBlob"
                or not isinstance(receipt.get("etag"), str)
                or not receipt["etag"].strip()):
            return {
                **base, "plan_id": record["plan_id"], "scope": scope,
                "next_action": "Exact Knowledge Source create receipt is missing; do not publish or retry writes.",
            }
    synchronizing = state == "synchronizing" and isinstance(record.get("create_receipt"), dict)
    return {
        **base, "status": "verified" if state == "verified" else "unverified",
        "code": "JOURNAL_VERIFIED" if state == "verified" else
                "JOURNAL_FAILED" if state == "failed" else
                "JOURNAL_SYNCHRONIZING" if synchronizing else "JOURNAL_ATTEMPT_REQUESTED",
        "plan_id": record["plan_id"], "scope": scope,
        "evidence": {"origin": "local_build_journal", "recorded_phase": state,
                     "error_code": record["error_code"] if state == "failed" else None},
        "counts": counts, "timings_ms": timings,
        "next_action": (
            "Use the verified descriptor only after fresh read-only target and index verification."
            if state == "verified" else
            "Service-side synchronization was submitted; check `ekg-build progress`, then reconcile read-only."
            if synchronizing else
            "Reconcile the exact attempt with read-only checks; never retry its writes automatically."
        ),
    }


def build_status(spec: BuildSpec, *, run_id: str | None = None,
                 working_directory: str | None = None) -> dict[str, Any]:
    """Validate a journal against the exact plan, including legacy managed runs."""
    if run_id is not None and (not isinstance(run_id, str) or not run_id):
        raise ValueError("run_id must be a nonempty string")
    journal = Path(spec.build_journal) if spec.build_journal else None
    relative_inputs = [
        value for value in (spec.corpus_source, spec.ontology_path,
                            spec.source.reference if spec.source and spec.source.kind
                            in {SourceKind.LOCAL_PATH, SourceKind.ZIP_ARCHIVE} else None)
        if value and not Path(value).is_absolute()
    ]
    base = Path(working_directory) if working_directory else None
    scoped = base is not None and base.is_absolute() and base.resolve() == Path.cwd().resolve()
    traverses = (journal is not None and not journal.is_absolute() and base is not None
                 and not (base / journal).resolve().is_relative_to(base.resolve()))
    if ((base is not None and not base.is_absolute())
            or ((journal is not None and not journal.is_absolute() or relative_inputs)
                and not scoped) or traverses):
        return {
            "phase": "build.status", "status": "unsupported", "code": "JOURNAL_SCOPE_REQUIRED",
            "plan_id": None, "scope": {}, "evidence": {"origin": "offline_contract"},
            "uncertainty": ["Original relative Build working directory is not established."],
            "next_action": "Run status from the original Build working directory with explicit working_directory.",
        }
    desired = plan(spec)
    exact_scope = desired.scope or scope(spec, desired.route)
    if desired.route is not None and desired.route.capability != "verified_path":
        return {
            "phase": "build.status", "status": "unsupported",
            "code": desired.route.blocked_by[0].split(":", 1)[0]
                    if desired.route.blocked_by else "UNSUPPORTED_ROUTE",
            "plan_id": desired.plan_id, "scope": exact_scope,
            "evidence": {"origin": "offline_contract"},
            "uncertainty": ["No verified Build execution route exists for this source."],
            "next_action": "Review the offline plan; do not attempt writes on this route.",
        }
    if spec.ontology_mode.value == "none":
        return {
            "phase": "build.status", "status": "unsupported",
            "code": "NO_MANAGED_BUILD_JOURNAL", "plan_id": desired.plan_id,
            "scope": exact_scope, "evidence": {"origin": "offline_contract"},
            "uncertainty": ["Document-only Build has no managed attempt journal."],
            "next_action": "Verify the document index read-only with the exact BuildSpec.",
        }
    if not spec.build_journal:
        return {
            "phase": "build.status", "status": "unverified", "code": "NO_BUILD_JOURNAL",
            "plan_id": desired.plan_id, "scope": exact_scope,
            "evidence": {"origin": "offline_contract"}, "uncertainty": [],
            "next_action": "Provide an exact local build journal path.",
        }
    if spec.source_manifest is None:
        from .executor import generation, index_names
        base = {
            "phase": "build.status", "status": "unverified", "plan_id": desired.plan_id,
            "scope": exact_scope, "evidence": {"origin": "local_build_journal"},
            "uncertainty": ["A local journal does not attest current remote state."],
            "next_action": "Reconcile this exact managed attempt read-only before further writes.",
        }
        if not Path(spec.build_journal).is_file():
            return {**base, "code": "JOURNAL_UNAVAILABLE"}
        try:
            record = json.loads(Path(spec.build_journal).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {**base, "code": "JOURNAL_SCOPE_MISMATCH"}
        expected = {
            "generation": generation(spec), "knowledge_source": index_names(spec)["knowledge_source"],
            "plan_id": desired.plan_id, "search_resource_id": exact_scope.get("search_resource_id"),
            "tenant_id": spec.tenant_id, "preview_entitlement": "unverified_before_attempt",
        }
        if not isinstance(record, dict) or any(record.get(key) != value for key, value in expected.items()) \
                or set(record) != {*expected, "state"} \
                or record["state"] not in {"attempt_requested", "verified"}:
            return {**base, "code": "JOURNAL_SCOPE_MISMATCH"}
        return {**base, "code": "JOURNAL_VERIFIED" if record["state"] == "verified"
                else "JOURNAL_ATTEMPT_REQUESTED"}
    from .executor import generation
    selected_id = run_id or f"build-{generation(spec)}"
    result = read_build_status(spec.build_journal, selected_id)
    if result["plan_id"] is None:
        return {**result, "plan_id": desired.plan_id, "scope": desired.scope}
    if result["plan_id"] != desired.plan_id or result["scope"] != desired.scope:
        return {
            **result, "status": "unverified", "code": "JOURNAL_SCOPE_MISMATCH",
            "plan_id": desired.plan_id, "scope": desired.scope, "counts": {}, "timings_ms": {},
            "next_action": "Use the exact approved spec and journal for this run; do not retry writes.",
        }
    return result
