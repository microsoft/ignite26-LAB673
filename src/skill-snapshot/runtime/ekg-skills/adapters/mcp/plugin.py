"""Offline agent-facing contract and scoped journal views."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from dataclasses import fields
from pathlib import Path
from typing import Any, Iterator

from ekg_build.planner import plan
from ekg_build.preflight import preflight, scope
from ekg_build.status import build_status
from ekg_core.models import (
    BuildSpec, KnowledgeSourceKind, ManifestItem, OntologyMode, RequestedOutcome,
    SourceKind, SourceLocator, SourceManifest, Target, manifest_item_from_json,
)


def _object(value: Any, cls: type, *, required: tuple[str, ...] = ()) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - {item.name for item in fields(cls)}:
        raise ValueError("Invalid contract fields")
    if any(key not in value for key in required):
        raise ValueError("Missing contract fields")
    return value


def _read(path: Any) -> Any:
    if not isinstance(path, str) or not path or not Path(path).is_absolute():
        raise ValueError("An absolute JSON file path is required")
    file = Path(path)
    try:
        if file.stat().st_size > 1024 * 1024:
            raise ValueError("JSON file exceeds 1 MiB")
        return json.loads(file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("JSON file must be readable and valid") from error


def _source(value: Any) -> SourceLocator:
    data = _object(value, SourceLocator, required=("kind", "reference"))
    return SourceLocator(**{**data, "kind": SourceKind(data["kind"])})


def _spec(path: Any) -> BuildSpec:
    data = _object(_read(path), BuildSpec, required=("target", "corpus_source"))
    target = Target(**_object(data["target"], Target))
    source = _source(data["source"]) if data.get("source") is not None else None
    manifest = None
    if data.get("source_manifest") is not None:
        raw = _object(data["source_manifest"], SourceManifest,
                      required=("version", "source", "observed_at", "items"))
        if not isinstance(raw["items"], list) or len(raw["items"]) > 10000:
            raise ValueError("Invalid manifest items")
        manifest = SourceManifest(
            version=raw["version"], source=_source(raw["source"]),
            observed_at=raw["observed_at"],
            items=tuple(manifest_item_from_json(_object(item, ManifestItem))
                        for item in raw["items"]),
            transform_config_id=raw.get("transform_config_id", "identity"),
        )
    return BuildSpec(**{
        **data, "target": target, "source": source, "source_manifest": manifest,
        "ontology_mode": OntologyMode(data.get("ontology_mode", "none")),
        "requested_outcome": (RequestedOutcome(data["requested_outcome"])
                              if data.get("requested_outcome") is not None else None),
        "knowledge_source_kind": (KnowledgeSourceKind(data["knowledge_source_kind"])
                                  if data.get("knowledge_source_kind") is not None else None),
    })


def _ax(phase: str, status: str, code: str, plan_id: str | None,
        exact_scope: dict[str, Any], evidence: dict[str, Any],
        uncertainty: list[str], next_action: str, **extra: Any) -> dict[str, Any]:
    return {
        "phase": phase, "status": status, "code": code, "plan_id": plan_id,
        "scope": exact_scope, "evidence": evidence, "uncertainty": uncertainty,
        "next_action": next_action, **extra,
    }


def _connect(arguments: dict[str, Any]) -> dict[str, Any]:
    """Live read-only connect; returns the report and writes nothing, not even a journal."""
    from ekg_provision.connect import ConnectSpec, connect, public_payload

    ints = {"embedding_dimensions", "documents"}
    for key, value in arguments.items():
        if value is not None and (not isinstance(value, int) or isinstance(value, bool)
                                  if key in ints else not isinstance(value, str)):
            raise ValueError(f"{key} has an invalid type")
    spec = ConnectSpec(**arguments)
    try:
        return public_payload(connect(spec))
    except RuntimeError as error:
        return _ax("provision.connect", "blocked", "CONNECT_READ_FAILED", None,
                   {"tenant_id": spec.tenant_id, "subscription_id": spec.subscription_id},
                   {"origin": "none", "writes": 0}, [str(error)],
                   "Confirm the tenant, sign in with az to it, then retry.")


def _generations(arguments: dict[str, Any]) -> dict[str, Any]:
    """Live read-only listing of EKG generations and which descriptors protect them."""
    from ekg_build.adapters import AzureDataPlane
    from ekg_build.generations import list_generations
    from ekg_build.managed_pipeline import SEARCH_API_VERSION
    from ekg_core import az_identity

    endpoint, tenant = arguments.get("search_endpoint"), arguments.get("tenant_id")
    paths = arguments.get("descriptor_paths", [])
    if not isinstance(endpoint, str) or not isinstance(tenant, str):
        raise ValueError("search_endpoint and tenant_id are required strings")
    if not isinstance(paths, list) or any(
            not isinstance(path, str) or not Path(path).is_absolute() for path in paths):
        raise ValueError("descriptor_paths must be absolute paths")
    adapter = AzureDataPlane(search_endpoint=endpoint, search_api_version=SEARCH_API_VERSION,
                             credential=az_identity.cli_credential(tenant))
    try:
        token = adapter.credential.get_token("https://search.azure.com/.default").token
        if not az_identity.token_in_tenant(token, tenant):
            raise ValueError("the signed-in Search credential is not in tenant_id")
        return list_generations(adapter, tuple(paths))
    except RuntimeError as error:
        return _ax("build.generations", "blocked", "GENERATIONS_READ_FAILED", None,
                   {"tenant_id": tenant, "search_endpoint": endpoint},
                   {"origin": "none", "writes": 0}, [str(error)],
                   "Confirm the tenant and Search reader access, then retry.")


@contextmanager
def _working_directory(directory: Path) -> Iterator[None]:
    original = Path.cwd()
    if directory != original:
        os.chdir(directory)
    try:
        yield
    finally:
        if directory != original:
            os.chdir(original)


def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "ekg_ks_capabilities":
        return _ax("capabilities", "unverified", "OFFLINE_CAPABILITIES", None, {},
                   {"source_contract_version": "1",
                    "knowledge_sources": {
                        "azure_blob": "legacy and approved explicit-source graph paths; exact service unverified",
                        "file": "graph route unsupported",
                        "sharepoint": "graph route unsupported",
                    },
                    "kb_handoff": "unsupported",
                    "grounding": "preview, unverified: optional validate-only grounding_index "
                                 "(existing edgeList index); never created",
                    "source_inventory": "read-only adapters available; no source observed by this tool",
                    "azure_observations": "none"},
                   ["Preview entitlement, target access and source contents are unverified"],
                   "Provide an exact BuildSpec and run read-only ekg_build_plan.")
    if name == "ekg_build_telemetry":
        from ekg_build.telemetry import build_telemetry
        paths = {key: arguments.get(key) for key in ("journal_path", "consume_log_path")}
        for value in paths.values():
            if value is not None and (not isinstance(value, str) or not Path(value).is_absolute()):
                raise ValueError("telemetry paths must be absolute")
        run_id = arguments.get("run_id")
        if run_id is not None and not isinstance(run_id, str):
            raise ValueError("run_id must be a string")
        return build_telemetry(paths["journal_path"], run_id,
                               consume_log=paths["consume_log_path"])
    if name == "ekg_provision_connect":
        return _connect(arguments)
    if name == "ekg_build_generations":
        return _generations(arguments)
    spec = _spec(arguments["spec_path"])
    if name == "ekg_build_status":
        return _build_status(name, arguments, spec)
    capacity = arguments.get("chat_capacity_k_tpm")
    if capacity is not None and (
        name != "ekg_build_plan" or not isinstance(capacity, int) or isinstance(capacity, bool)
        or capacity < 1
    ):
        raise ValueError("chat_capacity_k_tpm must be a positive integer for ekg_build_plan")
    return _call_with_spec(name, spec, chat_capacity_k_tpm=capacity)


def _build_status(name: str, arguments: dict[str, Any], spec: BuildSpec) -> dict[str, Any]:
    relative_input = (
        spec.build_journal and not Path(spec.build_journal).is_absolute()
        or spec.corpus_source and not Path(spec.corpus_source).is_absolute()
        or spec.ontology_path and not Path(spec.ontology_path).is_absolute()
        or spec.source and spec.source.kind in {
            SourceKind.LOCAL_PATH, SourceKind.ZIP_ARCHIVE,
        } and not Path(spec.source.reference).is_absolute()
    )
    explicit_directory = arguments.get("working_directory")
    if explicit_directory is not None:
        if (not isinstance(explicit_directory, str)
                or not Path(explicit_directory).is_absolute()
                or not Path(explicit_directory).is_dir()):
            raise ValueError("working_directory must be an existing absolute directory")
        directory = Path(explicit_directory).resolve()
    else:
        directory = Path.cwd().resolve()
    if relative_input and not Path(arguments["spec_path"]).resolve().is_relative_to(directory):
        return _ax("build.status", "unverified", "JOURNAL_WORKSPACE_REQUIRED",
                   None, {}, {"origin": "offline_contract"},
                   ["Original Build working directory is not established"],
                   "Supply the absolute original Build working_directory; do not retry Build.")
    if spec.build_journal and not Path(spec.build_journal).is_absolute():
        journal_path = (directory / spec.build_journal).resolve()
        if not journal_path.is_relative_to(directory):
            return _ax("build.status", "unverified", "JOURNAL_SCOPE_MISMATCH",
                       None, {}, {"origin": "offline_contract"},
                       ["Relative journal path escapes the selected Build workspace"],
                       "Supply the original journal as an absolute path; do not retry Build.")
    with _working_directory(directory):
        return _call_with_spec(name, spec, working_directory=str(directory),
                               run_id=arguments.get("run_id"))


def _estimates(spec: BuildSpec, desired: Any, capacity: int | None) -> dict[str, Any]:
    if not desired.estimates or capacity is None:
        return dict(desired.estimates)
    from ekg_build.estimates import extraction_estimate
    return {"extraction": extraction_estimate(
        spec, desired.estimates["extraction"]["documents"], chat_capacity_k_tpm=capacity,
    )}


def _call_with_spec(name: str, spec: BuildSpec, *,
                    working_directory: str | None = None,
                    run_id: str | None = None,
                    chat_capacity_k_tpm: int | None = None) -> dict[str, Any]:
    if name == "ekg_build_status":
        return build_status(spec, run_id=run_id, working_directory=working_directory)
    desired = plan(spec)
    exact_scope = desired.scope or scope(spec, None)
    if name == "ekg_source_inspect":
        return _ax("source.inspect", "unverified" if spec.source_manifest else "unsupported",
                   "SOURCE_MANIFEST_DECLARED" if spec.source_manifest else "SOURCE_ADAPTER_NOT_INTEGRATED",
                   desired.plan_id, exact_scope,
                   {"origin": "offline_contract", "inventory_observed": False,
                    "source_contract_version": "1",
                    "grounding_index_declared": spec.grounding_index is not None},
                   ["No source contents, ACLs or versions have been observed"],
                   "Re-inventory the source with its read-only adapter before approved writes."
                   if spec.source_manifest else
                   "Inventory the source with its read-only adapter before approval.")
    if name == "ekg_build_plan":
        result = preflight(spec)
        event = result.events[0]
        return _ax(
            "build.plan", result.status, result.code, desired.plan_id, exact_scope,
            {"origin": event.data["evidence"]["origin"],
             "capability": event.data["evidence"]["capability"],
             "observations": {key: value for key, value in event.data["evidence"].items()
                              if key not in {"origin", "capability"}}},
            list(event.data["uncertainty"]), result.next_action,
            blocked_by=list(event.data["blockers"]),
            plan={"id": desired.plan_id,
                  "operations": [
                 {"id": op.id, "plane": op.plane, "action": op.action,
                  "resource": op.resource, "risk": op.risk,
                  "requires_approval": op.requires_approval} for op in desired.operations
                  ],
                  "required_permissions": list(desired.required_permissions),
                  "warnings": list(desired.warnings),
                  "estimates": _estimates(spec, desired, chat_capacity_k_tpm),
                  **({"grounding": {**desired.grounding, "validated": False,
                                    "profile_kind": None}}
                     if desired.grounding else
                     {"grounding": {"index": spec.grounding_index, "validated": False,
                                    "profile_kind": None}}
                     if spec.grounding_index else {})},
            route=desired.to_dict()["route"],
        )
    raise ValueError("Unknown EKG tool")
