"""Credential and store construction for GRZ Consume."""

from __future__ import annotations

import os
from typing import Any, Literal

from grz_core.azure_auth import create_default_credential, validate_tenant
from grz_core.contracts import ContractError, Descriptor

from .search_store import AzureSearchReadStore, QueryOnlyPolicy


def build_store(
    descriptor: Descriptor,
    endpoint: str,
    auth: Literal["query-key", "entra"] = "query-key",
    tenant_id: str | None = None,
    *,
    query_key: str | None = None,
    credential: Any | None = None,
) -> AzureSearchReadStore:
    descriptor.validate()
    if auth == "query-key":
        key = query_key or os.environ.get("GRZ_SEARCH_QUERY_KEY")
        if not key:
            raise ContractError("QUERY_INVALID", "query-key auth requires GRZ_SEARCH_QUERY_KEY")
        from azure.core.credentials import AzureKeyCredential
        credential = AzureKeyCredential(key)
    elif auth == "entra":
        tenant = tenant_id or os.environ.get("GRZ_TENANT_ID")
        if credential is None:
            credential = create_default_credential()
        validate_tenant(credential, tenant or "")
    else:
        raise ContractError("QUERY_INVALID", "--auth must be query-key or entra")
    return AzureSearchReadStore(endpoint, credential, policies=[QueryOnlyPolicy(descriptor.physical_index, auth)])
