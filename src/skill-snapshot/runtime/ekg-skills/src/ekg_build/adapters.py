from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timezone
from typing import Any, Protocol
from urllib.parse import quote

from ekg_core import az_identity
from ekg_core.telemetry import HttpStats


class DataPlane(Protocol):
    def ensure_container(self, name: str) -> None: ...
    def stage(self, container: str, name: str, data: bytes, *, overwrite: bool = False) -> None: ...
    def get_index(self, name: str) -> dict[str, Any] | None: ...
    def create_index(self, schema: dict[str, Any]) -> None: ...
    def upload(self, name: str, documents: list[dict[str, Any]]) -> None: ...
    def count(self, name: str) -> int: ...
    def search(self, name: str, query: str, *, top: int = 10,
               filter: str | None = None, vector: list[float] | None = None) -> list[dict[str, Any]]: ...
    def search_page(self, name: str, *, skip: int, top: int) -> list[dict[str, Any]]: ...
    def embed(self, text: str) -> list[float]: ...
    def service_statistics(self) -> dict[str, Any]: ...
    def inspect_search_service(self, resource_id: str, tenant_id: str) -> dict[str, Any]: ...
    def get_knowledge_source(self, name: str) -> dict[str, Any] | None: ...
    def create_knowledge_source(self, definition: dict[str, Any]) -> dict[str, str]: ...
    def knowledge_source_status(self, name: str) -> dict[str, Any]: ...
    def get_resource(self, kind: str, name: str) -> dict[str, Any] | None: ...
    def graph_search(self, name: str, gql: str) -> dict[str, Any]: ...


class SearchRequestError(RuntimeError):
    def __init__(self, method: str, status: int) -> None:
        self.status = status
        super().__init__(f"Search {method} failed: HTTP {status}")


class AzureDataPlane:
    """Entra-authenticated REST client; credentials never enter build evidence/descriptors."""

    def __init__(self, *, search_endpoint: str, storage_endpoint: str | None = None,
                 openai_endpoint: str | None = None, embedding_deployment: str | None = None,
                 credential: Any = None,
                 search_api_version: str = "2024-07-01") -> None:
        for endpoint in (search_endpoint, storage_endpoint, openai_endpoint):
            if endpoint is not None and not endpoint.startswith("https://"):
                raise ValueError("Azure endpoints must use HTTPS")
        self.credential = az_identity.cached(
            credential if credential is not None else az_identity.cli_credential())
        self.search_endpoint = search_endpoint.rstrip("/")
        self.storage_endpoint = storage_endpoint.rstrip("/") if storage_endpoint else None
        self.openai_endpoint = openai_endpoint.rstrip("/") if openai_endpoint else None
        self.embedding_deployment = embedding_deployment
        self.search_api_version = search_api_version
        self._openai_client: Any = None
        self.http_stats = HttpStats()

    def _request(self, method: str, url: str, scope: str, *, json_body: Any = None,
                 data: bytes | None = None, headers: dict[str, str] | None = None,
                 missing_ok: bool = False, expected_status: int | None = None) -> Any:
        import httpx
        token = self.credential.get_token(scope).token
        response = httpx.request(
            method, url, json=json_body, content=data,
            headers={"Authorization": f"Bearer {token}", **(headers or {})}, timeout=90,
        )
        self.http_stats.observe_response(response)
        if missing_ok and response.status_code == 404:
            return None
        if response.is_error:
            # Azure response bodies may contain customer data; never include them in errors.
            raise SearchRequestError(method, response.status_code)
        if expected_status is not None and response.status_code != expected_status:
            raise RuntimeError(f"Search {method} returned unexpected HTTP {response.status_code}")
        return response.json() if response.content and response.headers.get(
            "content-type", ""
        ).startswith("application/json") else None

    def _search_url(self, path: str) -> str:
        return f"{self.search_endpoint}/{path}?api-version={self.search_api_version}"

    def _index_path(self, name: str) -> str:
        return f"indexes('{quote(name, safe='')}')"

    def ensure_container(self, name: str) -> None:
        if not self.storage_endpoint:
            raise ValueError("storage_endpoint is required for corpus staging")
        url = f"{self.storage_endpoint}/{quote(name, safe='')}?restype=container"
        import httpx
        token = self.credential.get_token("https://storage.azure.com/.default").token
        headers = {"Authorization": f"Bearer {token}", "x-ms-version": "2023-11-03"}
        headers["x-ms-date"] = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
        observed = httpx.head(url, headers=headers, timeout=90)
        self.http_stats.observe_response(observed)
        if observed.status_code == 404:
            created = httpx.put(url, headers={**headers, "If-None-Match": "*"}, timeout=90)
            self.http_stats.observe_response(created)
            if created.status_code != 201:
                raise RuntimeError(f"Storage container create failed: HTTP {created.status_code}")
        elif observed.status_code != 200:
            raise RuntimeError(f"Storage container inspect failed: HTTP {observed.status_code}")

    def _blob(self, method: str, container: str, name: str, *, endpoint: str | None = None,
              **kwargs: Any) -> Any:
        endpoint = endpoint or self.storage_endpoint
        if not endpoint:
            raise ValueError("storage_endpoint is required for corpus staging")
        headers = {"x-ms-version": "2023-11-03",
                   "x-ms-date": datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT"),
                   **kwargs.pop("headers", {})}
        return self._request(method, f"{endpoint}/{quote(container, safe='')}/"
                             f"{quote(name, safe='')}", "https://storage.azure.com/.default",
                             headers=headers, **kwargs)

    def stage(self, container: str, name: str, data: bytes, *, overwrite: bool = False) -> None:
        # Builds never overwrite; content updates replace a changed document in place.
        # Content-MD5 makes Storage reject a body that differs from these bytes in transit.
        digest = base64.b64encode(hashlib.md5(data, usedforsecurity=False).digest()).decode()
        guard = {} if overwrite else {"If-None-Match": "*"}
        try:
            self._blob("PUT", container, name, data=data,
                       headers={"x-ms-blob-type": "BlockBlob", "Content-MD5": digest,
                                "Content-Type": "application/octet-stream", **guard})
        except SearchRequestError as error:
            if overwrite or error.status != 409 or self._blob_md5(container, name) != digest:
                raise
            # The same bytes are already staged (for example by an interrupted attempt).

    def _blob_md5(self, container: str, name: str) -> str | None:
        import httpx
        url = (f"{self.storage_endpoint}/{quote(container, safe='')}/{quote(name, safe='')}")
        token = self.credential.get_token("https://storage.azure.com/.default").token
        response = httpx.head(url, headers={
            "Authorization": f"Bearer {token}", "x-ms-version": "2023-11-03",
            "x-ms-date": datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT"),
        }, timeout=90)
        self.http_stats.observe_response(response)
        return response.headers.get("Content-MD5") if response.status_code == 200 else None

    def delete_blob(self, container: str, name: str, *, etag: str | None = None,
                    endpoint: str | None = None) -> None:
        self._blob("DELETE", container, name, endpoint=endpoint, missing_ok=True,
                   headers={"If-Match": etag} if etag else {})

    def get_index(self, name: str) -> dict[str, Any] | None:
        return self._request("GET", self._search_url(self._index_path(name)),
                             "https://search.azure.com/.default", missing_ok=True)

    def create_index(self, schema: dict[str, Any]) -> None:
        self._request("POST", self._search_url("indexes"), "https://search.azure.com/.default",
                      json_body=schema)

    def upload(self, name: str, documents: list[dict[str, Any]]) -> None:
        if not documents:
            return
        value = self._request(
            "POST", self._search_url(f"{self._index_path(name)}/docs/search.index"),
            "https://search.azure.com/.default",
            json_body={"value": [{"@search.action": "upload", **doc} for doc in documents]},
        )
        failures = [item for item in value["value"] if not item.get("status")]
        if failures:
            raise RuntimeError(f"Search rejected {len(failures)} document(s)")

    def count(self, name: str) -> int:
        import httpx
        url = self._search_url(f"{self._index_path(name)}/docs/$count")
        token = self.credential.get_token("https://search.azure.com/.default").token
        response = httpx.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=90)
        self.http_stats.observe_response(response)
        if response.is_error:
            raise RuntimeError(f"Search count failed: HTTP {response.status_code}")
        return int(response.text)

    def search(self, name: str, query: str, *, top: int = 10,
               filter: str | None = None, vector: list[float] | None = None) -> list[dict[str, Any]]:
        body: dict[str, Any] = {"search": query, "top": top}
        if filter:
            body["filter"] = filter
        if vector is not None:
            body["vectorQueries"] = [{"kind": "vector", "vector": vector,
                                      "fields": "embedding", "k": top}]
        value = self._request(
            "POST", self._search_url(f"{self._index_path(name)}/docs/search.post.search"),
            "https://search.azure.com/.default", json_body=body,
        )
        return value["value"]

    def search_page(self, name: str, *, skip: int, top: int) -> list[dict[str, Any]]:
        if (not isinstance(skip, int) or isinstance(skip, bool) or skip < 0
                or not isinstance(top, int) or isinstance(top, bool) or not 1 <= top <= 1000):
            raise ValueError("generated content page requires skip >= 0 and top 1..1000")
        result = self._request(
            "POST", self._search_url(f"{self._index_path(name)}/docs/search.post.search"),
            "https://search.azure.com/.default",
            json_body={"search": "*", "skip": skip, "top": top,
                       "select": "uid,blob_url"},
        )
        if not isinstance(result, dict) or not isinstance(result.get("value"), list):
            raise RuntimeError("generated content page is malformed")
        return result["value"]

    def embed(self, text: str) -> list[float]:
        if not self.embedding_deployment:
            raise ValueError("embedding_deployment is required for vector retrieval")
        if not self.openai_endpoint:
            raise ValueError("openai_endpoint is required")
        result = self._openai().embeddings.create(
            model=self.embedding_deployment, input=text,
        )
        usage = result.usage.model_dump() if result.usage else None
        self.http_stats.add_usage(usage)
        return list(result.data[0].embedding)

    def _openai(self) -> Any:
        if self._openai_client is None:
            import httpx
            from openai import OpenAI

            transport = httpx.Client(
                timeout=90, follow_redirects=False,
                event_hooks={"response": [self.http_stats.observe_embedding_response]},
            )
            self._openai_client = OpenAI(
                base_url=f"{self.openai_endpoint}/openai/v1/",
                api_key=lambda: self.credential.get_token(
                    "https://ai.azure.com/.default").token,
                http_client=transport,
                max_retries=0,
            )
        return self._openai_client

    def service_statistics(self) -> dict[str, Any]:
        return self._request("GET", self._search_url("servicestats"),
                             "https://search.azure.com/.default")

    def inspect_search_service(self, resource_id: str, tenant_id: str) -> dict[str, Any]:
        az_identity.active_az_identity(tenant_id, resource_id.split("/")[2])
        scope = "https://management.azure.com/.default"
        token = self.credential.get_token(scope).token
        if not az_identity.token_in_tenant(token, tenant_id):
            raise RuntimeError("ARM credential tenant differs from the explicitly requested build tenant")
        return self._request(
            "GET", f"https://management.azure.com{resource_id}?api-version=2025-05-01",
            scope,
        )

    def get_knowledge_source(self, name: str) -> dict[str, Any] | None:
        return self._request(
            "GET", self._search_url(f"knowledgesources('{quote(name, safe='')}')"),
            "https://search.azure.com/.default", missing_ok=True,
        )

    def create_knowledge_source(self, definition: dict[str, Any]) -> dict[str, str]:
        result = self._request(
            "POST", self._search_url("knowledgesources"),
            "https://search.azure.com/.default", json_body=definition, expected_status=201,
        )
        if not isinstance(result, dict):
            raise RuntimeError("Knowledge Source create receipt is missing")
        binding = result.get("azureBlobParameters")
        if isinstance(binding, dict):
            observed = binding.get("connectionString")
            expected = (definition.get("azureBlobParameters") or {}).get("connectionString")
            if (observed is not None and observed != expected
                    and (not isinstance(observed, str)
                         or observed.casefold() != "<redacted>")):
                raise RuntimeError("Knowledge Source create response has a different Storage binding")
        name, kind, etag = result.get("name"), result.get("kind"), result.get("@odata.etag")
        if (name != definition.get("name") or kind != definition.get("kind")
                or not isinstance(etag, str) or not etag.strip()):
            raise RuntimeError("Knowledge Source create receipt lacks exact identity or ETag")
        return {"name": name, "kind": kind, "etag": etag}

    def knowledge_source_status(self, name: str) -> dict[str, Any]:
        return self._request(
            "GET", self._search_url(f"knowledgesources('{quote(name, safe='')}')/status"),
            "https://search.azure.com/.default",
        )

    def get_resource(self, kind: str, name: str) -> dict[str, Any] | None:
        if kind not in {"datasources", "skillsets", "indexers"}:
            raise ValueError("unsupported generated Search resource")
        return self._request(
            "GET", self._search_url(f"{kind}('{quote(name, safe='')}')"),
            "https://search.azure.com/.default", missing_ok=True,
        )

    def list_resources(self, kind: str) -> list[dict[str, Any]]:
        result = self._request("GET", self._search_url(kind), "https://search.azure.com/.default")
        if not isinstance(result, dict) or not isinstance(result.get("value"), list):
            raise RuntimeError(f"Search {kind} list is malformed")
        return result["value"]

    def resource_exists(self, kind: str, name: str) -> bool:
        return self._request(
            "GET", self._search_url(f"{kind}('{quote(name, safe='')}')"),
            "https://search.azure.com/.default", missing_ok=True,
        ) is not None

    def delete_resource(self, kind: str, name: str, etag: str) -> bool:
        """ETag-conditional delete; False when already absent, error on any other change."""
        import httpx
        if not etag:
            raise ValueError("retire deletes require the reviewed ETag")
        token = self.credential.get_token("https://search.azure.com/.default").token
        response = httpx.delete(
            self._search_url(f"{kind}('{quote(name, safe='')}')"),
            headers={"Authorization": f"Bearer {token}", "If-Match": etag}, timeout=90,
        )
        self.http_stats.observe_response(response)
        if response.status_code == 404:
            return False
        if response.status_code == 412:
            raise RuntimeError(f"{name} changed since review (ETag mismatch); not deleted")
        if response.status_code != 204:
            raise SearchRequestError("DELETE", response.status_code)
        return True

    def scan(self, name: str, fields: str, key: str) -> list[dict[str, Any]]:
        """Every document's selected fields, paged by key order."""
        rows: list[dict[str, Any]] = []
        while True:
            body: dict[str, Any] = {"search": "*", "select": fields, "top": 1000, "orderby": f"{key} asc"}
            if rows:
                body["filter"] = f"{key} gt '{rows[-1][key].replace(chr(39), chr(39) * 2)}'"
            page = self._request(
                "POST", self._search_url(f"{self._index_path(name)}/docs/search.post.search"),
                "https://search.azure.com/.default", json_body=body)["value"]
            rows += page
            if len(page) < 1000:
                return rows

    def delete_documents(self, name: str, key: str, keys: list[str]) -> None:
        for start in range(0, len(keys), 1000):
            value = self._request(
                "POST", self._search_url(f"{self._index_path(name)}/docs/search.index"),
                "https://search.azure.com/.default",
                json_body={"value": [{"@search.action": "delete", key: k}
                                     for k in keys[start:start + 1000]]})
            if any(not item.get("status") for item in value["value"]):
                raise RuntimeError(f"Search rejected a document delete in {name}")

    def run_indexer(self, name: str) -> None:
        self._request("POST", self._search_url(f"indexers('{quote(name, safe='')}')/search.run"),
                      "https://search.azure.com/.default", expected_status=202)

    def indexer_status(self, name: str) -> dict[str, Any]:
        return self._request(
            "GET", self._search_url(f"indexers('{quote(name, safe='')}')/search.status"),
            "https://search.azure.com/.default",
        )

    def arm_read(self, resource_path: str, api_version: str, *, tenant_id: str,
                 params: dict[str, str] | None = None) -> dict[str, Any] | None:
        """Tenant-checked ARM GET; never issues a write."""
        from urllib.parse import urlencode

        if not resource_path.startswith("/subscriptions/"):
            raise ValueError("ARM reads require an exact resource ID")
        scope = "https://management.azure.com/.default"
        token = self.credential.get_token(scope).token
        if not az_identity.token_in_tenant(token, tenant_id):
            raise RuntimeError("ARM credential tenant differs from the explicitly requested tenant")
        query = urlencode({"api-version": api_version, **(params or {})})
        return self._request("GET", f"https://management.azure.com{resource_path}?{query}",
                             scope, missing_ok=True)

    def arm_write(self, method: str, resource_path: str, api_version: str, *, tenant_id: str,
                  body: Any = None, conflict_ok: bool = False) -> Any:
        """Tenant-checked ARM PUT/DELETE for approved role assignments only."""
        if method not in ("PUT", "DELETE") or "/providers/Microsoft.Authorization/roleAssignments/" \
                not in resource_path or not resource_path.startswith("/subscriptions/"):
            raise ValueError("ARM writes are limited to exact role assignments")
        scope = "https://management.azure.com/.default"
        if not az_identity.token_in_tenant(self.credential.get_token(scope).token, tenant_id):
            raise RuntimeError("ARM credential tenant differs from the explicitly requested tenant")
        try:
            return self._request(method, f"https://management.azure.com{resource_path}"
                                 f"?api-version={api_version}", scope, json_body=body,
                                 missing_ok=method == "DELETE")
        except SearchRequestError as error:
            # 409 RoleAssignmentExists: the same grant exists under another name.
            if conflict_ok and error.status == 409:
                return None
            raise

    def monitor_metrics(self, resource_id: str, names: tuple[str, ...], start: Any, end: Any,
                        interval: str, *, tenant_id: str, split: str | None = None,
                        ) -> dict[str, Any]:
        """Azure Monitor metrics for one resource over one window (read-only)."""
        params = {
            "metricnames": ",".join(names), "interval": interval,
            "timespan": f"{start.strftime('%Y-%m-%dT%H:%M:%SZ')}/{end.strftime('%Y-%m-%dT%H:%M:%SZ')}",
            "aggregation": "Total,Average,Maximum",
        }
        if split:
            params["$filter"] = " and ".join(f"{name} eq '*'" for name in split.split(","))
        return self.arm_read(f"{resource_id}/providers/Microsoft.Insights/metrics",
                             "2023-10-01", tenant_id=tenant_id, params=params) or {}

    def graph_search(self, name: str, gql: str) -> dict[str, Any]:
        if self.search_api_version != "2026-08-01-preview":
            raise ValueError("native graph probe requires Search API 2026-08-01-preview")
        result = self._request(
            "POST", self._search_url(f"{self._index_path(name)}/docs/search.graph"),
            "https://search.azure.com/.default",
            json_body={"gql": gql, "provenance": {"kind": "ids"},
                       "includeDiagnostics": True},
        )
        if not isinstance(result, dict) or not isinstance(result.get("value"), list):
            raise RuntimeError("native graph probe returned malformed rows")
        return result
