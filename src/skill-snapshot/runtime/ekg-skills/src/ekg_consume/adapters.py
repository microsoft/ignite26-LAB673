from __future__ import annotations

import threading
import time
from typing import Any, Protocol
from urllib.parse import quote

from ekg_core import az_identity
from ekg_core.telemetry import HttpStats

_GRAPH_SEARCH_API_VERSIONS = {
    "2026-08-01-preview",
    "2026-11-01-preview",
}
_SEARCH_DATA_API_VERSION = "2026-04-01"


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
        self.credential = az_identity.cached(
            credential if credential is not None else az_identity.cli_credential())
        self.search_endpoint = search_endpoint.rstrip("/")
        self.openai_endpoint = openai_endpoint.rstrip("/") if openai_endpoint else None
        self.embedding_deployment = embedding_deployment
        self.search_api_version = search_api_version
        self._tokens: dict[str, Any] = {}
        self._token_lock = threading.Lock()
        self._search_clients: dict[str, Any] = {}
        self._search_client_lock = threading.Lock()
        self._openai_client: Any = None
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
        from azure.core.exceptions import HttpResponseError
        from azure.search.documents.models import VectorizedQuery

        kwargs: dict[str, Any] = {"search_text": query, "top": top}
        kwargs["raw_response_hook"] = self._observe_sdk_response
        if filter is not None:
            kwargs["filter"] = filter
        if vector is not None:
            kwargs["vector_queries"] = [
                VectorizedQuery(vector=vector, fields=vector_field, k_nearest_neighbors=top)
            ]
        try:
            return [dict(item) for item in self._search_client(name).search(**kwargs)]
        except HttpResponseError as error:
            _raise_search_error("query", name, error.status_code or 0)

    def graph_search(self, name: str, gql: str, *,
                     provenance: str = "ids") -> dict[str, Any]:
        if self.search_api_version not in _GRAPH_SEARCH_API_VERSIONS:
            raise ValueError("native graph query requires a supported preview Search API version")
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
        from azure.core.exceptions import HttpResponseError, ResourceNotFoundError

        try:
            result = dict(self._search_client(index).get_document(key=chunk_id))
        except ResourceNotFoundError:
            return None
        except HttpResponseError as error:
            _raise_search_error("chunk lookup", index, error.status_code or 0)
        if not isinstance(result, dict) or result.get("uid") != chunk_id:
            raise RuntimeError("Search chunk lookup returned an unexpected document")
        return result

    def embed(self, text: str) -> list[float]:
        if not self.openai_endpoint or not self.embedding_deployment:
            raise ValueError("vector retrieval requires an OpenAI endpoint and embedding deployment")
        result = self._openai().embeddings.create(
            model=self.embedding_deployment, input=text,
        )
        usage = result.usage.model_dump() if result.usage else None
        self.http_stats.add_usage(usage)
        return list(result.data[0].embedding)

    def _search_client(self, index: str) -> Any:
        with self._search_client_lock:
            client = self._search_clients.get(index)
            if client is None:
                from azure.search.documents import SearchClient

                client = SearchClient(
                    endpoint=self.search_endpoint, index_name=index, credential=self.credential,
                    api_version=_SEARCH_DATA_API_VERSION,
                )
                self._search_clients[index] = client
            return client

    def _openai(self) -> Any:
        if self._openai_client is None:
            import httpx
            from openai import OpenAI

            transport = httpx.Client(
                timeout=60, follow_redirects=False,
                event_hooks={"response": [self.http_stats.observe_embedding_response]},
            )
            self._openai_client = OpenAI(
                base_url=f"{self.openai_endpoint}/openai/v1/",
                api_key=lambda: self._token("https://ai.azure.com/.default"),
                http_client=transport,
                max_retries=0,
            )
        return self._openai_client

    def _observe_sdk_response(self, response: Any) -> None:
        self.http_stats.observe_response(getattr(response, "http_response", response))


def _raise_search_error(operation: str, index: str, status: int) -> None:
    if status == 403:
        raise RuntimeError(
            f"Search {operation} was denied (HTTP 403) on index {index}. The signed-in "
            "identity needs the Search Index Data Reader role on that index or its service. "
            "Fix: az role assignment create --assignee <your-object-id> --role "
            f"\"Search Index Data Reader\" --scope <search-service-resource-id>/indexes/{index}")
    raise RuntimeError(f"Search {operation} failed: HTTP {status}")
