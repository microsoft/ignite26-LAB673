"""Build access in the provision plan: the Search identity, the private container and
the six role assignments Build needs. Every item is a planned, approved operation."""

from __future__ import annotations

import uuid
from fnmatch import fnmatch
from typing import Any

from ekg_core.models import Operation, ProvisioningSpec

ROLE_API = "2022-04-01"
IDENTITY_API = "2023-01-31"
CONTAINER_API = "2023-05-01"
# Built-in role definition IDs; they are the same in every tenant.
ROLE_IDS = {
    "Search Service Contributor": "7ca78c08-252a-4471-8644-bb5ff32d4ba0",
    "Search Index Data Contributor": "8ebe5a00-799e-43f5-93ac-243d3dce84a7",
    "Storage Blob Data Contributor": "ba92f5b4-2d11-453d-a403-e96b0029c9fe",
    "Storage Blob Data Reader": "2a2b9908-6ea1-4ae2-8e65-a410df84e7d1",
    "Cognitive Services OpenAI User": "5e0bd9bd-7b93-4f28-af87-19fc36ad61bd",
}
# (operation suffix, principal, role, scope kind)
GRANTS = (
    ("operator-search-service-contributor", "operator", "Search Service Contributor", "search"),
    ("operator-search-index-data-contributor", "operator", "Search Index Data Contributor",
     "search"),
    ("operator-storage-blob-data-contributor", "operator", "Storage Blob Data Contributor",
     "container"),
    ("operator-openai-user", "operator", "Cognitive Services OpenAI User", "openai"),
    ("search-identity-storage-blob-data-reader", "search_identity", "Storage Blob Data Reader",
     "container"),
    ("search-identity-openai-user", "search_identity", "Cognitive Services OpenAI User",
     "openai"),
)
_GRANTS = {f"grant-{suffix}": (principal, role, kind)
           for suffix, principal, role, kind in GRANTS}
PERMISSIONS = (
    "Microsoft.ManagedIdentity/userAssignedIdentities/read",
    "Microsoft.ManagedIdentity/userAssignedIdentities/write",
    "Microsoft.ManagedIdentity/userAssignedIdentities/assign/action",
    "Microsoft.Storage/storageAccounts/blobServices/containers/read",
    "Microsoft.Storage/storageAccounts/blobServices/containers/write",
    "Microsoft.Authorization/roleAssignments/read",
    "Microsoft.Authorization/roleAssignments/write",
)


def _base(spec: ProvisioningSpec) -> str:
    return (f"/subscriptions/{spec.target.subscription_id}"
            f"/resourceGroups/{spec.target.resource_group}")


def identity_id(spec: ProvisioningSpec) -> str:
    assert spec.build_access is not None
    return (f"{_base(spec)}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/"
            f"{spec.build_access.search_identity_name}")


def container_id(spec: ProvisioningSpec) -> str:
    assert spec.build_access is not None
    return (f"{_base(spec)}/providers/Microsoft.Storage/storageAccounts/{spec.storage_name}"
            f"/blobServices/default/containers/{spec.build_access.storage_container}")


def scope(spec: ProvisioningSpec, kind: str) -> str:
    if kind == "container":
        return container_id(spec)
    if kind == "search":
        return f"{_base(spec)}/providers/Microsoft.Search/searchServices/{spec.search_name}"
    return f"{_base(spec)}/providers/Microsoft.CognitiveServices/accounts/{spec.openai_name}"


def grant(operation_id: str) -> tuple[str, str, str]:
    """(principal, role, scope kind) of a planned role assignment."""
    return _GRANTS[operation_id]


def role_assignment_id(spec: ProvisioningSpec, operation_id: str) -> str:
    """Deterministic assignment name, so a rerun finds the one it made."""
    assert spec.build_access is not None
    principal, role, kind = grant(operation_id)
    at = scope(spec, kind)
    who = (spec.build_access.operator_object_id.lower() if principal == "operator"
           else identity_id(spec).lower())
    name = uuid.uuid5(uuid.NAMESPACE_URL, f"{at.lower()}|{who}|{ROLE_IDS[role]}")
    return f"{at}/providers/Microsoft.Authorization/roleAssignments/{name}"


def operations(spec: ProvisioningSpec) -> tuple[list[Operation], list[Operation]]:
    """(before Search, after the services and models) operations for build access."""
    access = spec.build_access
    if access is None:
        return [], []
    before = [Operation(
        id="create-search-identity", plane="provision", action="ensure",
        resource="search_identity", name=access.search_identity_name,
        risk="remote_change", reversible=False, requires_approval=True,
        evidence=("resource_id", "principal_id"),
    )]
    after = [Operation(
        id="create-blob-container", plane="provision", action="ensure",
        resource="blob_container", name=access.storage_container,
        risk="remote_change", reversible=False, requires_approval=True,
        evidence=("resource_id", "public_access"), depends_on=("create-storage_account",),
    )]
    for suffix, principal, role, kind in GRANTS:
        after.append(Operation(
            id=f"grant-{suffix}", plane="provision", action="ensure",
            resource="role_assignment",
            name=f"{role} for {'you' if principal == 'operator' else 'the Search identity'}",
            risk="access_change", reversible=False, requires_approval=True,
            evidence=("resource_id", "role", "principal_id", "scope"),
            depends_on=tuple(dict.fromkeys((
                "create-blob-container" if kind == "container" else
                "create-search_service" if kind == "search" else "create-openai_resource",
                *(("create-search-identity",) if principal == "search_identity" else ()),
            ))),
        ))
    return before, after


def desired(spec: ProvisioningSpec, operation: Operation, *, principal_id: str | None = None,
            tags: dict[str, str] | None = None) -> dict[str, Any]:
    assert spec.build_access is not None
    if operation.resource == "search_identity":
        payload: dict[str, Any] = {"location": spec.target.location}
        if tags:
            payload["tags"] = tags
        return payload
    if operation.resource == "blob_container":
        return {"properties": {"publicAccess": "None"}}
    who, role, _ = grant(operation.id)
    return {"properties": {
        "roleDefinitionId": (f"/subscriptions/{spec.target.subscription_id}/providers/"
                             f"Microsoft.Authorization/roleDefinitions/{ROLE_IDS[role]}"),
        "principalId": principal_id,
        "principalType": (spec.build_access.operator_principal_type if who == "operator"
                          else "ServicePrincipal"),
    }}


def principal_for(spec: ProvisioningSpec, operation_id: str,
                  identity_principal: str | None) -> str | None:
    assert spec.build_access is not None
    who, _, _ = grant(operation_id)
    return spec.build_access.operator_object_id if who == "operator" else identity_principal


def can_assign_roles(permissions: Any) -> bool:
    """Whether an ARM permissions listing allows roleAssignments/write."""
    action = "microsoft.authorization/roleassignments/write"
    rows = permissions.get("value") if isinstance(permissions, dict) else None
    return any(
        any(fnmatch(action, str(allowed).lower()) for allowed in row.get("actions") or ())
        and not any(fnmatch(action, str(denied).lower()) for denied in row.get("notActions") or ())
        for row in rows or () if isinstance(row, dict))


def plain_writes(spec: ProvisioningSpec, operations_: tuple[Operation, ...]) -> list[str]:
    """One plain-language line per planned write, for the approval text."""
    lines = []
    for operation in operations_:
        if operation.resource == "resource_group":
            lines.append(f"Create resource group {operation.name}")
        elif operation.resource == "search_identity":
            lines.append(f"Create managed identity {operation.name} for Search to read "
                         "documents and call models")
        elif operation.resource == "search_service":
            lines.append(f"Create Azure AI Search {operation.name} ({spec.search_sku})"
                         + (" with the managed identity attached" if spec.build_access else ""))
        elif operation.resource == "storage_account":
            lines.append(f"Create storage account {operation.name}")
        elif operation.resource == "blob_container":
            lines.append(f"Create private Blob container {operation.name}")
        elif operation.resource in ("openai_resource", "content_understanding"):
            lines.append(f"Create Azure OpenAI account {operation.name}")
        elif operation.resource == "model_deployment":
            model = next(item for item in spec.model_deployments if item.name == operation.name)
            lines.append(f"Deploy {model.model} as {model.name} ({model.sku}, "
                         f"{model.capacity}K tokens/min), after a quota check")
        elif operation.resource == "role_assignment":
            _, role, kind = grant(operation.id)
            target = {"search": "the Search service", "container": "the container",
                      "openai": "the OpenAI account"}[kind]
            lines.append(f"Grant {operation.name} on {target}")
        else:
            lines.append(f"{operation.action.capitalize()} {operation.resource} {operation.name}")
    return lines
