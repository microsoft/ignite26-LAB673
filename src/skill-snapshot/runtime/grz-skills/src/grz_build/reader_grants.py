"""Carry index-scoped Search reader grants from the published generation to the next one.

Search roles scoped to an index don't follow an alias, so each generation needs its own
assignments. Plan lists the readers, apply grants them, publish refuses while any are missing,
and retire removes the grants on the retired index.
"""

from __future__ import annotations

import fnmatch
import uuid
from typing import Any, Callable
from urllib.parse import quote

from grz_core.contracts import ContractError

ROLE_API_VERSION = "2022-04-01"
SEARCH_INDEX_DATA_READER = "1407120a-92aa-4202-b7e9-c0e197c71c8f"
READER_ROLES = {SEARCH_INDEX_DATA_READER: "Search Index Data Reader"}
# Fixed namespace so the same principal, role and index always map to the same assignment name.
ASSIGNMENT_NAMESPACE = uuid.UUID("5b0f6f0e-6a53-4d1c-9a58-2f1f3b6f7a10")

ArmRequest = Callable[[str, str, str, dict[str, Any] | None], tuple[int, dict[str, Any]]]


def default_arm_request(method: str, url: str, bearer_token: str,
                        body: dict[str, Any] | None) -> tuple[int, dict[str, Any]]:
    import requests

    response = requests.request(method, url, json=body, timeout=30,
                                headers={"Authorization": "Bearer " + bearer_token})
    try:
        data = response.json() if response.content else {}
    except ValueError:
        data = {}
    return response.status_code, data


def reader(principal_id: str, *, principal_type: str | None = None, role: str = SEARCH_INDEX_DATA_READER,
           origin: str = "requested") -> dict[str, Any]:
    try:
        principal_id = str(uuid.UUID(principal_id))
    except (ValueError, TypeError) as exc:
        raise ContractError("READER_INVALID", f"--reader must be a principal object ID (GUID): {principal_id}") from exc
    return {"principal_id": principal_id, "principal_type": principal_type, "role_definition_id": role,
            "role": READER_ROLES[role], "origin": origin}


class ReaderGrants:
    """Reads and writes Search reader role assignments scoped to one index on one service."""

    def __init__(self, service_resource_id: str, bearer_token: str, arm_request: ArmRequest = default_arm_request):
        self.service_resource_id = service_resource_id.rstrip("/")
        self.subscription = "/".join(self.service_resource_id.split("/")[:3])
        self.token = bearer_token
        self.arm_request = arm_request

    def scope(self, index: str) -> str:
        return f"{self.service_resource_id}/indexes/{index}"

    def list(self, index: str) -> list[dict[str, Any]]:
        """Reader assignments made on exactly this index; inherited service or group grants are excluded."""
        scope = self.scope(index)
        url = (f"https://management.azure.com{quote(scope)}/providers/Microsoft.Authorization/roleAssignments"
               f"?api-version={ROLE_API_VERSION}&$filter=atScope()")
        status, data = self.arm_request("GET", url, self.token, None)
        if status != 200:
            raise ContractError("READER_GRANTS_UNREADABLE", f"Could not read role assignments on {index} (HTTP {status}). "
                                "Next step: sign in with an identity that can read role assignments on the Search service.")
        rows = []
        for item in data.get("value", []):
            props = item.get("properties") or {}
            role = str(props.get("roleDefinitionId", "")).rsplit("/", 1)[-1]
            if str(props.get("scope", "")).lower() != scope.lower() or role not in READER_ROLES:
                continue
            rows.append({**reader(props["principalId"], principal_type=props.get("principalType"), role=role,
                                  origin="current-index"), "assignment_id": item["id"]})
        return sorted(rows, key=lambda row: (row["principal_id"], row["role_definition_id"]))

    def grant(self, index: str, wanted: dict[str, Any]) -> str:
        """Create one assignment. An assignment that already exists counts as done."""
        if any(row["principal_id"] == wanted["principal_id"] and row["role_definition_id"] == wanted["role_definition_id"]
               for row in self.list(index)):
            return "exists"
        scope = self.scope(index)
        name = uuid.uuid5(ASSIGNMENT_NAMESPACE, f"{scope.lower()}|{wanted['principal_id']}|{wanted['role_definition_id']}")
        url = (f"https://management.azure.com{quote(scope)}/providers/Microsoft.Authorization/roleAssignments/{name}"
               f"?api-version={ROLE_API_VERSION}")
        properties = {"roleDefinitionId": f"{self.subscription}/providers/Microsoft.Authorization/roleDefinitions/"
                                          f"{wanted['role_definition_id']}",
                      "principalId": wanted["principal_id"]}
        if wanted.get("principal_type"):
            properties["principalType"] = wanted["principal_type"]
        status, data = self.arm_request("PUT", url, self.token, {"properties": properties})
        if status in (200, 201):
            return "created"
        if status == 409 and (data.get("error") or {}).get("code") == "RoleAssignmentExists":
            return "exists"
        error = ContractError("READER_GRANT_FAILED", f"Granting {wanted['role']} to {wanted['principal_id']} on {index} "
                              f"returned HTTP {status}")
        error.status_code = status  # lets the journal mark a 5xx as ambiguous
        raise error

    def revoke(self, assignment_id: str) -> str:
        """Delete one assignment. One that's already gone counts as done, so a rerun is safe."""
        status, _ = self.arm_request("DELETE", f"https://management.azure.com{quote(assignment_id)}"
                                     f"?api-version={ROLE_API_VERSION}", self.token, None)
        if status in (200, 204, 404):
            return "gone" if status != 200 else "deleted"
        error = ContractError("READER_REVOKE_FAILED", f"Removing a reader grant returned HTTP {status}")
        error.status_code = status
        raise error

    def check_can_manage(self, index: str, actions: tuple[str, ...]) -> None:
        """Read-only: stop before any write if this identity can't write the needed role assignments.

        Checked on the Search service, whose permissions cover its indexes; the new index doesn't exist at plan time.
        """
        url = (f"https://management.azure.com{quote(self.service_resource_id)}/providers/Microsoft.Authorization/"
               f"permissions?api-version={ROLE_API_VERSION}")
        status, data = self.arm_request("GET", url, self.token, None)
        if status != 200:
            raise ContractError("READER_GRANTS_UNREADABLE", f"Could not read this identity's permissions on {index} "
                                f"(HTTP {status}). Next step: sign in with an identity that can manage role "
                                "assignments on the Search service.")
        missing = [action for action in actions if not _allowed(data.get("value", []), action)]
        if missing:
            raise ContractError("READER_GRANTS_FORBIDDEN", f"This identity can't {', '.join(missing)} on {index}. "
                                "Next step: run as an identity with Owner or Role Based Access Control "
                                "Administrator on the Search service, or re-plan with --drop-reader.")


GRANT_ACTIONS = ("Microsoft.Authorization/roleAssignments/write",)
REVOKE_ACTIONS = ("Microsoft.Authorization/roleAssignments/delete",)


def _allowed(permissions: list[dict[str, Any]], action: str) -> bool:
    def matches(patterns: list[str]) -> bool:
        return any(fnmatch.fnmatchcase(action.lower(), pattern.lower()) for pattern in patterns)
    return any(matches(p.get("actions", [])) and not matches(p.get("notActions", [])) for p in permissions)


def missing_readers(current: list[dict[str, Any]], new: list[dict[str, Any]], dropped: list[str]) -> list[str]:
    """Principals reading the published index who can't read the new one and weren't dropped in the plan."""
    have = {(row["principal_id"], row["role_definition_id"]) for row in new}
    return sorted({row["principal_id"] for row in current
                   if (row["principal_id"], row["role_definition_id"]) not in have and row["principal_id"] not in dropped})
