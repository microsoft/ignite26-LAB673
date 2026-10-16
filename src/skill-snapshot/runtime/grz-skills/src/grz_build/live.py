"""Live Azure Build wiring with injectable boundaries for offline tests."""

from __future__ import annotations

import time
import re
from typing import Any, Callable
from urllib.parse import quote

from grz_adapters.azure_build import AzureBuildStore
from grz_adapters.azure_publication import PublicationApproval
from grz_adapters.azure_source import SourceExportApproval, SourceFields, get_field
from grz_build.reader_grants import ArmRequest, ReaderGrants, default_arm_request
from grz_core.azure_auth import MANAGEMENT_SCOPE, create_default_credential, get_token, validate_tenant
from grz_core.contracts import ContractError, SourceIdentity, digest, validate_alias


API_VERSION = "2026-04-01"
ARM_VERSION = "2023-11-01"


def service_endpoint(service: str) -> str:
    if not service or any(c in service for c in "/: "):
        raise ContractError("SEARCH_SERVICE_INVALID", "--search-service must be a Search service name")
    return f"https://{service}.search.windows.net"


def slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
    value = re.sub(r"-+", "-", value)
    if not value:
        raise ContractError("ALIAS_INVALID", "Vector field must produce a nonempty alias slug")
    return value


def default_alias(dataset: str, vector_field: str) -> str:
    validate_dataset(dataset)
    name = f"grz-{dataset}-{slug(vector_field)}-active"
    if len(name) > 128:
        raise ContractError("ALIAS_INVALID", "Derived GRZ alias exceeds Search 128 character limit")
    return name


def corpus_warnings(document_count: int) -> list[str]:
    return ["below recommended 2,000 chunks for clustering quality"] if document_count < 2000 else []


def validate_dataset(dataset: str) -> None:
    if not dataset or dataset != dataset.lower() or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in dataset):
        raise ContractError("DATASET_INVALID", "--dataset must be a lowercase Search-safe slug")


def target_index_for_plan(dataset: str, planned_without_target: dict[str, Any]) -> str:
    validate_dataset(dataset)
    basis = digest(planned_without_target)
    name = f"grz-{dataset}-{basis[:20]}"
    if len(name) > 128:
        raise ContractError("PUBLICATION_TARGET_INVALID", "Target generation index name exceeds Search limit")
    return name


def _field_defs(index: Any) -> dict[str, Any]:
    return {get_field(field, "name"): field for field in get_field(index, "fields", [])}


def vector_metadata(index: Any, vector_field: str) -> dict[str, Any]:
    fields = _field_defs(index)
    field = fields.get(vector_field)
    if field is None:
        raise ContractError("SOURCE_FIELDS_INVALID", "Mapped vector field is absent")
    return {
        "name": vector_field,
        "dimension": get_field(field, "vector_search_dimensions", get_field(field, "vectorSearchDimensions", get_field(field, "dimensions"))),
        "profile": get_field(field, "vector_search_profile_name", get_field(field, "vectorSearchProfile")),
        "algorithm": _algorithm_for_profile(index, get_field(field, "vector_search_profile_name", get_field(field, "vectorSearchProfile"))),
    }


def _algorithm_for_profile(index: Any, profile_name: str | None) -> str | None:
    search = get_field(index, "vector_search", get_field(index, "vectorSearch"))
    profiles = get_field(search, "profiles", []) if search is not None else []
    algorithms = get_field(search, "algorithms", []) if search is not None else []
    algorithm_name = None
    for profile in profiles:
        if get_field(profile, "name") == profile_name:
            algorithm_name = get_field(profile, "algorithm_configuration_name", get_field(profile, "algorithm"))
            break
    for algorithm in algorithms:
        if get_field(algorithm, "name") == algorithm_name:
            return get_field(algorithm, "kind")
    return algorithm_name


def definition_fingerprint(index: Any, mapped_fields: SourceFields) -> str:
    fields = _field_defs(index)
    names = sorted(set([mapped_fields.key, mapped_fields.text, mapped_fields.source,
                        mapped_fields.vector, mapped_fields.scan_key, *mapped_fields.security_fields]))
    return digest({
        "name": get_field(index, "name"),
        "fields": [{
            "name": name, "type": str(get_field(fields[name], "type")),
            "key": get_field(fields[name], "key"), "sortable": get_field(fields[name], "sortable"),
            "filterable": get_field(fields[name], "filterable"), "hidden": get_field(fields[name], "hidden"),
            "stored": get_field(fields[name], "stored"),
            "dimensions": get_field(fields[name], "vector_search_dimensions", get_field(fields[name], "vectorSearchDimensions", get_field(fields[name], "dimensions"))),
            "profile": get_field(fields[name], "vector_search_profile_name", get_field(fields[name], "vectorSearchProfile")),
        } for name in names if name in fields],
        "vector_algorithm": vector_metadata(index, mapped_fields.vector).get("algorithm"),
    })


def default_arm_get(url: str, bearer_token: str) -> dict[str, Any]:
    import requests
    response = requests.get(url, headers={"Authorization": f"Bearer {bearer_token}"}, timeout=30)
    if response.status_code == 404:
        raise ContractError("SEARCH_SERVICE_NOT_FOUND", "Search service resource was not found in the named subscription/RG")
    if response.status_code >= 400:
        raise ContractError("ARM_REQUEST_FAILED", f"ARM GET failed with status {response.status_code}")
    return response.json()


class LiveAzureBuildStore(AzureBuildStore):
    def __init__(self, *args: Any, arm: dict[str, Any], service_stats: dict[str, Any],
                 index_client: Any, endpoint: str, fields: SourceFields,
                 vector_query_factory: Any | None = None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.vector_query_factory = vector_query_factory
        self.reader_grants: ReaderGrants | None = None
        self.arm = arm
        self.service_stats = service_stats
        self.index_client = index_client
        self.endpoint = endpoint
        self.fields = fields

    def inspect(self, identity: SourceIdentity) -> dict[str, Any]:
        base = self.source.inspect(identity)
        index = self.index_client.get_index(identity.index)
        index_stats = self.index_stats(identity.index)
        headroom = headroom_snapshot(self.arm, self.service_stats, index_stats, base.get("source", identity.__dict__))
        vector = vector_metadata(index, self.fields.vector)
        result = {
            **base,
            "warnings": corpus_warnings(identity.expected_count),
            "arm": safe_arm_snapshot(self.arm),
            "index_stats": index_stats,
            "document_count": identity.expected_count,
            "vector": vector,
            "definition_fingerprint": definition_fingerprint(index, self.fields),
            "headroom": headroom,
        }
        return result

    def index_stats(self, index: str) -> Any:
        try:
            return self.index_client.get_index_statistics(index)
        except Exception as exc:
            raise ContractError("SEARCH_REQUEST_FAILED", "Cannot read Search index statistics") from exc

    def source_binding(self, inspected: dict[str, Any]) -> dict[str, Any]:
        binding = {
            "source_index": inspected["source"]["index"],
            "definition_fingerprint": inspected["definition_fingerprint"],
            "document_count": inspected["document_count"],
            "vector_field": inspected["vector"]["name"],
            "dimension": inspected["vector"]["dimension"],
        }
        if self.fields.visibility_basis != "per-document":
            # Only an attestation enters the binding, so per-document plan IDs stay as they were.
            binding["visibility_basis"] = self.fields.visibility_basis
        return binding

    def target_exists(self, index: str) -> bool:
        try:
            self.index_client.get_index(index)
            return True
        except Exception as exc:
            status = get_field(exc, "status_code", get_field(get_field(exc, "response"), "status_code"))
            if status == 404:
                return False
            raise

    def compatibility_probe(self, index: str, generation_id: str, representatives: list[dict[str, Any]], limit: int = 5) -> dict[str, Any]:
        vector_query = self.vector_query_factory
        if vector_query is None:
            try:
                from azure.search.documents.models import VectorizedQuery as vector_query
            except ImportError as exc:  # pragma: no cover
                raise ContractError("AZURE_DEPENDENCY_MISSING", "azure-search-documents is required for vector probe") from exc
        client = self.publisher.search_client(index)
        probes = []
        started = time.perf_counter()
        for doc in representatives[:limit]:
            filter_value = ("kind eq 'representative' and generation_id eq '" + generation_id.replace("'", "''")
                            + f"' and level eq {int(doc['level'])}")
            rows = list(client.search(
                search_text=None,
                vector_queries=[vector_query(vector=doc["centroid"], k_nearest_neighbors=1, fields="centroid", exhaustive=True)],
                filter=filter_value,
                select=["id", "kind", "community_id", "generation_id", "level"],
                top=1,
            ))
            top = dict(rows[0]) if rows else {}
            ok = top.get("id") == doc["id"]
            probes.append({"id": doc["id"], "top_id": top.get("id"), "ok": ok})
            if not ok:
                raise ContractError("VECTOR_PROBE_FAILED", "Exhaustive centroid query did not return the expected representative")
        return {"probes": probes, "timings_ms": {"vector_probe": int((time.perf_counter() - started) * 1000)}}


def safe_arm_snapshot(resource: dict[str, Any]) -> dict[str, Any]:
    sku = resource.get("sku") or {}
    props = resource.get("properties") or {}
    return {
        "id": resource.get("id"), "name": resource.get("name"), "location": resource.get("location"),
        "sku": sku.get("name") if isinstance(sku, dict) else sku,
        "replicaCount": props.get("replicaCount"), "partitionCount": props.get("partitionCount"),
        "disableLocalAuth": props.get("disableLocalAuth"),
    }


def _quota_counter(counters: dict[str, Any], name: str) -> tuple[int | None, int | None]:
    value = get_field(counters, name)
    if value is None:
        return None, None
    usage, quota = get_field(value, "usage"), get_field(value, "quota")
    return (usage if isinstance(usage, int) else None, quota if isinstance(quota, int) else None)


def _stat_counter(data: dict[str, Any], name: str) -> int:
    sdk_names = {"documentCount": "document_count", "storageSize": "storage_size",
                 "vectorIndexSize": "vector_index_size"}
    value = get_field(data, name, get_field(data, sdk_names.get(name, name)))
    if value is not None and not isinstance(value, int):
        usage = get_field(value, "usage", get_field(value, "value"))
        if isinstance(usage, int):
            return usage
    if isinstance(value, dict):
        for key in ("usage", "value"):
            if isinstance(value.get(key), int):
                return value[key]
    return value if isinstance(value, int) else 0


def headroom_snapshot(arm: dict[str, Any], service_stats: dict[str, Any], index_stats: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    counters = get_field(service_stats, "counters")
    limits = get_field(service_stats, "limits")
    if counters is None:
        raise ContractError("SEARCH_HEADROOM_INSUFFICIENT", "Search service stats counters are unavailable")
    index_count, index_quota = _quota_counter(counters, "indexesCount")
    storage_used, storage_quota = _quota_counter(counters, "storageSize")
    vector_used, vector_quota = _quota_counter(counters, "vectorIndexSize")
    max_storage_per_index = get_field(limits, "maxStoragePerIndex",
                                      get_field(limits, "max_storage_per_index"))
    required = (index_count, index_quota, storage_used, storage_quota, vector_used, vector_quota, max_storage_per_index)
    if any(not isinstance(value, int) for value in required):
        raise ContractError("SEARCH_HEADROOM_INSUFFICIENT", "Search index/storage/vector quotas must be known")
    source_storage = _stat_counter(index_stats, "storageSize")
    source_vector = _stat_counter(index_stats, "vectorIndexSize")
    dimension = int(source.get("dimension") or 1)
    count = int(source.get("expected_count") or 1)
    estimate = max(source_storage, count * (dimension * 4 + 1024) * 5)
    vector_estimate = max(source_vector, count * dimension * 4)
    free_indexes = max(index_quota - index_count, 0)
    free_storage = max(storage_quota - storage_used, 0)
    free_vector = max(vector_quota - vector_used, 0)
    ok = (free_indexes >= 1 and free_storage >= 2 * estimate and free_vector >= 2 * vector_estimate
          and estimate <= max_storage_per_index)
    snapshot = {
        "index_count": index_count, "index_quota": index_quota, "free_index_slots": free_indexes,
        "storage_used": storage_used, "storage_quota": storage_quota, "free_storage": free_storage,
        "vector_used": vector_used, "vector_quota": vector_quota, "free_vectorIndexSize": free_vector,
        "max_storage_per_index": max_storage_per_index,
        "estimated_bytes": estimate, "estimated_vector_bytes": vector_estimate,
        "sufficient": ok,
    }
    if not ok:
        raise ContractError("SEARCH_HEADROOM_INSUFFICIENT", "Search service lacks index, storage, vector or per-index headroom for the plan")
    return snapshot


def publication_approval(args: Any, endpoint: str, arm: dict[str, Any], service_stats: dict[str, Any],
                         index_client: Any, count: int, dimension: int) -> PublicationApproval:
    """Derive write attestations from this command's real inputs; read-only commands get none, so writes fail closed."""
    command = getattr(args, "command", None)
    writes = command == "apply" and bool(getattr(args, "confirm_writes", False))
    cutover = command == "publish" and bool(getattr(args, "approve_cutover", False))
    headroom = budget = write = cutover_approval = ""
    if writes or cutover:
        try:
            index_stats = index_client.get_index_statistics(args.source_index)
        except Exception as exc:
            raise ContractError("SEARCH_REQUEST_FAILED", "Cannot read source index statistics for publication approval") from exc
        snapshot = headroom_snapshot(arm, service_stats, index_stats, {"dimension": dimension, "expected_count": count})
        headroom = f"headroom:free_storage={snapshot['free_storage']}"
    if writes:
        budget_bytes = getattr(args, "approved_budget_bytes", None)
        if not isinstance(budget_bytes, int) or budget_bytes < 1:
            raise ContractError("BUDGET_APPROVAL_REQUIRED", "Live apply requires --approved-budget-bytes")
        budget, write = f"budget:{budget_bytes}", "confirm-writes"
    if cutover:
        budget, write, cutover_approval = "budget:alias-only", "approve-cutover", "approve-cutover"
    return PublicationApproval(args.tenant_id, endpoint, args.dataset, args.owner_approval, args.security_inspection,
                               headroom, budget, write, cutover_approval, args.alias)


def display_names(arm_get: Callable[[str, str], dict[str, Any]], management: str,
                  tenant_id: str, subscription_id: str) -> dict[str, str | None]:
    """Tenant and subscription display names for approval cards. Best effort: a failed lookup shows the ID prefix."""
    names: dict[str, str | None] = {"tenant_name": None, "subscription_name": None}
    try:
        sub = arm_get(f"https://management.azure.com/subscriptions/{quote(subscription_id, safe='')}?api-version=2022-12-01", management)
        if isinstance(sub.get("displayName"), str):
            names["subscription_name"] = sub["displayName"]
    except Exception:
        pass
    try:
        tenants = arm_get("https://management.azure.com/tenants?api-version=2022-12-01", management)
        match = next((t for t in tenants.get("value") or [] if t.get("tenantId") == tenant_id), None)
        if match and isinstance(match.get("displayName"), str):
            names["tenant_name"] = match["displayName"]
    except Exception:
        pass
    return names


def create_live_store(args: Any, *, credential: Any | None = None,
                      arm_get: Callable[[str, str], dict[str, Any]] = default_arm_get,
                      index_client_factory: Any | None = None, search_client_factory: Any | None = None,
                      vector_query_factory: Any | None = None,
                      arm_request: ArmRequest = default_arm_request) -> tuple[LiveAzureBuildStore, SourceIdentity, dict[str, Any]]:
    validate_dataset(args.dataset)
    if not getattr(args, "alias", None):
        args.alias = default_alias(args.dataset, args.vector_field)
    validate_alias(args.alias)
    endpoint = service_endpoint(args.search_service)
    credential = credential or create_default_credential()
    tenant = validate_tenant(credential, args.tenant_id)
    management = get_token(credential, MANAGEMENT_SCOPE, args.tenant_id)
    arm_url = (f"https://management.azure.com/subscriptions/{quote(args.subscription_id, safe='')}/resourceGroups/"
               f"{quote(args.resource_group, safe='')}/providers/Microsoft.Search/searchServices/"
               f"{quote(args.search_service, safe='')}?api-version={ARM_VERSION}")
    arm = arm_get(arm_url, management)
    props = arm.get("properties") or {}
    if arm.get("name") and arm.get("name") != args.search_service:
        raise ContractError("SEARCH_SERVICE_MISMATCH", "ARM returned a different Search service")
    if props.get("endpoint") and props.get("endpoint").rstrip("/") != endpoint:
        raise ContractError("SEARCH_SERVICE_MISMATCH", "ARM endpoint does not match --search-service")
    if index_client_factory is None or search_client_factory is None:
        try:
            from azure.search.documents import SearchClient
            from azure.search.documents.indexes import SearchIndexClient
        except ImportError as exc:  # pragma: no cover
            raise ContractError("AZURE_DEPENDENCY_MISSING", "azure-search-documents is required for --backend azure") from exc
        index_client_factory = index_client_factory or SearchIndexClient
        search_client_factory = search_client_factory or SearchClient
    index_factory = index_client_factory
    search_factory = search_client_factory
    client_options = {"credential": credential, "audience": "https://search.azure.com",
                      "api_version": API_VERSION, "permit_redirects": False}
    index_client = index_factory(endpoint=endpoint, **client_options)
    source_client = search_factory(endpoint=endpoint, index_name=args.source_index, **client_options)
    try:
        service_stats = index_client.get_service_statistics()
    except Exception as exc:
        raise ContractError("SEARCH_REQUEST_FAILED", "Cannot read Search service statistics") from exc
    fields = SourceFields(args.key_field, args.text_field, args.source_field, args.vector_field,
                          args.key_field, tuple(args.security_field or ()),
                          getattr(args, "source_visibility", None) or "per-document")
    source_index_def = index_client.get_index(args.source_index)
    vector = vector_metadata(source_index_def, args.vector_field)
    try:
        count = source_client.get_document_count()
    except Exception as exc:
        raise ContractError("SOURCE_COUNT_UNAVAILABLE", "Cannot read source document count") from exc
    if not isinstance(vector.get("dimension"), int) or vector["dimension"] < 1 or type(count) is not int or count < 1:
        raise ContractError("SOURCE_IDENTITY_INVALID", "Live source dimension/count could not be inferred")
    source_id = SourceIdentity(endpoint, args.source_index, args.frozen_evidence, args.embedding_model_id,
                               vector["dimension"], "public", count, args.owner_approval)
    from grz_adapters import AzurePublicationAdapter, AzureSourceAdapter
    source = AzureSourceAdapter(source_client, index_client, fields, approval=SourceExportApproval(
        args.tenant_id, endpoint, args.source_index, args.owner_approval, args.security_inspection, args.frozen_evidence))
    publisher = AzurePublicationAdapter(index_client, lambda index: search_factory(
        endpoint=endpoint, index_name=index, **client_options),
        approval=publication_approval(args, endpoint, arm, service_stats, index_client, count, vector["dimension"]),
)
    store = LiveAzureBuildStore(source, publisher, arm=arm, service_stats=service_stats,
                                index_client=index_client, endpoint=endpoint, fields=fields,
                                vector_query_factory=vector_query_factory)
    store.reader_grants = ReaderGrants(arm.get("id") or arm_url.split("?", 1)[0].removeprefix("https://management.azure.com"),
                                       management, arm_request)
    return store, source_id, {"tenant_tokens": tenant, "endpoint": endpoint, "arm": safe_arm_snapshot(arm),
                              "credential": credential,
                              "names": lambda: display_names(arm_get, management, args.tenant_id, args.subscription_id)}
