"""List EKG build generations on a Search service and retire unbound ones.

A generation is the 16-hex suffix Build gives every resource it creates. Retire
only deletes generations that no supplied deployment descriptor references,
using ETag-conditional deletes so anything that changed after review is kept.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from ekg_core.descriptors import descriptor_file
from ekg_core.execution import ApprovalRequired
from ekg_core.models import SourceKind, SourceLocator, stable_id
from ekg_core.telemetry import TelemetryRecorder

# Knowledge Source first so its indexer stops before the resources it uses go away;
# the ontology index last because the graph extraction definition points at it.
DELETE_ORDER = ("knowledgesources", "indexers", "skillsets", "datasources", "indexes")
_NAME = re.compile(r"^ekg-(?:managed|ontology|content)-(?P<generation>[0-9a-f]{16})(?:-|$)")
_DESCRIPTOR_KEYS = ("knowledge_source", "content_index", "graph_index")
# Live, a deleted Knowledge Source's generated resources were gone within seconds.
REMOVAL_POLLS = 24
REMOVAL_DELAY_SECONDS = 5.0


class GenerationStore(Protocol):
    def list_resources(self, kind: str) -> list[dict[str, Any]]: ...
    def delete_resource(self, kind: str, name: str, etag: str) -> bool: ...
    def resource_exists(self, kind: str, name: str) -> bool: ...
    def service_statistics(self) -> dict[str, Any]: ...
    def delete_blob(self, container: str, name: str, *, etag: str | None = None,
                    endpoint: str | None = None) -> None: ...


class RetireError(RuntimeError):
    pass


@dataclass(frozen=True)
class StagedStorage:
    """Where Build staged source blobs; the Knowledge Source redacts its connection string."""
    reader: Any
    endpoint: str
    resource_id: str

    def listing(self, container: str, prefix: str) -> list[Any]:
        locator = SourceLocator(SourceKind.BLOB_PREFIX, self.endpoint.rstrip("/"),
                                resource_id=self.resource_id, container=container,
                                prefix=prefix)
        blobs, marker = [], None
        while True:
            page = self.reader.list_blobs(locator, marker, 5000)
            blobs += page.blobs
            marker = page.next_marker
            if not marker:
                return blobs


@dataclass(frozen=True)
class IndexGrants:
    """Where to find role assignments made on single indexes; ARM, not Search, owns them."""
    arm: Any
    search_resource_id: str
    tenant_id: str

    def operations(self, generation: str, index: str) -> list[dict[str, Any]]:
        from . import readers
        at = readers.scope(self.search_resource_id, index)
        ops = []
        for item in readers.assignments(self.arm, at, self.tenant_id):
            props = item.get("properties") or {}
            role = str(props.get("roleDefinitionId", "")).rsplit("/", 1)[-1].lower()
            ops.append({"generation": generation, "kind": "roleassignments", "name": item["id"],
                        "action": "delete", "index": index,
                        "principal": f"{props.get('principalId')}:{props.get('principalType')}",
                        "role": readers.ROLE_NAME if role == readers.READER_ROLE else role})
        return ops

    def delete(self, op: dict[str, Any]) -> None:
        from . import readers
        self.arm.arm_write("DELETE", op["name"], readers.ARM_API_VERSION,
                           tenant_id=self.tenant_id)
        if self.arm.arm_read(op["name"], readers.ARM_API_VERSION, tenant_id=self.tenant_id):
            raise RetireError(f"role assignment on {op['index']} still exists after delete")


def _generation_of(name: str) -> str | None:
    match = _NAME.match(name)
    return match["generation"] if match else None


def _descriptor_bindings(paths: tuple[str, ...]) -> dict[str, list[str]]:
    """Generation -> build IDs of the descriptors that reference it."""
    bound: dict[str, list[str]] = {}
    for path in paths:
        try:
            payload = json.loads(descriptor_file(path).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            raise ValueError(f"descriptor is not readable JSON: {path}") from error
        endpoints = payload.get("endpoints") if isinstance(payload, dict) else None
        if not isinstance(endpoints, dict):
            raise ValueError(f"descriptor has no endpoints: {path}")
        generations = {_generation_of(str(endpoints.get(key) or "")) for key in _DESCRIPTOR_KEYS}
        generations.discard(None)
        if not generations:
            raise ValueError(f"descriptor references no EKG generation: {path}")
        for generation in generations:
            bound.setdefault(generation, []).append(str(payload.get("build_id")))
    return bound


def list_generations(store: GenerationStore, descriptors: tuple[str, ...] = ()) -> dict[str, Any]:
    bound = _descriptor_bindings(descriptors)
    groups: dict[str, dict[str, list[dict[str, str]]]] = {}
    kb_sources: set[str] = set()
    for kind in DELETE_ORDER:
        for item in store.list_resources(kind):
            name = item.get("name")
            generation = _generation_of(name) if isinstance(name, str) else None
            if generation is None:
                continue
            entry = {"name": name, "etag": str(item.get("@odata.etag") or "")}
            if kind == "knowledgesources":
                blob = item.get("azureBlobParameters") or {}
                created = blob.get("createdResources") or {}
                entry["created"] = sorted(v for v in created.values() if isinstance(v, str))
                # Build stages under <container>/<generation>/ (trials under
                # trial/<generation>/); anything else isn't ours to delete.
                folder = blob.get("folderPath")
                if folder in (generation, f"trial/{generation}") and blob.get("containerName"):
                    entry["staged"] = {"container": blob["containerName"],
                                       "prefix": f"{folder}/"}
                    entry["trial"] = folder != generation
            groups.setdefault(generation, {}).setdefault(kind, []).append(entry)
    for base in store.list_resources("knowledgebases"):
        for source in base.get("knowledgeSources") or ():
            if isinstance(source, dict) and isinstance(source.get("name"), str):
                kb_sources.add(source["name"])
    generations = []
    for generation in sorted(groups):
        resources = {kind: sorted(items, key=lambda item: item["name"])
                     for kind, items in groups[generation].items()}
        in_kb = sorted(item["name"] for item in resources.get("knowledgesources", ())
                       if item["name"] in kb_sources)
        generations.append({
            "generation": generation,
            "bound_by": sorted(bound.get(generation, [])),
            "knowledge_bases_reference": in_kb,
            "retirable": not bound.get(generation) and not in_kb,
            "trial": any(item.get("trial") for item in resources.get("knowledgesources", ())),
            "resources": resources,
            "index_count": len(resources.get("indexes", ())),
        })
    counters = (store.service_statistics() or {}).get("counters") or {}
    retirable = [item["generation"] for item in generations if item["retirable"]]
    return {
        "summary": (f"{len(generations)} EKG generation(s); "
                    f"{_slots(counters.get('indexesCount'))} index slots used; "
                    f"{len(retirable)} can be retired."),
        "next_step": ("Pass --descriptor for every serving descriptor so it is protected."
                      if not descriptors else
                      "Review `ekg-build plan-retire` with --generation "
                      + " --generation ".join(retirable) if retirable else "Nothing to retire."),
        "indexes": counters.get("indexesCount"),
        "descriptors_checked": len(descriptors),
        "unbound_descriptor_generations": sorted(set(bound) - set(groups)),
        "generations": generations,
    }


def _operation(generation: str, kind: str, resource: dict[str, Any],
               owned: set[str]) -> dict[str, Any]:
    # The service refuses direct deletes of Knowledge Source created resources and
    # removes them itself once the Knowledge Source is deleted, so retire only waits.
    action = "await_removal" if resource["name"] in owned else "delete"
    return {"generation": generation, "kind": kind, "name": resource["name"],
            "etag": resource["etag"], "action": action}


def _blob_operations(storage: StagedStorage | None, generation: str,
                     item: dict[str, Any]) -> list[dict[str, Any]]:
    if storage is None:
        return []
    return [{"generation": generation, "kind": "blobs", "name": blob.name, "etag": blob.etag,
             "action": "delete", "container": staged["container"],
             **({"prefix": staged["prefix"]} if staged["prefix"] != f"{generation}/" else {})}
            for source in item["resources"].get("knowledgesources", ())
            if (staged := source.get("staged"))
            for blob in storage.listing(staged["container"], staged["prefix"])]


def _slots(value: Any) -> str:
    value = value or {}
    return f"{value.get('usage', '?')}/{value.get('quota', '?')}"


def retire_plan(store: GenerationStore, generations: tuple[str, ...], *,
                descriptors: tuple[str, ...], search_endpoint: str,
                storage: StagedStorage | None = None,
                grants: IndexGrants | None = None) -> dict[str, Any]:
    """Read-only: the exact ETag-conditional deletes that retire would issue."""
    listing = list_generations(store, descriptors)
    by_id = {item["generation"]: item for item in listing["generations"]}
    blockers = []
    # A trial is never published, so no descriptor can bind it.
    trials_only = bool(generations) and all(
        by_id.get(generation, {}).get("trial") for generation in generations)
    if not descriptors and not trials_only:
        blockers.append("pass --descriptor for every serving descriptor; without one "
                        "nothing is protected")
    operations = []
    for generation in dict.fromkeys(generations):
        item = by_id.get(generation)
        if item is None:
            blockers.append(f"{generation}: no EKG resources with this generation")
            continue
        if item["bound_by"]:
            blockers.append(f"{generation}: referenced by descriptor {', '.join(item['bound_by'])}")
        if item["knowledge_bases_reference"]:
            blockers.append(f"{generation}: Knowledge Source is used by a knowledge base")
        owned = {name for source in item["resources"].get("knowledgesources", ())
                 for name in source.get("created", ())}
        # Only assignments scoped exactly to an index being deleted; ARM keeps them orphaned
        # otherwise. Service-, group- and account-scoped grants are never listed here.
        if grants:
            for index in item["resources"].get("indexes", ()):
                operations.extend(grants.operations(generation, index["name"]))
        for kind in DELETE_ORDER:
            operations.extend(_operation(generation, kind, resource, owned)
                              for resource in item["resources"].get(kind, ()))
        # Blobs go last: the Knowledge Source that reads them is already gone.
        operations.extend(_blob_operations(storage, generation, item))
    identity = {
        "search_endpoint": search_endpoint.rstrip("/").lower(),
        "protected": sorted(g["generation"] for g in listing["generations"] if g["bound_by"]),
        "operations": operations,
    }
    plan_id = stable_id("retire-plan", identity)
    blobs = [op for op in operations if op["kind"] == "blobs"]
    roles = [op for op in operations if op["kind"] == "roleassignments"]
    deletes = sum(op["action"] == "delete" for op in operations) - len(blobs) - len(roles)
    freed = sum(op["kind"] == "indexes" for op in operations)
    prefixes = sorted({f"{op['container']}/{op.get('prefix', op['generation'] + '/')}"
                       for op in blobs})
    role_text = "".join(f"; remove {op['role']} for {op['principal']} on index {op['index']}"
                        for op in roles)
    warnings = [text for text, missing in (
        ("Staged source blobs are not deleted; pass --storage-endpoint and "
         "--storage-resource-id to include them.", not storage),
        ("Role assignments on the retired indexes are not checked; pass --search-resource-id "
         "to remove them rather than leave them orphaned.", not grants)) if missing]
    return {
        "plan_id": plan_id,
        "summary": (f"Blocked: {blockers[0]}" if blockers else
                    f"Retire {len(dict.fromkeys(generations))} generation(s): delete {deletes} "
                    f"Search resource(s) and {len(blobs)} staged blob(s)"
                    f"{' under ' + ', '.join(prefixes) if prefixes else ''}{role_text}; "
                    f"frees {freed} "
                    f"index slot(s) ({_slots(listing['indexes'])} used now). Undo: rebuild "
                    "with `ekg-build`."),
        "next_step": ("Resolve the blocker, then run `ekg-build plan-retire` again." if blockers else
                      f"After approval, run `ekg-build retire` with the same flags plus "
                      f"--plan-id {plan_id} --confirm-writes."),
        "search_endpoint": search_endpoint,
        "indexes": listing["indexes"],
        "indexes_freed": freed,
        "protected": identity["protected"],
        "operations": operations,
        "blockers": blockers,
        "write": {"requires_approval": True, "deletes": deletes, "blob_deletes": len(blobs),
                  "blob_prefixes": prefixes, "role_assignment_deletes": len(roles),
                  "conditional": "If-Match on each listed ETag",
                  "removed_by_service": len(operations) - deletes - len(blobs) - len(roles)},
        "warning": " ".join(warnings) or None,
    }


def _await_absent(store: GenerationStore, kind: str, name: str,
                  sleep: Callable[[float], None]) -> bool:
    for attempt in range(REMOVAL_POLLS):
        if not store.resource_exists(kind, name):
            return True
        if attempt + 1 < REMOVAL_POLLS:
            sleep(REMOVAL_DELAY_SECONDS)
    return False


def _apply(store: GenerationStore, op: dict[str, Any], storage: StagedStorage | None,
           sleep: Callable[[float], None], grants: IndexGrants | None = None) -> str:
    if op["kind"] == "roleassignments":
        grants.delete(op)
        return "deleted"
    if op["kind"] == "blobs":
        store.delete_blob(op["container"], op["name"], etag=op["etag"],
                          endpoint=storage.endpoint)
        if any(blob.name == op["name"] for blob in storage.listing(op["container"], op["name"])):
            raise RetireError(f"staged blob {op['name']} still exists after delete")
        return "deleted"
    if op["action"] == "await_removal":
        if not _await_absent(store, op["kind"], op["name"], sleep):
            raise RetireError(f"{op['name']} was not removed with its Knowledge Source")
        return "removed_by_service"
    deleted = store.delete_resource(op["kind"], op["name"], op["etag"])
    if store.resource_exists(op["kind"], op["name"]):
        raise RetireError(f"{op['name']} still exists after delete")
    return "deleted" if deleted else "already_absent"


def retire(store: GenerationStore, generations: tuple[str, ...], *,
           descriptors: tuple[str, ...], search_endpoint: str,
           approved_plan_id: str, confirmed: bool, storage: StagedStorage | None = None,
           grants: IndexGrants | None = None,
           sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    if not confirmed:
        raise ApprovalRequired("retire deletes require explicit confirmation")
    review = retire_plan(store, generations, descriptors=descriptors,
                         search_endpoint=search_endpoint, storage=storage, grants=grants)
    if approved_plan_id != review["plan_id"]:
        raise ApprovalRequired(
            f"explicit approval of retire plan {review['plan_id']} is required; "
            "the generations may have changed since review"
        )
    if review["blockers"]:
        raise RetireError("; ".join(review["blockers"]))
    recorder = TelemetryRecorder("build")
    results, error = [], None
    for op in review["operations"]:
        try:
            with recorder.span("retire-" + op["action"].replace("_", "-"),
                               resource=op["kind"]):
                results.append({**op, "status": _apply(store, op, storage, sleep, grants)})
        except RuntimeError as failure:
            error = f"{failure}; stopped after {len(results)} of {len(review['operations'])}"
            break
    after = store.service_statistics().get("counters", {}).get("indexesCount")
    writes = sum(r["status"] == "deleted" for r in results)
    blobs = sum(r["kind"] == "blobs" and r["status"] == "deleted" for r in results)
    roles = sum(r["kind"] == "roleassignments" for r in results)
    return {**review, "status": "stopped" if error else "retired", "error": error,
            "summary": (f"Stopped: {error}." if error else
                        f"Retired {len(dict.fromkeys(generations))} generation(s): "
                        f"{writes - blobs - roles} Search delete(s) and {blobs} staged blob(s)"
                        f"{f', plus {roles} role assignment(s),' if roles else ''} removed; "
                        f"{_slots(after)} index slots used now."),
            "next_step": ("Run `ekg-build plan-retire` again to see what is left."
                          if error else "Nothing else to do."),
            "results": results, "writes": writes,
            "indexes": after if after else review["indexes"],
            "indexes_before": review["indexes"],
            "indexes_after": after, "telemetry": recorder.events}


def cleanup_proposal(store: GenerationStore, published: dict[str, Any], previous: str, *,
                     search_endpoint: str, storage: StagedStorage | None = None,
                     grants: IndexGrants | None = None) -> dict[str, Any]:
    """Read-only, after publish: keep the new and the previous generation, propose the rest."""
    import tempfile
    with tempfile.TemporaryDirectory() as folder:
        new = Path(folder, "published.json")
        new.write_text(json.dumps(published), encoding="utf-8")
        descriptors = (str(new), previous)
        listing = list_generations(store, descriptors)
        candidates = tuple(g["generation"] for g in listing["generations"] if g["retirable"])
        kept = [g["generation"] for g in listing["generations"] if g["bound_by"]]
        if not candidates:
            return {"keep": kept, "retire_candidates": [], "retire_plan_id": None,
                    "summary": f"Keeping {', '.join(kept)}; no older generations to retire.",
                    "next_step": "Nothing to do."}
        review = retire_plan(store, candidates, descriptors=descriptors,
                             search_endpoint=search_endpoint, storage=storage, grants=grants)
    flags = " ".join(f"--generation {g}" for g in candidates)
    return {"keep": kept, "retire_candidates": list(candidates),
            "retire_plan_id": review["plan_id"], "retire_plan": review,
            "summary": f"Keeping {', '.join(kept)} for rollback. {review['summary']}",
            "next_step": ("Nothing was deleted. To retire, review `ekg-build plan-retire` with "
                          f"--descriptor <new> --descriptor <previous> {flags}, then approve "
                          "its plan ID.")}
