"""Consume readers granted per generation index.

Azure AI Search can scope Search Index Data Reader to one index, and those grants
do not follow a consumer to a new generation's indexes. Service-scoped readers
need nothing here: only exact index-scope grants are carried forward.
"""
from __future__ import annotations

import re
import uuid
from fnmatch import fnmatch
from typing import Any

READER_ROLE = "1407120a-92aa-4202-b7e9-c0e197c71c8f"
ROLE_NAME = "Search Index Data Reader"
ARM_API_VERSION = "2022-04-01"
_READER = re.compile(r"([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})"
                     r":(User|ServicePrincipal|Group)")


def parse(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    """`<object-id>:<User|ServicePrincipal|Group>`, normalized and de-duplicated."""
    readers = set()
    for value in values:
        match = _READER.fullmatch(value.strip())
        if not match:
            raise ValueError(f"--reader must be <object-id>:User|ServicePrincipal|Group, "
                             f"not {value!r}")
        readers.add(f"{match[1].lower()}:{match[2]}")
    return tuple(sorted(readers))


def scope(search_resource_id: str, index: str) -> str:
    return f"{search_resource_id}/indexes/{index}"


def assignments(arm: Any, at: str, tenant_id: str) -> list[dict[str, Any]]:
    """Role assignments made exactly at `at`; inherited ones are left alone."""
    listed = arm.arm_read(f"{at}/providers/Microsoft.Authorization/roleAssignments",
                          ARM_API_VERSION, tenant_id=tenant_id,
                          params={"$filter": "atScope()"}) or {}
    return [item for item in listed.get("value") or ()
            if str((item.get("properties") or {}).get("scope", "")).lower() == at.lower()]


def _readers_at(arm: Any, at: str, tenant_id: str) -> set[str]:
    return {f"{props['principalId'].lower()}:{props['principalType']}"
            for item in assignments(arm, at, tenant_id)
            if (props := item.get("properties") or {})
            and str(props.get("roleDefinitionId", "")).lower().endswith(READER_ROLE)}


def published(arm: Any, search_resource_id: str, descriptor: dict[str, Any],
              tenant_id: str) -> tuple[str, ...]:
    """Index-scoped readers of the published generation's content and graph indexes."""
    endpoints = descriptor.get("endpoints") or {}
    found: set[str] = set()
    for key in ("content_index", "graph_index"):
        if endpoints.get(key):
            found |= _readers_at(arm, scope(search_resource_id, endpoints[key]), tenant_id)
    return tuple(sorted(found))


def can_grant(arm: Any, search_resource_id: str, tenant_id: str) -> bool:
    """Whether the signed-in identity may write role assignments under the service."""
    listed = arm.arm_read(f"{search_resource_id}/providers/Microsoft.Authorization/permissions",
                          ARM_API_VERSION, tenant_id=tenant_id) or {}
    action = "microsoft.authorization/roleassignments/write"
    return any(
        any(fnmatch(action, allowed.lower()) for allowed in item.get("actions") or ())
        and not any(fnmatch(action, denied.lower()) for denied in item.get("notActions") or ())
        for item in listed.get("value") or ())


def command(reader: str, at: str) -> str:
    principal, kind = reader.split(":")
    return (f"az role assignment create --assignee-object-id {principal} "
            f"--assignee-principal-type {kind} --role \"{ROLE_NAME}\" --scope {at}")


def missing(arm: Any, search_resource_id: str, indexes: list[str], readers: tuple[str, ...],
            tenant_id: str) -> list[str]:
    """The grant command for every reader that lacks the role on an index."""
    result = []
    for index in indexes:
        at = scope(search_resource_id, index)
        have = _readers_at(arm, at, tenant_id)
        result += [command(reader, at) for reader in readers if reader not in have]
    return result


def grant(arm: Any, search_resource_id: str, indexes: list[str], readers: tuple[str, ...],
          tenant_id: str) -> dict[str, Any]:
    """Idempotent: a deterministic assignment name, and an existing grant counts as done."""
    subscription = search_resource_id.split("/")[2]
    role = (f"/subscriptions/{subscription}/providers/Microsoft.Authorization/"
            f"roleDefinitions/{READER_ROLE}")
    granted = 0
    for index in indexes:
        at = scope(search_resource_id, index)
        have = _readers_at(arm, at, tenant_id)
        for reader in readers:
            if reader in have:
                continue
            principal, kind = reader.split(":")
            name = uuid.uuid5(uuid.NAMESPACE_URL, f"{at.lower()}|{principal}|{READER_ROLE}")
            arm.arm_write("PUT", f"{at}/providers/Microsoft.Authorization/roleAssignments/{name}",
                          ARM_API_VERSION, tenant_id=tenant_id, body={"properties": {
                              "roleDefinitionId": role, "principalId": principal,
                              "principalType": kind}}, conflict_ok=True)
            granted += 1
    left = missing(arm, search_resource_id, indexes, readers, tenant_id)
    return {"readers": len(readers), "indexes": indexes, "granted": granted, "missing": left}
