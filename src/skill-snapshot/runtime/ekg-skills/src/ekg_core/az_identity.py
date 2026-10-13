"""Azure CLI sign-in checks shared by Provision, Build and Consume.

Tenant checks read the token's own ``tid`` claim instead of calling Microsoft
Graph, so they work with the narrowest sign-in the operator has.
"""

from __future__ import annotations

import base64
import binascii
import json
import shutil
import subprocess
import threading
import time
from typing import Any, Callable
from urllib.parse import parse_qsl, urlsplit, urlunsplit


class IdentityError(RuntimeError):
    pass


def az_executable(runner: Callable[..., Any]) -> str:
    if runner is not subprocess.run:
        return "az"
    executable = shutil.which("az")
    if executable is None:
        raise IdentityError("Azure CLI unavailable; check the intended login")
    return executable


def claims(token: str) -> dict[str, Any]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
    except (IndexError, ValueError, UnicodeDecodeError, binascii.Error, TypeError) as error:
        raise IdentityError("Azure CLI returned a token without verifiable claims") from error
    if not isinstance(payload, dict):
        raise IdentityError("Azure CLI returned invalid token claims")
    return payload


def _rest_query_as_parameters(arguments: list[str]) -> list[str]:
    # On Windows `az` is a .cmd shim, and cmd.exe splits an unquoted `&` in a URL into a
    # second command. Pass a multi-parameter query through --url-parameters instead.
    if not arguments or arguments[0] != "rest" or "--url" not in arguments:
        return arguments
    position = arguments.index("--url") + 1
    if position >= len(arguments):
        return arguments
    url = urlsplit(arguments[position])
    if "&" not in url.query:
        return arguments
    parameters = [f"{key}={value}" for key, value in parse_qsl(url.query, keep_blank_values=True)]
    rewritten = list(arguments)
    rewritten[position] = urlunsplit(url._replace(query=""))
    return [*rewritten, "--url-parameters", *parameters]


def az_json(arguments: list[str], *, runner: Callable[..., Any] = subprocess.run) -> Any:
    arguments = _rest_query_as_parameters(arguments)
    try:
        result = runner(
            [az_executable(runner), *arguments, "--output", "json"], capture_output=True, text=True,
            timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise IdentityError("Azure CLI unavailable or timed out; check the intended login") from error
    if result.returncode != 0:
        # Avoid echoing CLI stderr, which could contain account details or tokens.
        raise IdentityError(f"Azure CLI {arguments[:2]} failed; check login and permissions")
    try:
        return json.loads(result.stdout)
    except ValueError as error:
        raise IdentityError("Azure CLI returned invalid JSON") from error


def active_az_identity(
    tenant_id: str, subscription_id: str, *, runner: Callable[..., Any] = subprocess.run,
) -> dict[str, str]:
    account = az_json(["account", "show"], runner=runner)
    if not isinstance(account, dict) or (
        str(account.get("id", "")).lower() != subscription_id.lower()
        or str(account.get("tenantId", "")).lower() != tenant_id.lower()
    ):
        raise IdentityError(
            "active az account tenant/subscription differs; explicitly select the intended account"
        )
    kind = {"user": "User", "servicePrincipal": "ServicePrincipal"}.get(
        (account.get("user") or {}).get("type")
    )
    if not kind:
        raise IdentityError("active az account must be a user or service principal")
    issued = az_json([
        "account", "get-access-token", "--subscription", subscription_id,
        "--resource", "https://management.azure.com/",
    ], runner=runner)
    if not isinstance(issued, dict) or not isinstance(issued.get("accessToken"), str):
        raise IdentityError("Azure CLI did not return an ARM access token")
    token = claims(issued["accessToken"])
    if str(token.get("tid", "")).lower() != tenant_id.lower() or not isinstance(
        token.get("oid"), str
    ) or not token["oid"]:
        raise IdentityError("active az token does not match the intended tenant/principal")
    return {"tenant_id": tenant_id, "subscription_id": subscription_id,
            "principal_object_id": token["oid"], "principal_type": kind}


def token_in_tenant(token: str, tenant_id: str) -> bool:
    return str(claims(token).get("tid", "")).casefold() == tenant_id.casefold()


class CachedCredential:
    """Reuse each scope's token until five minutes before expiry.

    AzureCliCredential spawns `az` for every token, which costs about a second per
    request; staging a corpus makes one request per document.
    """

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self._tokens: dict[Any, Any] = {}
        self._lock = threading.Lock()

    def get_token(self, *scopes: str, **kwargs: Any) -> Any:
        key = (scopes, tuple(sorted(kwargs.items())))
        with self._lock:
            cached = self._tokens.get(key)
            if cached is not None and getattr(cached, "expires_on", 0) - time.time() > 300:
                return cached
            issued = self.inner.get_token(*scopes, **kwargs)
            if isinstance(getattr(issued, "expires_on", None), (int, float)):
                self._tokens[key] = issued
            return issued


def cached(credential: Any) -> Any:
    return credential if isinstance(credential, CachedCredential) else CachedCredential(credential)


def cli_credential(tenant_id: str | None = None) -> Any:
    from azure.identity import AzureCliCredential

    return AzureCliCredential(tenant_id=tenant_id) if tenant_id else AzureCliCredential()
