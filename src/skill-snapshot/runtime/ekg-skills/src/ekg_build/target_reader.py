"""Read-only ARM identity observations for an explicit source graph build."""

from __future__ import annotations

from typing import Any

from ekg_core import az_identity
from ekg_core.resource_endpoints import canonical_resource_endpoint, cognitive_account_endpoint


class AzureTargetReader:
    def __init__(self, *, tenant_id: str, credential: Any = None) -> None:
        self.credential = az_identity.cached(
            credential if credential is not None else az_identity.cli_credential(tenant_id))
        self.tenant_id = tenant_id

    def _inspect(self, resource_id: str, tenant_id: str, version: str) -> dict[str, Any]:
        if tenant_id != self.tenant_id or not resource_id.startswith("/subscriptions/"):
            raise ValueError("target tenant or ARM ID differs from the bound reader")
        import httpx

        token = self.credential.get_token("https://management.azure.com/.default").token
        if not az_identity.token_in_tenant(token, tenant_id):
            raise ValueError("TARGET_TENANT_MISMATCH: credential tenant differs")
        response = httpx.get(
            f"https://management.azure.com{resource_id}",
            params={"api-version": version},
            headers={"Authorization": f"Bearer {token}"}, timeout=60,
        )
        if response.is_error:
            raise RuntimeError(f"TARGET_INSPECTION_FAILED: ARM GET returned HTTP {response.status_code}")
        observed = response.json()
        if not isinstance(observed, dict):
            raise ValueError("TARGET_INSPECTION_FAILED: ARM metadata is malformed")
        return {**observed, "tenant_id": tenant_id}

    def inspect_search_service(self, resource_id: str, tenant_id: str) -> dict[str, Any]:
        return self._inspect(resource_id, tenant_id, "2025-05-01")

    def inspect_resource(self, resource_id: str, tenant_id: str) -> dict[str, Any]:
        if "/providers/Microsoft.Storage/storageAccounts/" in resource_id:
            observed = self._inspect(resource_id, tenant_id, "2024-01-01")
            endpoints = (observed.get("properties") or {}).get("primaryEndpoints") or {}
            endpoint = endpoints.get("blob")
        elif "/providers/Microsoft.CognitiveServices/accounts/" in resource_id:
            observed = self._inspect(resource_id, tenant_id, "2024-10-01")
            endpoint = cognitive_account_endpoint(observed.get("properties") or {})
        else:
            raise ValueError("unsupported target ARM resource type")
        return {**observed, "endpoint": canonical_resource_endpoint(endpoint)
                if isinstance(endpoint, str) else None}
