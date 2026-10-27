"""Small REST helpers shared by the LAB673 preview notebooks."""

import json
import os
from pathlib import Path
import re
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


API_VERSION = "2026-11-01-preview"
DEFAULT_PREVIEW_INDEX_PREFIX = "lab673-preview-cocoarynth"


def load_environment(repo_root: Path) -> None:
    env_file = repo_root / ".env"
    if env_file.is_file():
        from dotenv import load_dotenv

        load_dotenv(env_file, override=False)


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value or "your-" in value:
        raise RuntimeError(f"Set {name} in your environment or the root .env file.")
    return value


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class SearchRestClient:
    def __init__(self, endpoint: str, admin_key: str, resource_prefix: str):
        origin = urlsplit(endpoint)
        if (
            origin.scheme != "https"
            or not origin.hostname
            or origin.username
            or origin.password
            or origin.port not in (None, 443)
            or origin.path not in ("", "/")
            or origin.query
            or origin.fragment
        ):
            raise ValueError("The preview endpoint must be an HTTPS service origin.")
        if not re.fullmatch(r"lab673-[a-z0-9](?:[a-z0-9-]{0,40}[a-z0-9])?", resource_prefix):
            raise ValueError("Use a unique lab673- resource prefix of at most 49 characters.")
        self.endpoint = endpoint.rstrip("/")
        self.admin_key = admin_key
        self.resource_prefix = resource_prefix
        self.owner = f"LAB673 REST notebooks: {resource_prefix} | "
        self.opener = build_opener(_NoRedirects())

    def request(self, method, path, body=None, *, headers=None, missing_ok=False):
        if path.startswith("/") or not re.fullmatch(r"[A-Za-z0-9/$'()_-]+", path):
            raise ValueError("Use a relative Search REST path, not a URL.")
        request = Request(
            f"{self.endpoint}/{path}?api-version={API_VERSION}",
            method=method,
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "api-key": self.admin_key,
                **(headers or {}),
            },
        )
        try:
            with self.opener.open(request, timeout=120) as response:
                if response.status == 206:
                    raise RuntimeError("Search returned HTTP 206: these results are incomplete.")
                raw = response.read()
                if not raw:
                    return None
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    raise RuntimeError("Search returned a response that is not valid JSON.") from None
        except HTTPError as error:
            if missing_ok and error.code == 404:
                return None
            raw = error.read()
            try:
                detail = json.loads(raw)["error"]["message"]
            except (json.JSONDecodeError, KeyError, TypeError):
                detail = "The service did not return a JSON error message."
            if not isinstance(detail, str):
                detail = "The service did not return a text error message."
            for secret in (self.admin_key, os.environ.get("AZURE_OPENAI_KEY", "")):
                if secret:
                    detail = detail.replace(secret, "[REDACTED]")
            guidance = {
                402: " Ask the service owner about the Standard Knowledge Retrieval prerequisite.",
                412: " Another request changed this resource. Rerun the cell to read its current state.",
                429: " The service is busy or its allowance is exhausted. Retry later.",
            }.get(error.code, "")
            raise RuntimeError(f"Search returned HTTP {error.code}: {detail}{guidance}") from None

    def _owned_headers(self, path, current):
        kind, _, name = path.partition("/")
        if (
            kind not in ("knowledgesources", "knowledgebases")
            or not re.fullmatch(r"[a-z0-9-]+", name)
            or not name.startswith(f"{self.resource_prefix}-")
        ):
            raise ValueError("Only this notebook prefix's knowledge sources and bases may be changed.")
        if current is None:
            return {"If-None-Match": "*"}
        if not (current.get("description") or "").startswith(self.owner):
            raise RuntimeError(f"Refusing to change a resource not owned by these notebooks: {path}")
        etag = current.get("@odata.etag")
        if not etag:
            raise RuntimeError(f"Cannot safely change a resource without its ETag: {path}")
        return {"If-Match": etag}

    def put_owned(self, path, definition):
        current = self.request("GET", path, missing_ok=True)
        headers = self._owned_headers(path, current)
        body = {
            **definition,
            "description": self.owner + definition.get("description", ""),
        }
        self.request("PUT", path, body, headers=headers)

    def delete_owned(self, path):
        current = self.request("GET", path, missing_ok=True)
        headers = self._owned_headers(path, current)
        if current is not None:
            self.request("DELETE", path, headers=headers)
