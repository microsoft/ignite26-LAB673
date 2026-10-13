"""The only egress path.

Every outbound request goes through `request()`, which enforces `EgressPolicy`. Tests install a fake
transport with `set_transport()` and a recorder with `set_recorder()`; nothing else in the package may
import `urllib`, `requests`, `httpx` or `azure.core.pipeline.transport` directly.

The allowlist (`check()`), for the targets named in the policy only:

- Search: `POST https://<svc>.search.windows.net/indexes('<physical_index>')/docs/search.post.search`
  (or `/indexes/<physical_index>/docs/search.post.search`), and `GET` of `/indexes('<idx>')/docs…`
  or `/indexes/<idx>/docs…`.
- Model: `POST <endpoint>/openai/deployments/<deployment>/chat/completions` and `GET <endpoint>/openai/models`.
- ARM: `GET https://management.azure.com/subscriptions/<sub>/resourceGroups/<rg>/providers/
  Microsoft.CognitiveServices/accounts/<acct>/deployments/<deployment>`.
- `extra`: exact `"<METHOD> https://host/path"` entries (GET or POST only).

Everything is `https` on the default port with no user info or fragment. PUT, PATCH and DELETE are never
allowed. The query string is not part of the match. Redirects are never followed, and `request()` never
retries: a request whose outcome is unknown raises `EgressUnknownOutcome` for the caller to journal.
"""

from __future__ import annotations

import http.client
import json as _json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import unquote, urlsplit

from ontology_core.errors import Blocked

CONNECT_TIMEOUT_S = 10.0
READ_TIMEOUT_S = 300.0
MAX_RETRY_AFTER_S = 30.0

ARM_HOST = "management.azure.com"
SEARCH_SUFFIX = ".search.windows.net"
ALLOWED_METHODS = ("GET", "POST")


@dataclass(frozen=True)
class Response:
    status: int
    headers: Mapping[str, str]
    """Lower-case header names (`request()` normalizes them)."""
    body: bytes

    def json(self) -> Any:
        """The body parsed as JSON; None for an empty body. Raises `ValueError` on invalid JSON."""
        if not self.body.strip():
            return None
        return _json.loads(self.body.decode("utf-8-sig"))


@dataclass(frozen=True)
class EgressPolicy:
    """Allowed targets, built from config. Any field may be None when not yet known."""

    search_endpoint: str | None = None
    physical_index: str | None = None
    model_endpoint: str | None = None
    model_deployment: str | None = None
    subscription_id: str | None = None
    resource_group: str | None = None
    account_name: str | None = None
    extra: tuple[str, ...] = field(default=())


class EgressNotSent(Exception):
    """The request never left the machine (DNS/connect failure). Safe to treat as not billed."""


class EgressNameNotResolved(EgressNotSent):
    """DNS has no record for the host (for a `*.search.windows.net` host: the service does not exist)."""


class EgressUnknownOutcome(Exception):
    """Timed out or dropped after the body was sent; the caller journals `call_unknown`."""


class Transport(Protocol):
    def __call__(self, method: str, url: str, *, headers: Mapping[str, str], body: bytes | None,
                 connect_timeout: float, read_timeout: float) -> Response: ...


Recorder = Callable[[str, str], None]


# --------------------------------------------------------------------------- allowlist

def _host_and_path(url: str) -> tuple[str, str] | None:
    """`(host, decoded path)` for a plain https URL on the default port, else None."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme.lower() != "https" or parts.fragment or parts.username is not None or parts.password is not None:
        return None
    if port not in (None, 443) or not parts.hostname:
        return None
    path = unquote(parts.path)
    if "\\" in path or any(seg in (".", "..") for seg in path.split("/")):
        return None
    return parts.hostname.lower(), path


def _endpoint(value: str | None) -> tuple[str, str] | None:
    """`(host, path prefix without trailing slash)` of a configured endpoint."""
    if not value:
        return None
    parsed = _host_and_path(value.strip())
    if parsed is None:
        return None
    return parsed[0], parsed[1].rstrip("/")


def _search_allowed(policy: EgressPolicy, method: str, host: str, path: str) -> bool:
    target = _endpoint(policy.search_endpoint)
    idx = policy.physical_index
    if target is None or not idx or host != target[0] or not host.endswith(SEARCH_SUFFIX):
        return False
    for docs in (f"/indexes('{idx}')/docs", f"/indexes/{idx}/docs"):
        if method == "POST" and path == docs + "/search.post.search":
            return True
        if method == "GET" and (path == docs or path.startswith(docs + "/") or path.startswith(docs + "(")):
            return True
    return False


def _model_allowed(policy: EgressPolicy, method: str, host: str, path: str) -> bool:
    target = _endpoint(policy.model_endpoint)
    if target is None or host != target[0]:
        return False
    base = target[1]
    if method == "GET" and path == base + "/openai/models":
        return True
    dep = policy.model_deployment
    return bool(dep) and method == "POST" and path == f"{base}/openai/deployments/{dep}/chat/completions"


def _arm_allowed(policy: EgressPolicy, method: str, host: str, path: str) -> bool:
    fields = (policy.subscription_id, policy.resource_group, policy.account_name, policy.model_deployment)
    if method != "GET" or host != ARM_HOST or not all(fields):
        return False
    sub, rg, acct, dep = fields
    expected = (f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.CognitiveServices"
                f"/accounts/{acct}/deployments/{dep}")
    return path.lower() == expected.lower()


def _extra_allowed(policy: EgressPolicy, method: str, host: str, path: str) -> bool:
    for entry in policy.extra:
        allowed_method, _, allowed_url = entry.strip().partition(" ")
        parsed = _host_and_path(allowed_url.strip())
        if allowed_method.upper() == method and parsed is not None and parsed == (host, path):
            return True
    return False


def _display(url: str) -> str:
    return url.split("?", 1)[0].split("#", 1)[0]


def check(policy: EgressPolicy, method: str, url: str) -> None:
    """Raises:
        Blocked("INTERNAL_ERROR", "egress not allowlisted: <METHOD> <url>"): not in the allowlist,
        or any PUT/PATCH/DELETE.
    """
    verb = method.upper()
    parsed = _host_and_path(url)
    if verb in ALLOWED_METHODS and parsed is not None:
        host, path = parsed
        if any(rule(policy, verb, host, path)
               for rule in (_search_allowed, _model_allowed, _arm_allowed, _extra_allowed)):
            return
    raise Blocked("INTERNAL_ERROR", f"egress not allowlisted: {verb} {_display(url)}")


# --------------------------------------------------------------------------- transports

def _not_sent(exc: BaseException) -> type[EgressNotSent] | None:
    """The `EgressNotSent` class to raise when urllib3 failed before any byte of the request went out
    (DNS, TCP or TLS connect), else None."""
    import urllib3.exceptions as u3

    seen: set[int] = set()
    stack: list[Any] = [exc]
    found: type[EgressNotSent] | None = None
    while stack:
        item = stack.pop()
        if item is None or id(item) in seen:
            continue
        seen.add(id(item))
        if isinstance(item, u3.NameResolutionError):
            return EgressNameNotResolved
        if isinstance(item, (u3.NewConnectionError, u3.ConnectTimeoutError)):
            found = EgressNotSent
        if isinstance(item, BaseException):
            stack.extend([getattr(item, "reason", None), item.__cause__, item.__context__, *item.args])
    return found


_session: Any = None


def _requests_transport(method: str, url: str, *, headers: Mapping[str, str], body: bytes | None,
                        connect_timeout: float, read_timeout: float) -> Response:
    import requests
    from requests.adapters import HTTPAdapter

    global _session
    if _session is None:
        _session = requests.Session()
        adapter = HTTPAdapter(max_retries=0)
        _session.mount("https://", adapter)
        _session.mount("http://", adapter)
    try:
        resp = _session.request(method, url, headers=dict(headers), data=body,
                                timeout=(connect_timeout, read_timeout), allow_redirects=False)
    except (requests.exceptions.ConnectTimeout, requests.exceptions.SSLError) as exc:
        raise EgressNotSent(f"{method} {_display(url)}: {type(exc).__name__}") from exc
    except requests.exceptions.ConnectionError as exc:
        not_sent = _not_sent(exc)
        if not_sent is not None:
            raise not_sent(f"{method} {_display(url)}: {type(exc).__name__}") from exc
        raise EgressUnknownOutcome(f"{method} {_display(url)}: {type(exc).__name__}") from exc
    except requests.exceptions.RequestException as exc:
        raise EgressUnknownOutcome(f"{method} {_display(url)}: {type(exc).__name__}") from exc
    return Response(resp.status_code, dict(resp.headers), resp.content)


_transport: Transport = _requests_transport
_recorder: Recorder | None = None


def set_transport(transport: Transport | None) -> None:
    """Install a fake transport (tests); None restores the real one."""
    global _transport
    _transport = transport if transport is not None else _requests_transport


def set_recorder(recorder: Recorder | None) -> None:
    """Call `recorder(method, url)` for every request that passed `check()`; None disables."""
    global _recorder
    _recorder = recorder


def _send(policy: EgressPolicy, method: str, url: str, headers: Mapping[str, str], body: bytes | None,
          connect_timeout: float, read_timeout: float) -> Response:
    verb = method.upper()
    check(policy, verb, url)
    if _recorder is not None:
        _recorder(verb, url)
    resp = _transport(verb, url, headers=dict(headers), body=body, connect_timeout=connect_timeout,
                      read_timeout=read_timeout)
    return Response(int(resp.status), {str(k).lower(): str(v) for k, v in dict(resp.headers).items()},
                    bytes(resp.body or b""))


def request(policy: EgressPolicy, method: str, url: str, *, headers: Mapping[str, str] | None = None,
            json_body: Any = None, connect_timeout: float = CONNECT_TIMEOUT_S,
            read_timeout: float = READ_TIMEOUT_S) -> Response:
    """`check()`, record, then send via the active transport. Returns any HTTP status (no raising on 4xx/5xx).

    Raises:
        Blocked("INTERNAL_ERROR"): egress not allowlisted.
        EgressNotSent: connection could not be established.
        EgressUnknownOutcome: timeout or drop after sending.
    """
    sent_headers = dict(headers or {})
    body = None
    if json_body is not None:
        body = _json.dumps(json_body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if not any(k.lower() == "content-type" for k in sent_headers):
            sent_headers["Content-Type"] = "application/json"
    return _send(policy, method, url, sent_headers, body, connect_timeout, read_timeout)


def retry_after_seconds(headers: Mapping[str, str], default: float) -> float:
    """Seconds to wait from `retry-after-ms`, `x-ms-retry-after-ms` or `retry-after` (seconds),
    capped at `MAX_RETRY_AFTER_S`; `default` when none parses."""
    lower = {str(k).lower(): str(v) for k, v in headers.items()}
    for name, scale in (("retry-after-ms", 1000.0), ("x-ms-retry-after-ms", 1000.0), ("retry-after", 1.0)):
        try:
            value = float(lower[name]) / scale
        except (KeyError, ValueError):
            continue
        return max(0.0, min(value, MAX_RETRY_AFTER_S))
    return max(0.0, min(default, MAX_RETRY_AFTER_S))


# --------------------------------------------------------------------------- azure.core adapter

def search_transport(policy: EgressPolicy) -> Any:
    """An `azure.core` HTTP transport for `SearchClient(transport=...)` that routes every request
    through `check()` and the active transport."""
    from azure.core.pipeline.transport import HttpTransport
    from azure.core.rest._http_response_impl import HttpResponseImpl
    from azure.core.utils import CaseInsensitiveDict

    class _Response(HttpResponseImpl):
        def __init__(self, request: Any, resp: Response) -> None:
            headers = CaseInsensitiveDict(resp.headers)
            super().__init__(request=request, internal_response=resp, status_code=resp.status,
                             reason=http.client.responses.get(resp.status, ""),
                             content_type=headers.get("content-type"), headers=headers,
                             stream_download_generator=None)
            self._content = resp.body
            self._is_stream_consumed = True

        def body(self) -> bytes:
            return self._content or b""

        def close(self) -> None:
            self._is_closed = True

    class _PolicyTransport(HttpTransport):
        def __enter__(self) -> _PolicyTransport:
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def open(self) -> None:
            return None

        def close(self) -> None:
            return None

        def send(self, request: Any, **kwargs: Any) -> Any:
            body = getattr(request, "content", None)
            if body is None:
                body = getattr(request, "body", None) or getattr(request, "data", None)
            if isinstance(body, str):
                body = body.encode("utf-8")
            elif body is not None and not isinstance(body, bytes):
                body = _json.dumps(body).encode("utf-8")
            resp = _send(policy, request.method, request.url, dict(request.headers), body,
                         float(kwargs.get("connection_timeout") or CONNECT_TIMEOUT_S),
                         float(kwargs.get("read_timeout") or READ_TIMEOUT_S))
            return _Response(request, resp)

    return _PolicyTransport()
