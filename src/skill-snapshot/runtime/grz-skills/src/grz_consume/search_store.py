"""Query-only Azure Search adapter for a physical, published sidecar index."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import unquote, urlparse

from grz_core.contracts import ContractError
from .endpoint import validate_search_endpoint

SEARCH_API_VERSION = "2026-04-01"

try:
    from azure.core.pipeline.policies import SansIOHTTPPolicy
except ImportError:  # pragma: no cover
    class SansIOHTTPPolicy:  # type: ignore[no-redef]
        pass


class QueryOnlyPolicy(SansIOHTTPPolicy):
    """Client-side guard that permits only document reads on one physical index."""

    def __init__(self, physical_index: str, auth: str = "entra", *, endpoint: str | None = None):
        if not isinstance(physical_index, str) or not physical_index:
            raise ContractError("QUERY_ONLY_VIOLATION", "Physical index binding is required")
        self.physical_index = physical_index
        self.auth = auth
        self.endpoint = validate_search_endpoint(endpoint) if endpoint is not None else None

    def on_response(self, request: Any, response: Any) -> None:
        status = getattr(getattr(response, "http_response", response), "status_code", None)
        if status != 403:
            return
        if self.auth == "query-key":
            raise ContractError("READ_ACCESS_DENIED", f"The query key can't read {self.physical_index}. "
                                "Next step: ask the builder for a current query key for this service.")
        raise ContractError("READ_ACCESS_DENIED", f"This identity can't read {self.physical_index}; it needs "
                            "Search Index Data Reader on that index. Next step: ask the builder to grant "
                            f"Search Index Data Reader on {self.physical_index}.")

    def on_request(self, request: Any) -> None:
        http = getattr(request, "http_request", request)
        method = str(getattr(http, "method", "")).upper()
        url = str(getattr(http, "url", ""))
        parsed = urlparse(url)
        if self.endpoint is not None and f"{parsed.scheme}://{parsed.netloc}" != self.endpoint:
            raise ContractError("QUERY_ONLY_VIOLATION", "Request is not bound to the configured Search origin")
        path = unquote(parsed.path)
        lowered = path.lower()
        if "/aliases" in lowered or lowered.rstrip("/").endswith("/indexes"):
            raise ContractError("QUERY_ONLY_VIOLATION", "Admin Search paths are not permitted")
        marker = f"/indexes/{self.physical_index}/"
        quoted_marker = f"/indexes('{self.physical_index}')/"
        if marker not in path and quoted_marker not in path:
            raise ContractError("QUERY_ONLY_VIOLATION", "Request is not bound to the descriptor physical index")
        if "/docs/index" in lowered:
            raise ContractError("QUERY_ONLY_VIOLATION", "Document indexing is not permitted")
        allowed = (
            lowered.endswith("/docs/search") or "/docs/search" in lowered
            or lowered.endswith("/docs/$count") or "/docs/$count" in lowered
            or (method == "GET" and "/docs(" in lowered)
        )
        if method not in {"GET", "POST"} or not allowed:
            raise ContractError("QUERY_ONLY_VIOLATION", "Only docs search/count/lookup reads are permitted")



def _select_without_vectors(schema_version: str = "grz-sidecar-v1") -> list[str]:
    from grz_adapters.sidecar_schema import load_sidecar_schema

    excluded = {"chunk_vector"}
    if schema_version == "grz-sidecar-v1":
        excluded.add("community_ids")
    return [field["name"] for field in load_sidecar_schema()["fields"] if field["name"] not in excluded]


def _search(client: Any, **kwargs: Any) -> Any:
    return client.search(**kwargs)


def _literal(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContractError("QUERY_INVALID", "Filter identities must be nonempty strings")
    return "'" + value.replace("'", "''") + "'"


class AzureSearchReadStore:
    """Accept an injected SearchClient factory; never create an admin client.

    The supplied credential must be a query key or query-only token. Search
    pages use ``sort_key gt last`` rather than an unbounded skip offset.
    """

    def __init__(self, endpoint: str, credential: Any, page_size: int = 500, *, policies: list[Any] | None = None):
        endpoint = validate_search_endpoint(endpoint)
        if type(page_size) is not int or not 1 <= page_size <= 1000:
            raise ContractError("PAGE_SIZE_INVALID", "Azure page size must be 1..1000")
        try:
            from azure.search.documents import SearchClient
        except ImportError as exc:
            raise RuntimeError("Install the azure optional dependency to use Azure Search") from exc
        self.endpoint = endpoint
        self.credential = credential
        self.page_size = page_size
        self._client_type = SearchClient
        self.policies = list(policies or [])
        self._schema_versions: dict[tuple[str, str], str] = {}

    def bind_schema(self, physical_index: str, generation_id: str, schema_version: str) -> None:
        from grz_core.contracts import SIDECAR_VERSIONS

        if schema_version not in SIDECAR_VERSIONS:
            raise ContractError("SCHEMA_UNSUPPORTED", "Unsupported sidecar projection")
        if not hasattr(self, "_schema_versions"):
            self._schema_versions = {}
        key = (physical_index, generation_id)
        if key in self._schema_versions and self._schema_versions[key] != schema_version:
            raise ContractError("SIDECAR_INTEGRITY_FAILED", "Published schema changed during browsing")
        self._schema_versions[key] = schema_version

    def _select(self, physical_index: str, generation_id: str, kind: str) -> list[str]:
        if kind == "manifest":
            return ["id", "sort_key", "kind", "generation_id", "visibility", "payload"]
        version = getattr(self, "_schema_versions", {}).get((physical_index, generation_id), "grz-sidecar-v1")
        return _select_without_vectors(version)

    def _client(self, physical_index: str) -> Any:
        return self._client_type(
            endpoint=self.endpoint, index_name=physical_index, credential=self.credential,
            audience="https://search.azure.com", api_version=SEARCH_API_VERSION, permit_redirects=False,
            per_call_policies=[*self.policies, QueryOnlyPolicy(physical_index, endpoint=self.endpoint)],
        )

    def _query(
        self, physical_index: str, kind: str, generation_id: str, *,
        limit: int, after: str | None = None, field: str | None = None,
        value: str | None = None, level: int | None = None,
    ) -> list[dict[str, Any]]:
        if kind not in ("representative", "membership", "evidence", "manifest"):
            raise ContractError("QUERY_INVALID", "Unsupported sidecar document kind")
        if not isinstance(physical_index, str) or not physical_index:
            raise ContractError("QUERY_INVALID", "Physical index is required")
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ContractError("PAGE_SIZE_INVALID", "Azure query limit must be 1..1000")
        if field is not None and field not in ("community_id", "chunk_id", "parent_id"):
            raise ContractError("QUERY_INVALID", "Unsupported filtered lookup field")
        if (field is None) != (value is None):
            raise ContractError("QUERY_INVALID", "Lookup field and value must occur together")
        if level is not None and (type(level) is not int or level < 0):
            raise ContractError("LEVEL_INVALID", "level must be nonnegative")
        where = f"kind eq {_literal(kind)} and generation_id eq {_literal(generation_id)}"
        if field is not None:
            where += f" and {field} eq {_literal(value)}"
        if level is not None:
            where += f" and level eq {level}"
        if after is not None:
            where += f" and sort_key gt {_literal(after)}"
        client = self._client(physical_index)
        try:
            page = [
                {key: val for key, val in dict(item).items()
                 if not key.startswith("@search.") and val is not None and val != []}
                for item in _search(client,
                    search_text="*", filter=where, order_by=["sort_key asc"],
                    top=limit, include_total_count=False, select=self._select(physical_index, generation_id, kind),
                )
            ]
        finally:
            client.close()
        if len(page) > limit:
            raise ContractError("SIDECAR_INTEGRITY_FAILED", "Search returned an oversized page")
        last = after
        for row in page:
            key = row.get("sort_key")
            if not isinstance(key, str) or (last is not None and key <= last):
                raise ContractError("SIDECAR_INTEGRITY_FAILED", "Unordered Search sort keys")
            last = key
            if kind == "manifest" and isinstance(row.get("payload"), str):
                try:
                    row["payload"] = json.loads(row["payload"])
                except ValueError as exc:
                    raise ContractError("SIDECAR_INTEGRITY_FAILED", "Malformed manifest JSON") from exc
        return page

    def count(
        self, physical_index: str, kind: str, generation_id: str,
        community_id: str | None = None, level: int | None = None,
    ) -> int:
        """Server-side filtered count without retrieving document bodies."""
        if kind not in ("representative", "membership", "evidence", "manifest"):
            raise ContractError("QUERY_INVALID", "Unsupported sidecar document kind")
        if not isinstance(physical_index, str) or not physical_index:
            raise ContractError("QUERY_INVALID", "Physical index is required")
        where = f"kind eq {_literal(kind)} and generation_id eq {_literal(generation_id)}"
        if community_id is not None:
            where += f" and community_id eq {_literal(community_id)}"
        if level is not None:
            if type(level) is not int or level < 0:
                raise ContractError("LEVEL_INVALID", "level must be a nonnegative integer")
            where += f" and level eq {level}"
        client = self._client(physical_index)
        try:
            result = _search(client,
                search_text="*",
                filter=where,
                top=0, include_total_count=True, select=["id"],
            )
            count = result.get_count()
        finally:
            client.close()
        if type(count) is not int or count < 0:
            raise ContractError("SIDECAR_INTEGRITY_FAILED", "Search did not return an exact kind count")
        return count

    def page(
        self, physical_index: str, kind: str, generation_id: str, limit: int, *,
        after: str | None = None, community_id: str | None = None,
        level: int | None = None, parent_id: str | None = None,
        chunk_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """One bounded keyset page; no skip/deep-offset or arbitrary OData input."""
        if sum(value is not None for value in (community_id, parent_id, chunk_id)) > 1:
            raise ContractError("QUERY_INVALID", "Only one key filter is permitted")
        return self._query(
            physical_index, kind, generation_id, limit=limit, after=after,
            field=("community_id" if community_id is not None else
                   "parent_id" if parent_id is not None else "chunk_id" if chunk_id is not None else None),
            value=(community_id if community_id is not None else
                   parent_id if parent_id is not None else chunk_id), level=level,
        )

    def lookup(
        self, physical_index: str, kind: str, generation_id: str,
        field: str, value: str,
    ) -> list[dict[str, Any]]:
        """Return at most two rows to detect ambiguous point lookups."""
        return self._query(physical_index, kind, generation_id, limit=2, field=field, value=value)

    def evidence_for_chunks(
        self, physical_index: str, generation_id: str, chunk_ids: list[str],
    ) -> list[dict[str, Any]]:
        """Resolve at most 32 evidence keys per query; no unbounded fan-out."""
        if not chunk_ids or len(chunk_ids) > 32 or len(chunk_ids) != len(set(chunk_ids)):
            raise ContractError("QUERY_INVALID", "Evidence lookup requires 1..32 unique chunk IDs")
        if not isinstance(physical_index, str) or not physical_index:
            raise ContractError("QUERY_INVALID", "Physical index is required")
        where = (
            f"kind eq 'evidence' and generation_id eq {_literal(generation_id)} and ("
            + " or ".join(f"chunk_id eq {_literal(chunk)}" for chunk in chunk_ids) + ")"
        )
        client = self._client(physical_index)
        try:
            rows = [
                {key: val for key, val in dict(item).items()
                 if not key.startswith("@search.") and val is not None and val != []}
                for item in _search(client,
                    search_text="*", filter=where, order_by=["chunk_id asc"],
                    top=len(chunk_ids) + 1, include_total_count=False,
                    select=self._select(physical_index, generation_id, "evidence"),
                )
            ]
        finally:
            client.close()
        if len(rows) > len(chunk_ids):
            raise ContractError("SIDECAR_INTEGRITY_FAILED", "Duplicate chunk evidence")
        return rows


    def rank_evidence(
        self, physical_index: str, generation_id: str, community_id: str, vector: list[float], top: int,
    ) -> list[dict[str, Any]]:
        """One vector Search request over evidence rows in a community."""
        if not isinstance(physical_index, str) or not physical_index:
            raise ContractError("QUERY_INVALID", "Physical index is required")
        if type(top) is not int or not 1 <= top <= 200:
            raise ContractError("LIMIT_INVALID", "rank top must be 1..200")
        try:
            from azure.search.documents.models import VectorizedQuery
        except ImportError as exc:
            raise RuntimeError("Install the azure optional dependency to use Azure Search") from exc
        where = (
            f"kind eq 'evidence' and generation_id eq {_literal(generation_id)} "
            f"and community_ids/any(c: c eq {_literal(community_id)})"
        )
        client = self._client(physical_index)
        try:
            rows = []
            # Pure vector query: adding search_text would make it hybrid and return RRF scores, not cosine.
            for item in _search(client,
                search_text=None, filter=where, top=top, include_total_count=False,
                vector_queries=[VectorizedQuery(vector=vector, fields="chunk_vector", k_nearest_neighbors=top, exhaustive=True)],
                select=["chunk_id", "source_id", "community_ids", "id", "sort_key", "kind", "generation_id", "visibility"],
            ):
                row = {key: val for key, val in dict(item).items() if val is not None and val != []}
                score = row.pop("@search.score", None)
                if score is not None:
                    row["score"] = float(score)
                rows.append(row)
        finally:
            client.close()
        if len(rows) > top:
            raise ContractError("SIDECAR_INTEGRITY_FAILED", "Search returned too many ranked rows")
        return rows

    def documents(self, physical_index: str, kind: str, generation_id: str) -> list[dict[str, Any]]:
        """Full scan used once to validate the canonical manifest and hierarchy."""
        rows: list[dict[str, Any]] = []
        last: str | None = None
        while True:
            page = self.page(physical_index, kind, generation_id, self.page_size, after=last)
            rows.extend(page)
            if len(page) < self.page_size:
                return rows
            last = page[-1]["sort_key"]
