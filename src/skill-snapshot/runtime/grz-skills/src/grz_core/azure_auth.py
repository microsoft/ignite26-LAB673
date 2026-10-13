"""Azure identity helpers shared by live Build and Consume."""

from __future__ import annotations

import base64
import json
import threading
import time
from typing import Any

from grz_core.contracts import ContractError

MANAGEMENT_SCOPE = "https://management.azure.com/.default"
SEARCH_SCOPE = "https://search.azure.com/.default"
TOKEN_REFRESH_MARGIN_SECONDS = 300


class CachingCredential:
    """Cache tokens per method, scope and tenant; DefaultAzureCredential can spawn `az` on every call."""

    def __init__(self, inner: Any, *, clock: Any = time.time, margin: float = TOKEN_REFRESH_MARGIN_SECONDS):
        self.inner, self.clock, self.margin = inner, clock, margin
        self._tokens: dict[tuple[Any, ...], Any] = {}
        self._lock = threading.Lock()

    def _cached(self, method: str, scopes: tuple[str, ...], kwargs: dict[str, Any], fetch: Any) -> Any:
        # Claims challenges (CAE) and unknown options must always reach the real credential.
        if kwargs.get("claims") or set(kwargs) - {"tenant_id", "options"} or (kwargs.get("options") or {}).get("claims"):
            return fetch()
        options = kwargs.get("options") or {}
        key = (method, scopes, kwargs.get("tenant_id") or options.get("tenant_id"))
        with self._lock:
            token = self._tokens.get(key)
            if token is not None and getattr(token, "expires_on", 0) - self.margin > self.clock():
                return token
            token = fetch()
            self._tokens[key] = token
            return token

    def get_token(self, *scopes: str, **kwargs: Any) -> Any:
        return self._cached("get_token", scopes, kwargs, lambda: self.inner.get_token(*scopes, **kwargs))

    def get_token_info(self, *scopes: str, options: Any = None) -> Any:
        if not hasattr(self.inner, "get_token_info"):
            raise AttributeError("get_token_info")
        return self._cached("get_token_info", scopes, {"options": options} if options else {},
                            lambda: self.inner.get_token_info(*scopes, options=options))

    def close(self) -> None:
        close = getattr(self.inner, "close", None)
        if callable(close):
            close()


def create_default_credential() -> Any:
    """Create the only default live credential chain used by CLI entrypoints."""
    try:
        from azure.identity import DefaultAzureCredential
    except ImportError as exc:  # pragma: no cover - exercised only without optional extra
        raise ContractError("AZURE_DEPENDENCY_MISSING", "Install the azure optional dependency") from exc
    return CachingCredential(DefaultAzureCredential(exclude_interactive_browser_credential=True))


def token_claims(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) < 2:
        raise ContractError("TOKEN_INVALID", "Azure access token is not a JWT")
    data = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(data.encode("ascii")).decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise ContractError("TOKEN_INVALID", "Azure access token payload is not decodable") from exc


def get_token(credential: Any, scope: str, tenant_id: str) -> str:
    try:
        token = credential.get_token(scope, tenant_id=tenant_id)
    except TypeError:
        token = credential.get_token(scope)
    value = getattr(token, "token", token)
    if not isinstance(value, str) or not value:
        raise ContractError("TOKEN_INVALID", "Azure credential did not return a bearer token")
    return value


def validate_tenant(credential: Any, tenant_id: str) -> dict[str, Any]:
    if not tenant_id:
        raise ContractError("TENANT_REQUIRED", "--tenant-id is required for Entra authentication")
    observed: dict[str, Any] = {}
    for name, scope in (("management", MANAGEMENT_SCOPE), ("search", SEARCH_SCOPE)):
        token = get_token(credential, scope, tenant_id)
        payload = token_claims(token)
        if payload.get("tid") != tenant_id:
            raise ContractError("TENANT_MISMATCH", "Authenticated token tenant does not match --tenant-id")
        observed[name] = {"tid": payload.get("tid"), "appid": payload.get("appid") or payload.get("azp")}
    return observed
