from __future__ import annotations

import threading
import time
from typing import Any, Protocol
from urllib.parse import quote

from ekg_core import az_identity
from ekg_core.telemetry import HttpStats


class QueryAdapter(Protocol):
    def search(self, name: str, query: str, *, top: int = 10,
               filter: str | None = None, vector: list[float] | None = None,
               vector_field: str = "embedding"
               ) -> list[dict[str, Any]]: ...
    def embed(self, text: str) -> list[float]: ...
    def graph_search(self, name: str, gql: str, *, provenance: str = "ids"
                     ) -> dict[str, Any]: ...
    def lookup_chunk(self, index: str, chunk_id: str) -> dict[str, Any] | None: ...


class AzureQueryAdapter:
    """Read-only Azure Search and OpenAI data-plane client."""

    def __init__(self, search_endpoint: str, *, openai_endpoint: str | None = None,
                 embedding_deployment: str | None = None, credential: Any = None,
                 search_api_version: str = "2024-07-01") -> None:
        if not search_endpoint.startswith("https://") or (
            openai_endpoint and not openai_endpoint.startswith("https://")
        ):
            raise ValueError("query endpoints must use HTTPS")
        self.credential = credential if credential is not None else az_identity.cli_credential()
        self.search_endpoint = search_endpoint.rstrip("/")
        self.openai_endpoint = openai_endpoint.rstrip("/") if openai_endpoint else None
        self.embedding_deployment = embedding_deployment
        self.search_api_version = search_api_version
        self._tokens: dict[str, Any] = {}
        self._token_lock = threading.Lock()
        self.http_stats = HttpStats()

    def _token(self, scope: str) -> str:
        # AzureCliCredential spawns `az` per call; reuse a token until shortly before expiry.
        with self._token_lock:
            cached = self._tokens.get(scope)
            if cached is not None and getattr(cached, "expires_on", 0) - time.time() > 300:
                return cached.token
            issued = self.credential.get_token(scope)
            if isinstance(getattr(issued, "expires_on", None), (int, float)):
                self._tokens[scope] = issued
            return issued.token

    def search(self, name: str, query: str, *, top: int = 10,
               filter: str | None = None, vector: list[float] | None = None,
               vector_field: str = "embedding"
               ) -> list[dict[str, Any]]:
        import httpx
        url = (f"{self.search_endpoint}/indexes('{quote(name, safe='')}')/"
               f"docs/search.post.search?api-version={self.search_api_version}")
        body: dict[str, Any] = {"search": query, "top": top}
        if filter:
            body["filter"] = filter
        if vector is not None:
            body["vectorQueries"] = [{
                "kind": "vector", "vector": vector, "fields": vector_field, "k": top,
            }]
        token = self._token("https://search.azure.com/.default")
        response = httpx.post(url, json=body, headers={"Authorization": f"Bearer {token}"}, timeout=60)
        self.http_stats.observe_response(response)
        if response.is_error:
            _raise_search_error("query", name, response.status_code)
        return response.json()["value"]

    def graph_search(self, name: str, gql: str, *,
                     provenance: str = "ids") -> dict[str, Any]:
        if self.search_api_version != "2026-08-01-preview":
            raise ValueError("native graph query requires Search 2026-08-01-preview")
        if provenance != "ids":
            raise ValueError("only provenance IDs are supported without service confirmation")
        import httpx
        url = (f"{self.search_endpoint}/indexes('{quote(name, safe='')}')/"
               f"docs/search.graph?api-version={self.search_api_version}")
        token = self._token("https://search.azure.com/.default")
        response = httpx.post(
            url, json={"gql": gql, "provenance": {"kind": provenance},
                       "includeDiagnostics": True},
            headers={"Authorization": f"Bearer {token}"}, timeout=60,
        )
        self.http_stats.observe_response(response)
        if response.is_error:
            _raise_search_error("graph query", name, response.status_code)
        result = response.json()
        if not isinstance(result, dict) or not isinstance(result.get("value"), list):
            raise RuntimeError("Search graph response is malformed")
        return result

    def lookup_chunk(self, index: str, chunk_id: str) -> dict[str, Any] | None:
        if self.search_api_version != "2026-08-01-preview":
            raise ValueError("managed chunk lookup requires Search 2026-08-01-preview")
        import httpx
        safe_id = quote(chunk_id.replace("'", "''"), safe="")
        url = (f"{self.search_endpoint}/indexes('{quote(index, safe='')}')/"
               f"docs('{safe_id}')?api-version={self.search_api_version}")
        token = self._token("https://search.azure.com/.default")
        response = httpx.get(
            url, headers={"Authorization": f"Bearer {token}"}, timeout=60,
        )
        self.http_stats.observe_response(response)
        if response.status_code == 404:
            return None
        if response.is_error:
            _raise_search_error("chunk lookup", index, response.status_code)
        result = response.json()
        if not isinstance(result, dict) or result.get("uid") != chunk_id:
            raise RuntimeError("Search chunk lookup returned an unexpected document")
        return result

    def embed(self, text: str) -> list[float]:
        import httpx
        if not self.openai_endpoint or not self.embedding_deployment:
            raise ValueError("vector retrieval requires an OpenAI endpoint and embedding deployment")
        url = (f"{self.openai_endpoint}/openai/deployments/"
               f"{quote(self.embedding_deployment, safe='')}/embeddings?api-version=2024-10-21")
        token = self._token("https://cognitiveservices.azure.com/.default")
        response = httpx.post(
            url, json={"input": text}, headers={"Authorization": f"Bearer {token}"}, timeout=60,
        )
        self.http_stats.observe_response(response)
        if response.is_error:
            raise RuntimeError(f"OpenAI embedding failed: HTTP {response.status_code}")
        result = response.json()
        self.http_stats.add_usage(result.get("usage"))
        return result["data"][0]["embedding"]


def _raise_search_error(operation: str, index: str, status: int) -> None:
    if status == 403:
        raise RuntimeError(
            f"Search {operation} was denied (HTTP 403) on index {index}. The signed-in "
            "identity needs the Search Index Data Reader role on that index or its service. "
            "Fix: az role assignment create --assignee <your-object-id> --role "
            f"\"Search Index Data Reader\" --scope <search-service-resource-id>/indexes/{index}")
    raise RuntimeError(f"Search {operation} failed: HTTP {status}")
