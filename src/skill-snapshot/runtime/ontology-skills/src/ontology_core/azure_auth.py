"""Entra tokens via Azure CLI and the tenant check. Never keys."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any, Literal

from ontology_core.errors import Blocked

Scope = Literal["search", "aoai", "arm"]
SCOPES: dict[str, str] = {
    "search": "https://search.azure.com/.default",
    "aoai": "https://cognitiveservices.azure.com/.default",
    "arm": "https://management.azure.com/.default",
}
AZ_TIMEOUT_S = 60.0


@dataclass(frozen=True)
class AzAccount:
    tenant_id: str
    tenant_name: str | None
    user: str | None


def _az_path() -> str:
    path = shutil.which("az")
    if path is None:
        raise Blocked("AZ_CLI_MISSING", "Azure CLI (`az`) is not on PATH")
    return path


def az_account() -> AzAccount | None:
    """`az account show -o json`; None when signed out.

    Raises:
        Blocked("AZ_CLI_MISSING"): `az` is not on PATH.
    """
    az = _az_path()
    try:
        proc = subprocess.run([az, "account", "show", "-o", "json"], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=AZ_TIMEOUT_S, check=False)
    except FileNotFoundError as exc:
        raise Blocked("AZ_CLI_MISSING", "Azure CLI (`az`) could not be started") from exc
    except subprocess.TimeoutExpired:
        return None
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("tenantId"), str) or not data["tenantId"]:
        return None
    user = data.get("user")
    name = data.get("tenantDisplayName")
    return AzAccount(tenant_id=data["tenantId"],
                     tenant_name=name if isinstance(name, str) and name else None,
                     user=user.get("name") if isinstance(user, dict) else None)


def require_tenant(tenant_id: str, tenant_name: str | None = None) -> AzAccount:
    """The signed-in account, which must be in `tenant_id`.

    Raises:
        Blocked("AZ_CLI_MISSING", tenant_id=...): `az` missing.
        Blocked("AZ_NOT_SIGNED_IN", tenant_id=..., tenant_name=...): no account.
        Blocked("TENANT_MISMATCH", tenant_id=..., tenant_name=...): a different tenant.
    """
    label = f"{tenant_id} ({tenant_name})" if tenant_name else tenant_id
    try:
        account = az_account()
    except Blocked as exc:
        raise Blocked("AZ_CLI_MISSING", exc.error, tenant_id=tenant_id) from exc
    if account is None:
        raise Blocked("AZ_NOT_SIGNED_IN", f"Azure CLI is not signed in; target tenant is {label}",
                      tenant_id=tenant_id, tenant_name=tenant_name)
    if account.tenant_id.strip().lower() != tenant_id.strip().lower():
        current = account.tenant_id + (f" ({account.tenant_name})" if account.tenant_name else "")
        raise Blocked("TENANT_MISMATCH", f"Azure CLI is signed in to tenant {current}, not the target tenant {label}",
                      tenant_id=tenant_id, tenant_name=tenant_name,
                      details={"signed_in_tenant_id": account.tenant_id, "target_tenant_id": tenant_id})
    return account


def credential(tenant_id: str) -> Any:
    """`azure.identity.AzureCliCredential(tenant_id=tenant_id)`."""
    from azure.identity import AzureCliCredential

    return AzureCliCredential(tenant_id=tenant_id)


def token(tenant_id: str, scope: Scope) -> str:
    """Bearer token for `SCOPES[scope]`.

    Raises:
        Blocked("AZ_NOT_SIGNED_IN", tenant_id=...): the CLI could not issue a token.
    """
    from azure.core.exceptions import ClientAuthenticationError

    try:
        return credential(tenant_id).get_token(SCOPES[scope]).token
    except ClientAuthenticationError as exc:
        # CredentialUnavailableError subclasses ClientAuthenticationError.
        raise Blocked("AZ_NOT_SIGNED_IN", f"Azure CLI could not issue a {scope} token for tenant {tenant_id}",
                      tenant_id=tenant_id) from exc
