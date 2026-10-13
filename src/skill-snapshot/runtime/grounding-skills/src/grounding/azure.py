"""Microsoft Entra auth and thin REST helpers for Azure Resource Manager and Azure AI Search.

No keys are read, stored or accepted: every call carries an Entra bearer token.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import API_VERSION
from .errors import AuthError, GroundingError, ServiceError

ARM = "https://management.azure.com"
ARM_SCOPE = "https://management.azure.com/.default"
SEARCH_SCOPE = "https://search.azure.com/.default"
SEARCH_SUFFIXES = (".search.windows.net", ".search.azure.us", ".search.azure.cn")
SEARCH_ARM_API = "2025-05-01"
RESOURCES_API = "2021-04-01"
AUTHZ_API = "2022-04-01"
RETRY_STATUS = {429, 503}

ROLE_IDS = {  # built-in role definition GUIDs (public, identical in every tenant)
    "Search Service Contributor": "7ca78c08-252a-4471-8644-bb5ff32d4ba0",
    "Search Index Data Contributor": "8ebe5a00-799e-43f5-93ac-243d3dce84a7",
    "Search Index Data Reader": "1407120a-92aa-4202-b7e9-c0e197c71c8f",
}
# What each role must grant (matched with wildcards against effective actions / dataActions).
ROLE_NEEDS = {
    "Search Service Contributor": ("actions", "Microsoft.Search/searchServices/write"),
    "Search Index Data Contributor": ("dataActions", "Microsoft.Search/searchServices/indexes/documents/write"),
    "Search Index Data Reader": ("dataActions", "Microsoft.Search/searchServices/indexes/documents/read"),
}


def validate_endpoint(endpoint: str) -> str:
    u = urlparse(endpoint)
    host = (u.hostname or "").lower()
    if u.scheme != "https" or not host.endswith(SEARCH_SUFFIXES) or u.username or u.path.strip("/"):
        raise GroundingError("ENDPOINT_INVALID", "endpoint must look like https://<service>.search.windows.net",
                             "Run grounding-provision connect to list services you can use.")
    return f"https://{host}"


def endpoint_for(service_name: str) -> str:
    return f"https://{service_name}.search.windows.net"


def _jwt_claims(token: str) -> dict[str, Any]:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:  # noqa: BLE001 - claims are advisory only
        return {}


def default_subscription() -> str:
    sub = os.environ.get("AZURE_SUBSCRIPTION_ID", "").strip()
    if sub:
        return sub
    profile = Path(os.environ.get("AZURE_CONFIG_DIR") or Path.home() / ".azure") / "azureProfile.json"
    try:
        data = json.loads(profile.read_text(encoding="utf-8-sig"))
        for s in data.get("subscriptions", []):
            if s.get("isDefault"):
                return s["id"]
    except (OSError, ValueError):
        pass
    return ""


class Azure:
    """Entra credential plus resolved tenant/subscription identity."""

    def __init__(self, credential: Any | None = None, http: Any | None = None, say=None):
        import httpx
        self._cred = credential
        self._http = http or httpx.Client(timeout=120.0)
        self._say = say or (lambda msg: print(msg, file=sys.stderr))
        self.identity: dict[str, Any] = {}

    def credential(self):
        if self._cred is None:
            from azure.identity import DefaultAzureCredential
            self._cred = DefaultAzureCredential(exclude_interactive_browser_credential=True)
        return self._cred

    def token(self, scope: str) -> str:
        try:
            return self.credential().get_token(scope).token
        except Exception as exc:  # noqa: BLE001
            raise AuthError("NOT_SIGNED_IN", f"could not obtain an Entra token: {type(exc).__name__}",
                            "Sign in with `az login`, then retry.") from exc

    def resolve_identity(self, expected_tenant: str = "", expected_subscription: str = "",
                         need_subscription: bool = True) -> dict[str, Any]:
        """Resolve and print tenant/subscription; abort when they differ from user-confirmed values."""
        claims = _jwt_claims(self.token(ARM_SCOPE))
        ident: dict[str, Any] = {"tenant": claims.get("tid", ""), "principal_id": claims.get("oid", ""),
                                 "principal": claims.get("upn") or claims.get("appid") or "", "subscription": "",
                                 "subscription_name": ""}
        sub = expected_subscription or (default_subscription() if need_subscription else "")
        if sub:
            r = self._arm("GET", f"/subscriptions/{sub}", api="2022-12-01")
            ident["subscription"] = sub
            ident["subscription_name"] = r.get("displayName", "")
            ident["tenant"] = r.get("tenantId") or ident["tenant"]
        elif need_subscription:
            raise AuthError("SUBSCRIPTION_UNRESOLVED", "no subscription resolved",
                            "Pass --subscription or run `az account set --subscription <id>`.")
        self._say(f"Tenant: {ident['tenant']}")
        if ident["subscription"]:
            self._say(f"Subscription: {ident['subscription_name']} ({ident['subscription']})")
        if expected_tenant and expected_tenant.lower() != ident["tenant"].lower():
            raise AuthError("TENANT_MISMATCH", "resolved tenant differs from the confirmed --tenant; aborting",
                            "Sign in to the intended tenant (`az login --tenant <id>`).")
        self.identity = ident
        return ident

    def _request(self, method: str, url: str, token: str, body: Any = None,
                 ok: tuple[int, ...] = (200, 201, 202, 204, 207), allow: tuple[int, ...] = ()) -> Any:
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        for attempt in range(6):
            r = self._http.request(method, url, headers=headers, content=None if body is None else json.dumps(body))
            if r.status_code in RETRY_STATUS and attempt < 5:
                time.sleep(min(30.0, float(r.headers.get("Retry-After", 2 ** attempt))))
                continue
            break
        if r.status_code in allow:
            return {"_status": r.status_code, **(_json(r) if isinstance(_json(r), dict) else {})}
        if r.status_code in (401, 403):
            raise AuthError("FORBIDDEN", f"{method} {urlparse(url).path} returned HTTP {r.status_code}",
                            "Check the Entra roles for this identity (grounding-provision doctor).",
                            detail=_json(r))
        if r.status_code not in ok:
            raise ServiceError("SERVICE_HTTP", f"{method} {urlparse(url).path} returned HTTP {r.status_code}",
                               detail=_json(r))
        return _json(r) if r.content else {}

    # --- ARM -------------------------------------------------------------------------------------------------
    def _arm(self, method: str, path: str, body: Any = None, api: str = RESOURCES_API, allow: tuple[int, ...] = ()) -> Any:
        sep = "&" if "?" in path else "?"
        return self._request(method, f"{ARM}{path}{sep}api-version={api}", self.token(ARM_SCOPE), body, allow=allow)

    def arm(self, method: str, path: str, body: Any = None, api: str = RESOURCES_API, allow: tuple[int, ...] = ()) -> Any:
        return self._arm(method, path, body, api, allow)

    # --- Search data plane ---------------------------------------------------------------------------------
    def search(self, method: str, endpoint: str, path: str, body: Any = None, allow: tuple[int, ...] = ()) -> Any:
        sep = "&" if "?" in path else "?"
        url = f"{validate_endpoint(endpoint)}{path}{sep}api-version={API_VERSION}"
        return self._request(method, url, self.token(SEARCH_SCOPE), body, allow=allow)


def _json(r: Any) -> Any:
    try:
        return r.json()
    except ValueError:
        return {"text": (r.text or "")[:500]}


def role_gaps(permissions: list[dict[str, Any]], roles: list[str]) -> dict[str, bool]:
    """Pure: which of `roles` are satisfied by effective ARM permission blocks."""
    import fnmatch

    def granted(kind: str, needed: str) -> bool:
        for block in permissions:
            allow = block.get(kind, [])
            deny = block.get("not" + kind[0].upper() + kind[1:], [])
            if any(fnmatch.fnmatchcase(needed.lower(), a.lower()) for a in allow) and not any(
                    fnmatch.fnmatchcase(needed.lower(), d.lower()) for d in deny):
                return True
        return False

    return {r: granted(*ROLE_NEEDS[r]) for r in roles}
