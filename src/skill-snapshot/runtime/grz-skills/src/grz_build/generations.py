"""List GRZ sidecar generations on a live service and retire superseded ones behind a plan ID."""

from __future__ import annotations

from typing import Any

from grz_adapters.azure_source import get_field
from grz_adapters.sidecar_schema import load_sidecar_schema
from grz_build.reader_grants import REVOKE_ACTIONS
from grz_core.contracts import ContractError, digest
from grz_core.state import State

RETIRE_PLAN_VERSION = "grz-retire-v1"


def _sidecar_field_names() -> set[str]:
    return {field["name"] for field in load_sidecar_schema()["fields"]}


def _is_sidecar(store: Any, index: str) -> bool:
    definition = store.index_client.get_index(index)
    return {get_field(field, "name") for field in get_field(definition, "fields", [])} == _sidecar_field_names()


def _manifest_generation(store: Any, index: str) -> str | None:
    rows = list(store.publisher.search_client(index).search(
        search_text=None, filter="kind eq 'manifest'", select=["generation_id"], top=1))
    return dict(rows[0]).get("generation_id") if rows else None


def _stats(store: Any, index: str) -> dict[str, int]:
    data = store.index_stats(index)
    return {"document_count": int(data.get("documentCount") or 0), "storage_bytes": int(data.get("storageSize") or 0)}


def list_generations(store: Any, *, dataset: str, alias: str, source_index: str) -> dict[str, Any]:
    """Read-only. Only names under grz-{dataset}- (plus the named source index) are inspected."""
    prefix = f"grz-{dataset}-"
    names = sorted(name for name in store.index_client.list_index_names()
                   if name.startswith(prefix) or name == source_index)
    active = store.publisher.resolve_alias(alias)
    bound = store.publisher.aliases_by_index(names)
    rows = []
    for name in names:
        row: dict[str, Any] = {"index": name, **_stats(store, name), "aliases": bound.get(name, [])}
        if name == source_index:
            row["role"] = "source"
        elif not _is_sidecar(store, name):
            row["role"] = "unrecognized"
        else:
            row["generation_id"] = _manifest_generation(store, name)
            row["role"] = "alias-bound" if row["aliases"] else "superseded"
        rows.append(row)
    return {
        "alias": alias, "active_physical_index": active, "generations": rows,
        "retire_candidates": [row["index"] for row in rows if row["role"] == "superseded"],
    }


def plan_retire(store: Any, state: State, args: Any, index: str) -> dict[str, Any]:
    listing = list_generations(store, dataset=args.dataset, alias=args.alias, source_index=args.source_index)
    row = next((row for row in listing["generations"] if row["index"] == index), None)
    if row is None:
        raise ContractError("RETIRE_TARGET_UNKNOWN", f"No grz-{args.dataset}- generation named {index}")
    if row["role"] != "superseded":
        raise ContractError("RETIRE_TARGET_PROTECTED", f"{index} is {row['role']}; only superseded sidecar generations can be retired")
    data = {
        "version": RETIRE_PLAN_VERSION, "tenant_id": args.tenant_id, "subscription_id": args.subscription_id,
        "resource_group": args.resource_group, "search_service": args.search_service, "endpoint": store.endpoint,
        "dataset": args.dataset, "alias": args.alias, "alias_target": listing["active_physical_index"],
        "source_index": args.source_index, "index": index, "generation_id": row.get("generation_id"),
        "document_count": row["document_count"], "storage_bytes": row["storage_bytes"],
    }
    grants = getattr(store, "reader_grants", None)
    readers = grants.list(index) if grants is not None else []
    if readers:
        grants.check_can_manage(index, REVOKE_ACTIONS)
        data["reader_grants"] = [{"principal_id": r["principal_id"], "role": r["role"],
                                  "assignment_id": r["assignment_id"]} for r in readers]
    planned = {"plan_id": digest(data), **data}
    state.record(planned["plan_id"], row.get("generation_id"), "retire-plan", "planned",
                 expected={"documents": row["document_count"]})
    return planned


def _check_plan(planned: dict[str, Any], plan_id: str, args: Any, endpoint: str) -> None:
    body = {key: value for key, value in planned.items() if key != "plan_id"}
    if planned.get("version") != RETIRE_PLAN_VERSION or digest(body) != plan_id or planned.get("plan_id") != plan_id:
        raise ContractError("PLAN_ID_MISMATCH", "Retire plan file does not match --plan-id")
    bound = {"tenant_id": args.tenant_id, "subscription_id": args.subscription_id,
             "resource_group": args.resource_group, "search_service": args.search_service, "endpoint": endpoint,
             "dataset": args.dataset, "alias": args.alias, "source_index": args.source_index}
    if any(planned.get(key) != value for key, value in bound.items()):
        raise ContractError("RETIRE_BINDING_MISMATCH", "Retire plan was made for a different service, dataset, alias or source")


def retire(store: Any, state: State, args: Any, planned: dict[str, Any], plan_id: str) -> dict[str, Any]:
    """Delete one superseded generation once, then prove it is gone and the alias did not move."""
    _check_plan(planned, plan_id, args, store.endpoint)
    index = planned["index"]
    with state.publisher_lock():
        fresh = plan_retire(store, state, args, index)
        drift = [key for key in ("alias_target", "generation_id", "document_count", "reader_grants")
                 if fresh.get(key) != planned.get(key)]
        if drift:
            raise ContractError("RETIRE_PLAN_STALE", "Service changed since the retire plan: " + ", ".join(drift))
        state.record_write(plan_id, planned["generation_id"], "delete", "retire", index)
        try:
            store.index_client.delete_index(index)
        except Exception as exc:
            state.record_write(plan_id, planned["generation_id"], "delete", "retire", index,
                               status="ambiguous", error_code="RETIRE_DELETE_FAILED")
            raise ContractError("RETIRE_DELETE_FAILED", "Delete failed or outcome unknown; run generations before any retry") from exc
        exists = store.target_exists(index)
        active = store.publisher.resolve_alias(args.alias)
        if exists or active != planned["alias_target"]:
            state.record_write(plan_id, planned["generation_id"], "delete", "retire", index,
                               status="failed", error_code="RETIRE_READBACK_FAILED")
            raise ContractError("RETIRE_READBACK_FAILED", "Index still exists or the alias moved after delete")
        state.record_write(plan_id, planned["generation_id"], "delete", "retire", index, status="confirmed")
        revoked = _revoke_readers(store, state, plan_id, planned, index)
    result = {"state": "retired", "index": index, "generation_id": planned["generation_id"],
              "alias": args.alias, "active_physical_index": active, "readback": {"index_exists": False}}
    if revoked:
        result["readback"]["reader_grants_left"] = 0
        result["reader_grants_revoked"] = revoked
    return result


def _revoke_readers(store: Any, state: State, plan_id: str, planned: dict[str, Any], index: str) -> int:
    """Deleting an index leaves its role assignments behind, so remove the planned ones and re-read."""
    rows = planned.get("reader_grants") or []
    if not rows:
        return 0
    generation = planned["generation_id"]
    for row in rows:
        state.record_write(plan_id, generation, "delete", "reader-revoke", index,
                           detail={"principal_id": row["principal_id"]})
        try:
            store.reader_grants.revoke(row["assignment_id"])
        except Exception as exc:
            state.record_write(plan_id, generation, "delete", "reader-revoke", index, status="ambiguous",
                               error_code="READER_REVOKE_FAILED")
            raise ContractError("READER_REVOKE_FAILED", f"The index is gone, but removing the read grant for "
                                f"{row['principal_id']} failed or its outcome is unknown. Next step: check role "
                                f"assignments on {index} and remove any that remain; don't rerun retire.") from exc
        state.record_write(plan_id, generation, "delete", "reader-revoke", index, status="confirmed")
    left = store.reader_grants.list(index)
    if left:
        raise ContractError("RETIRE_READBACK_FAILED", f"{len(left)} reader grant(s) still exist on {index}")
    return len(rows)
