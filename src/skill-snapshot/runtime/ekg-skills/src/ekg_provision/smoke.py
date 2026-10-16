"""Synthetic, client-side data-plane check; not an EKG Build or Consume adapter."""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

from ekg_core.execution import ApprovalRequired
from ekg_core.models import ProvisioningSpec, stable_id
from .journal import _write_json
from .planner import plan
from .public_test import validate_public_test


class SmokeError(RuntimeError):
    pass


_SAFE_ERROR_CODES = frozenset({
    "AuthenticationFailed", "AuthorizationFailed", "BadRequest", "Conflict",
    "Forbidden", "IndexNotFound", "InvalidApiVersion", "InvalidField",
    "InvalidIndexDefinition", "InvalidParameter", "InvalidRequest",
    "InvalidRequestParameter", "MissingRequiredParameter", "OperationNotAllowed",
    "PreconditionFailed", "ResourceNotFound", "Unauthorized",
})


@dataclass(frozen=True)
class SmokeSpec:
    smoke_id: str
    container: str
    vpn_egress_ip: str | None = None
    embedding_deployment: str | None = None


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    body: bytes
    error_code: str | None = None

    def json(self) -> dict[str, Any]:
        value = json.loads(self.body)
        if not isinstance(value, dict):
            raise SmokeError("unexpected data-plane JSON response")
        return value

    def header(self, name: str) -> str | None:
        return next((value for key, value in self.headers.items()
                     if key.lower() == name.lower()), None)


class Transport(Protocol):
    def request(self, method: str, url: str, scope: str, *,
                body: bytes | None = None, headers: dict[str, str] | None = None) -> Response: ...


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request: Request, fp: Any, code: int,
                         msg: str, headers: Any, newurl: str) -> None:
        return None


class AzureTransport:
    def __init__(self, credential: Any) -> None:
        self.credential = credential
        self.opener = build_opener(_NoRedirect)

    def request(self, method: str, url: str, scope: str, *,
                body: bytes | None = None, headers: dict[str, str] | None = None) -> Response:
        if not url.startswith("https://"):
            raise SmokeError("data-plane transport requires HTTPS")
        token = self.credential.get_token(scope).token
        request = Request(url, data=body, method=method, headers={
            "Content-Type": "application/json" if body is not None else "application/octet-stream",
            **(headers or {}),
            "Authorization": f"Bearer {token}",
        })
        try:
            with self.opener.open(request, timeout=30) as result:
                return Response(result.status, dict(result.headers), result.read())
        except HTTPError as error:
            headers = dict(error.headers)
            code = next((value for key, value in headers.items()
                         if key.lower() == "x-ms-error-code"), None)
            try:
                if code not in _SAFE_ERROR_CODES:
                    body = error.read(8193)
                    if len(body) <= 8192:
                        try:
                            payload = json.loads(body)
                        except (ValueError, UnicodeError):
                            payload = None
                        if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
                            code = payload["error"].get("code")
            finally:
                error.close()
            return Response(error.code, {}, b"",
                            code if isinstance(code, str) and code in _SAFE_ERROR_CODES else None)


def smoke_plan(spec: ProvisioningSpec, smoke: SmokeSpec) -> dict[str, Any]:
    validate_public_test(spec)
    if spec.public_test is None:
        raise ValueError("smoke requires the explicitly approved public-test mode")
    if not isinstance(smoke, SmokeSpec) or not re.fullmatch(r"[0-9a-f]{12}", smoke.smoke_id):
        raise ValueError("smoke ID must be twelve lowercase hexadecimal characters")
    if not isinstance(smoke.container, str) or not re.fullmatch(
        r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", smoke.container
    ) or "--" in smoke.container:
        raise ValueError("smoke requires an existing, approved Storage container name")
    if spec.public_test.mode == "ip_allowlist":
        if smoke.vpn_egress_ip not in spec.public_test.egress_ips:
            raise ValueError("smoke VPN egress IP must be in the approved public-test allowlist")
        if len(spec.public_test.egress_ips) != 1:
            raise ValueError("smoke requires one exact VPN egress IP to prove effective ingress")
    elif smoke.vpn_egress_ip is not None:
        raise ValueError("entra_only smoke must not specify a VPN egress IP")
    if smoke.embedding_deployment is not None and (
        not isinstance(smoke.embedding_deployment, str)
        or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}", smoke.embedding_deployment)
    ):
        raise ValueError("invalid approved OpenAI embedding deployment name")
    return {
        "plan_id": stable_id("public-smoke-plan", {
            "provision_plan_id": plan(spec).plan_id, "smoke": asdict(smoke),
        }),
        "provision_plan_id": plan(spec).plan_id,
        "index": f"ekg-proof-{smoke.smoke_id}",
        "blob": f"ekg-proof-{smoke.smoke_id}.txt",
        "container": smoke.container,
        "embedding_deployment": smoke.embedding_deployment,
        "operations": [
            {"action": "preflight", "resources": ["ARM foundation", "Blob container",
                                                  "Search index list"],
             "requires_approval": False},
            *([{"action": "embed", "resource": smoke.embedding_deployment,
                "requires_approval": True}] if smoke.embedding_deployment else []),
            {"action": "upload_read_conditional_delete",
             "resource": f"{smoke.container}/ekg-proof-{smoke.smoke_id}.txt",
             "requires_approval": True},
            {"action": "create_push_query_conditional_delete", "resource": f"ekg-proof-{smoke.smoke_id}",
             "requires_approval": True},
        ],
        "warnings": [
            "Separate approval is required for data-plane writes; this is not an EKG Build/Consume proof.",
            "The Storage container and optional embedding model deployment must already exist.",
            "An uncertain write leaves resources for manual review; never infer ownership from a later GET.",
        ],
    }


def _require(response: Response, statuses: tuple[int, ...], step: str) -> Response:
    if response.status not in statuses:
        code = f" ({response.error_code})" if response.error_code in _SAFE_ERROR_CODES else ""
        raise SmokeError(f"{step}: HTTP {response.status}{code}; no result is treated as verified")
    return response


def _json(data: dict[str, Any]) -> bytes:
    return json.dumps(data, separators=(",", ":")).encode("utf-8")


def _prepare_smoke_run(
    spec: ProvisioningSpec, smoke: SmokeSpec, desired: dict[str, Any],
    transport: Transport, inspection: dict[str, Any],
) -> tuple[str, str, str, str, str, str, str, dict[str, str], str, list[Any] | None]:
    if inspection.get("plan_id") != desired["provision_plan_id"] or any(
        item.get("status") != "present" for item in inspection.get("resources", {}).values()
    ) or len(inspection.get("resources", {})) != 4:
        raise SmokeError("foundation inspection is missing or differs from the approved plan")
    for name in ("search_service", "storage_account", "openai_resource"):
        resource = inspection["resources"].get(f"create-{name}", {})
        if (resource.get("auth_posture") != spec.public_test.mode
            or resource.get("public_network_access") != "Enabled"):
            raise SmokeError(f"{name}: authenticated public ARM posture is not verified")
    search = f"https://{spec.search_name}.search.windows.net"
    blob = (f"https://{spec.storage_name}.blob.core.windows.net/"
            f"{smoke.container}/{desired['blob']}")
    index = f"{search}/indexes('{desired['index']}')?api-version=2024-07-01"
    create_index = f"{search}/indexes?api-version=2024-07-01"
    docs = (f"{search}/indexes('{desired['index']}')/docs/"
            "search.index?api-version=2024-07-01")
    query = (f"{search}/indexes('{desired['index']}')/docs/"
             "search.post.search?api-version=2024-07-01")
    scope_storage = "https://storage.azure.com/.default"
    scope_search = "https://search.azure.com/.default"
    scope_openai = "https://ai.azure.com/.default"
    storage_headers = {"x-ms-version": "2023-11-03",
                       "x-ms-date": datetime.now(timezone.utc).strftime(
                           "%a, %d %b %Y %H:%M:%S GMT"
                       )}
    container_url = (f"https://{spec.storage_name}.blob.core.windows.net/"
                     f"{smoke.container}?restype=container")
    _require(transport.request("HEAD", container_url, scope_storage,
                               headers=storage_headers), (200,), "Storage container access probe")
    _require(transport.request(
        "GET", create_index, scope_search,
    ), (200,), "Search authenticated network-access probe")
    if transport.request("HEAD", blob, scope_storage, headers=storage_headers).status != 404:
        raise SmokeError("isolated Blob name is not confirmed absent")
    if transport.request("GET", index, scope_search).status != 404:
        raise SmokeError("isolated Search index name is not confirmed absent")
    content = f"Synthetic EKG proof marker {smoke.smoke_id}. No customer data."
    embedding = None
    if smoke.embedding_deployment:
        url = f"https://{spec.openai_name}.openai.azure.com/openai/v1/embeddings"
        response = _require(transport.request(
            "POST", url, scope_openai,
            body=_json({"model": smoke.embedding_deployment, "input": content}),
        ), (200,), "OpenAI embedding data plane")
        items = response.json().get("data")
        if not isinstance(items, list) or len(items) != 1 or not isinstance(
            items[0].get("embedding"), list
        ) or not items[0]["embedding"] or not all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in items[0]["embedding"]
        ):
            raise SmokeError("OpenAI embedding data plane returned no usable vector")
        embedding = items[0]["embedding"]
    return blob, index, create_index, docs, query, scope_storage, scope_search, storage_headers, content, embedding


def _run_smoke_writes(
    transport: Transport, smoke: SmokeSpec, desired: dict[str, Any],
    targets: tuple[str, str, str, str, str, str, str, dict[str, str], str, list[Any] | None],
    record_path: Path, record: dict[str, Any],
) -> None:
    blob, index, create_index, docs, query, scope_storage, scope_search, storage_headers, content, embedding = targets
    def mark(operation: str, status: str, **details: Any) -> None:
        record["operations"][operation] = status
        record.update(details)
        _write_json(record_path, record)
    mark("blob", "attempted")
    uploaded = _require(transport.request(
        "PUT", blob, scope_storage, body=content.encode(),
        headers={**storage_headers, "Content-Type": "text/plain; charset=utf-8",
                 "x-ms-blob-type": "BlockBlob", "If-None-Match": "*"},
    ), (201,), "Blob upload")
    blob_etag = uploaded.header("ETag")
    if not blob_etag:
        raise SmokeError("Blob upload did not return an ownership ETag")
    got = _require(transport.request("GET", blob, scope_storage, headers=storage_headers),
                   (200,), "Blob read")
    if got.body != content.encode() or got.header("ETag") != blob_etag:
        raise SmokeError("Blob content/ETag changed; manual cleanup required")
    mark("blob", "verified", blob_etag=blob_etag)
    fields: list[dict[str, Any]] = [
        {"name": "id", "type": "Edm.String", "key": True, "filterable": True},
        {"name": "content", "type": "Edm.String", "searchable": True},
    ]
    definition: dict[str, Any] = {"name": desired["index"], "fields": fields}
    document: dict[str, Any] = {"id": smoke.smoke_id, "content": content}
    if embedding is not None:
        fields.append({
            "name": "embedding", "type": "Collection(Edm.Single)",
            "searchable": True, "dimensions": len(embedding),
            "vectorSearchProfile": "proof-vector",
        })
        definition["vectorSearch"] = {
            "algorithms": [{"name": "proof-hnsw", "kind": "hnsw"}],
            "profiles": [{"name": "proof-vector", "algorithm": "proof-hnsw"}],
        }
        document["embedding"] = embedding
    mark("index", "attempted")
    created = _require(transport.request(
        "POST", create_index, scope_search, body=_json(definition),
    ), (200, 201,), "Search index create")
    index_etag = created.header("ETag") or created.json().get("@odata.etag")
    if not isinstance(index_etag, str) or not index_etag:
        raise SmokeError("Search index create did not return an ownership ETag")
    read_index = _require(transport.request("GET", index, scope_search),
                          (200,), "Search index read")
    if (read_index.header("ETag") or read_index.json().get("@odata.etag")) != index_etag:
        raise SmokeError("Search index ETag changed; manual cleanup required")
    mark("index", "created_verified", index_etag=index_etag)
    mark("document", "attempted")
    uploaded_doc = _require(transport.request(
        "POST", docs, scope_search,
        body=_json({"value": [{"@search.action": "upload", **document}]}),
    ), (200, 201, 207,), "Search document push")
    statuses = uploaded_doc.json().get("value")
    if not isinstance(statuses, list) or len(statuses) != 1 or (
        statuses[0].get("key") != smoke.smoke_id
        or statuses[0].get("status") is not True
    ):
        raise SmokeError("Search document push was not confirmed")
    mark("document", "push_confirmed")
    request: dict[str, Any] = {
        "search": smoke.smoke_id, "top": 1, "select": "id,content",
    }
    if embedding is not None:
        request = {
            "search": "*", "top": 1, "select": "id,content",
            "vectorQueries": [{
                "kind": "vector", "vector": embedding,
                "fields": "embedding", "k": 1,
            }],
        }
    deadline = time.monotonic() + 30
    while True:
        results = _require(transport.request(
            "POST", query, scope_search, body=_json(request),
        ), (200,), "Search query").json().get("value")
        if results or time.monotonic() >= deadline:
            break
        time.sleep(2)
    if not isinstance(results, list) or len(results) != 1 or (
        results[0].get("id") != smoke.smoke_id
        or results[0].get("content") != content
    ):
        raise SmokeError("Search query did not return the exact synthetic document")
    mark("document", "query_verified")
    reread = _require(transport.request("GET", index, scope_search),
                      (200,), "Search index ownership check")
    if (reread.header("ETag") or reread.json().get("@odata.etag")) != index_etag:
        raise SmokeError("Search index changed before cleanup; manual review required")
    deadline = time.monotonic() + 30
    while True:
        inventory = _require(transport.request(
            "POST", query, scope_search,
            body=_json({"search": "*", "count": True, "top": 2,
                        "select": "id,content"}),
        ), (200,), "Search isolated document inspection").json()
        documents = inventory.get("value")
        count = inventory.get("@odata.count")
        if not isinstance(documents, list) or not isinstance(count, int) or (
            isinstance(count, bool) or count < 0
        ):
            raise SmokeError("Search isolated document inspection is invalid; manual review required")
        if len(documents) > 1 or count > 1 or any(
            not isinstance(item, dict) or item.get("id") != smoke.smoke_id
            or item.get("content") != content for item in documents
        ):
            raise SmokeError("Search index has unexpected content; manual review required")
        if len(documents) == count == 1:
            break
        if time.monotonic() >= deadline:
            raise SmokeError(
                "Search isolated document inspection timed out without the exact "
                "synthetic document; manual review required"
            )
        time.sleep(2)
    reread = _require(transport.request("GET", index, scope_search),
                      (200,), "Search index ownership recheck")
    if (reread.header("ETag") or reread.json().get("@odata.etag")) != index_etag:
        raise SmokeError("Search index changed before cleanup; manual review required")
    mark("index_delete", "attempted")
    _require(transport.request(
        "DELETE", index, scope_search, headers={"If-Match": index_etag},
    ), (200, 204,), "Search index delete")
    if transport.request("GET", index, scope_search).status != 404:
        raise SmokeError("Search index deletion is unconfirmed; manual review required")
    mark("index_delete", "verified")
    reread_blob = _require(transport.request(
        "GET", blob, scope_storage, headers=storage_headers,
    ), (200,), "Blob ownership check")
    if reread_blob.header("ETag") != blob_etag or reread_blob.body != content.encode():
        raise SmokeError("Blob changed before cleanup; manual review required")
    mark("blob_delete", "attempted")
    _require(transport.request(
        "DELETE", blob, scope_storage,
        headers={**storage_headers, "If-Match": blob_etag},
    ), (202, 204,), "Blob delete")
    if transport.request("GET", blob, scope_storage, headers=storage_headers).status != 404:
        raise SmokeError("Blob deletion is unconfirmed; manual review required")
    mark("blob_delete", "verified")


def run_smoke(
    spec: ProvisioningSpec, smoke: SmokeSpec, *, approved_smoke_plan_id: str,
    confirmed: bool, transport: Transport, inspection: dict[str, Any],
    journal_dir: str | Path,
) -> dict[str, Any]:
    if not confirmed:
        raise ApprovalRequired("synthetic data-plane smoke requires explicit write confirmation")
    desired = smoke_plan(spec, smoke)
    if approved_smoke_plan_id != desired["plan_id"]:
        raise ApprovalRequired(f"explicit approval of smoke plan {desired['plan_id']} is required")
    targets = _prepare_smoke_run(spec, smoke, desired, transport, inspection)

    run_id = uuid4().hex
    record_path = Path(journal_dir) / f"smoke-{run_id}.json"
    record: dict[str, Any] = {
        "run_id": run_id, "smoke_plan_id": desired["plan_id"],
        "provision_plan_id": desired["provision_plan_id"],
        "container": smoke.container, "blob": desired["blob"], "index": desired["index"],
        "operations": {"blob": "pending", "index": "pending", "index_delete": "pending",
                       "blob_delete": "pending"},
    }
    _write_json(record_path, record)
    try:
        _run_smoke_writes(transport, smoke, desired, targets, record_path, record)
    except Exception as error:
        failure = str(error) if isinstance(error, SmokeError) else type(error).__name__
        raise SmokeError(
            f"smoke run {run_id} is incomplete; inspect journal {record_path} and "
            f"manually review uncertain resources ({failure})"
        ) from error
    return {
        "status": "verified_and_cleaned" if smoke.embedding_deployment
                  else "partial_no_openai_deployment",
        "openai": "embedding_verified" if smoke.embedding_deployment
                  else "not_tested_no_deployment",
        "search": "push_query_index_deleted", "storage": "blob_read_deleted",
        "run_id": run_id, "journal_path": str(record_path),
    }
