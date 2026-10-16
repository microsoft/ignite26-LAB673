"""Approval-gated publisher for new, generation-scoped Azure Search sidecars."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

from grz_core.contracts import ContractError, digest, require_public

from .azure_source import get_field
from .sidecar_schema import (
    check_created_index, generation_index_definition, load_sidecar_schema, prepare_document, sdk_index_model,
)

@dataclass(frozen=True)
class PublicationApproval:
    tenant: str
    resource: str
    dataset: str
    owner_approval: str
    security_inspection: str
    replication_approval: str
    budget_approval: str
    write_approval: str
    cutover_approval: str = ""
    serving_alias: str = ""


def _status(exc: Exception) -> int | None:
    return get_field(exc, "status_code", get_field(get_field(exc, "response"), "status_code"))


def _denied(operation: str) -> ContractError:
    return ContractError("PUBLICATION_PERMISSION_DENIED", f"Insufficient Search rights for {operation}")


def _is_sdk_client(client: Any) -> bool:
    return type(client).__module__.startswith("azure.")


class AzurePublicationAdapter:
    """Injected index admin and document-client factory, with no credential creation.

    Single publisher only: alias verification is a best-effort expected-prior
    guard, NOT an atomic compare-and-set across independent writers.
    """

    def __init__(
        self, index_client: Any, search_client_factory: Any,
        *, approval: PublicationApproval, batch_size: int = 500,
    ):
        if not 1 <= batch_size <= 1000:
            raise ContractError("PUBLICATION_BATCH_INVALID", "Batch size must be 1..1000")
        self.index_client = index_client
        self.search_client_factory = search_client_factory
        self.approval = approval
        self.batch_size = batch_size
        self.confirmed_ids: set[str] = set()
        self.verified_indexes: set[str] = set()
        self.verified_fingerprints: dict[str, str] = {}
        self.index_dimensions: dict[str, int] = {}

    def _approve(self, index: str, *, cutover: bool = False, alias: str = "", write: bool = True) -> None:
        a = self.approval
        required = [a.tenant, a.resource, a.dataset, a.owner_approval, a.security_inspection]
        if write:
            required += [a.replication_approval, a.budget_approval, a.write_approval]
        if not all(required):
            raise ContractError("PUBLICATION_APPROVAL_REQUIRED", "Named tenant/service/dataset, owner, security, replication, budget and write approvals required")
        planned_prefix = f"grz-{a.dataset}-"
        if not index.startswith("grz-") or not (index.startswith(planned_prefix) and index[len(planned_prefix):]):
            raise ContractError("PUBLICATION_TARGET_MISMATCH", "Physical generation index must belong to the approved dataset")
        if cutover:
            if not a.cutover_approval or not a.serving_alias:
                raise ContractError("CUTOVER_APPROVAL_REQUIRED", "Separate named-alias cutover approval required")
            if not alias.startswith("grz-") or alias != a.serving_alias:
                raise ContractError("PUBLICATION_TARGET_MISMATCH", "Serving alias differs from approved alias")

    def search_client(self, index: str) -> Any:
        client = self.search_client_factory(index)
        bound = get_field(client, "index_name")
        if bound is not None and bound != index:
            raise ContractError("PUBLICATION_TARGET_MISMATCH", "Document client bound to wrong physical index")
        return client

    def create_generation_index(self, index: str, dimension: int) -> None:
        self._approve(index)
        if not isinstance(dimension, int) or dimension < 1:
            raise ContractError("SOURCE_VECTOR_INVALID", "Positive source vector dimension required")
        schema = load_sidecar_schema()
        try:
            self.index_client.get_index(index)
        except Exception as exc:
            if _status(exc) != 404:
                raise _denied("index inspection") from exc
        else:
            raise ContractError("GENERATION_EXISTS", "Never overwrite an existing generation index; verify exact retries instead")
        definition = generation_index_definition(index, dimension, schema)
        try:
            self.index_client.create_index(sdk_index_model(definition) if _is_sdk_client(self.index_client) else definition)
            observed = self.index_client.get_index(index)
        except Exception as exc:
            raise _denied("index creation/readback") from exc
        check_created_index(observed, definition, dimension, schema["vector_profile"])
        self.index_dimensions[index] = dimension

    def _target_dimension(self, index: str) -> int:
        dimension = self.index_dimensions.get(index)
        if dimension is None:
            try:
                definition = self.index_client.get_index(index)
                vector = next(field for field in get_field(definition, "fields", [])
                              if get_field(field, "name") == "centroid")
                dimension = get_field(vector, "vector_search_dimensions",
                                 get_field(vector, "vectorSearchDimensions"))
            except Exception as exc:
                raise ContractError("SIDECAR_SCHEMA_MISMATCH", "Cannot inspect target index vector dimension") from exc
        if not isinstance(dimension, int) or dimension < 1:
            raise ContractError("SIDECAR_SCHEMA_MISMATCH", "Target index lacks a usable centroid dimension")
        return dimension

    def upload_batch(self, index: str, documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self._approve(index)
        if not documents or len(documents) > self.batch_size:
            raise ContractError("PUBLICATION_BATCH_INVALID", "Supply a nonempty bounded document batch")
        prepared = [prepare_document(doc) for doc in documents]
        dimension = self._target_dimension(index)
        for doc in prepared:
            vector = doc.get("centroid") if doc["kind"] == "representative" else doc.get("chunk_vector") if doc["kind"] == "evidence" else None
            if vector is not None and (not isinstance(vector, (list, tuple)) or len(vector) != dimension
                    or any(isinstance(x, bool) or not isinstance(x, (int, float))
                           or not math.isfinite(x) for x in vector)
                    or not any(x != 0 for x in vector)):
                raise ContractError("SIDECAR_DOCUMENT_INVALID", "Vector must be finite, nonzero and match source dimension")
        ids = [doc["id"] for doc in prepared]
        if len(set(ids)) != len(ids) or any(key in self.confirmed_ids for key in ids):
            raise ContractError("SIDECAR_DOCUMENT_INVALID", "Duplicate or previously confirmed document ID")
        results = self._upload_once(self.search_client(index), prepared)
        self.confirmed_ids.update(ids)
        return [results[key] for key in ids]

    @staticmethod
    def _upload_once(client: Any, prepared: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """One attempt per batch: any failure is final and left for the journal and reconcile to resolve."""
        try:
            response = list(client.upload_documents(documents=prepared))
        except Exception as exc:
            raise ContractError("PUBLICATION_UPLOAD_FAILED", "Upload failed; no unconfirmed document may be published") from exc
        returned = [get_field(item, "key") for item in response]
        if len(returned) != len(prepared) or set(returned) != {doc["id"] for doc in prepared}:
            raise ContractError("PUBLICATION_RESULT_INCOMPLETE", "Batch results must account for each document exactly once")
        results: dict[str, dict[str, Any]] = {}
        for item in response:
            key = get_field(item, "key")
            if get_field(item, "succeeded") is not True:
                status = get_field(item, "status_code", get_field(item, "statusCode"))
                raise ContractError("PUBLICATION_UPLOAD_FAILED", f"Document {key!r} failed indexing (status {status})")
            results[key] = {"key": key, "succeeded": True}
        return results

    def readback(self, index: str) -> list[dict[str, Any]]:
        self._approve(index, write=False)
        client = self.search_client(index)
        last: str | None = None
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        while True:
            where = None if last is None else f"sort_key gt '{last.replace(chr(39), chr(39) * 2)}'"
            try:
                page = list(client.search(search_text="*", filter=where, order_by=["sort_key asc"],
                                          top=self.batch_size))
            except Exception as exc:
                if _status(exc) == 404:
                    raise ContractError("INDEX_MISSING", "Physical generation index does not exist") from exc
                raise ContractError("PUBLICATION_READBACK_FAILED", "Cannot verify physical generation index") from exc
            if len(page) > self.batch_size:
                raise ContractError("PUBLICATION_READBACK_FAILED", "Readback exceeded bounded page")
            for row in page:
                row = {key: value for key, value in dict(row).items()
                       if not key.startswith("@search.") and value is not None and value != []}
                key, sort_key = row.get("id"), row.get("sort_key")
                if not isinstance(sort_key, str) or not sort_key or (last is not None and sort_key <= last) or key in seen:
                    raise ContractError("PUBLICATION_READBACK_FAILED", "Duplicate, missing or unordered sidecar keys")
                seen.add(key)
                last = sort_key
                require_public(row.get("visibility"))
                if row.get("kind") == "manifest":
                    try:
                        row["payload"] = json.loads(row["payload"])
                    except (TypeError, ValueError) as exc:
                        raise ContractError("PUBLICATION_READBACK_FAILED", "Corrupt manifest payload") from exc
                result.append(row)
            if len(page) < self.batch_size:
                break
        try:
            count = client.get_document_count()
        except Exception as exc:
            if _status(exc) == 404:
                raise ContractError("INDEX_MISSING", "Physical generation index does not exist") from exc
            raise ContractError("PUBLICATION_READBACK_FAILED", "Document count read permission required") from exc
        if count != len(result):
            raise ContractError("READBACK_NOT_SETTLED",
                                f"Search is still indexing: document count {count} differs from keyset scan {len(result)}")
        return result

    def verify(self, index: str, expected: list[dict[str, Any]]) -> None:
        self._approve(index, write=False)
        if not expected or len({doc["id"] for doc in expected}) != len(expected):
            raise ContractError("PUBLICATION_VERIFY_FAILED", "Complete expected document inventory required")
        actual = {doc["id"]: doc for doc in self.readback(index)}
        wanted = {doc["id"]: doc for doc in expected}
        if len(actual) != len(expected) or set(actual) != set(wanted):
            raise ContractError("PUBLICATION_VERIFY_FAILED", "Physical index inventory differs from expected generation")
        for key, original in wanted.items():
            observed = actual[key]
            projected = prepare_document(original)
            if observed.get("kind") == "manifest":
                projected["payload"] = original["payload"]
            for vector_field in ("centroid", "chunk_vector"):
                if vector_field in projected and vector_field in observed:
                    left, right = projected[vector_field], observed[vector_field]
                    if len(left) != len(right) or any(abs(float(x) - float(y)) > 1e-6 for x, y in zip(left, right)):
                        raise ContractError("PUBLICATION_VERIFY_FAILED", f"Physical vector {key!r} differs from build output")
                    projected[vector_field] = observed[vector_field]
            if observed != projected:
                raise ContractError("PUBLICATION_VERIFY_FAILED", f"Physical document {key!r} differs from build output")
        self.verified_indexes.add(index)
        self.verified_fingerprints[index] = digest(actual)

    def resolve_alias(self, alias: str) -> str | None:
        try:
            record = self.index_client.get_alias(alias)
        except Exception as exc:
            if _status(exc) == 404:
                return None
            raise ContractError("ALIAS_UNAVAILABLE", "Cannot inspect serving alias or insufficient rights") from exc
        indexes = get_field(record, "indexes")
        if not isinstance(indexes, (list, tuple)) or len(indexes) != 1:
            raise ContractError("ALIAS_UNAVAILABLE", "Alias must bind exactly one physical index")
        return indexes[0]

    def aliases_by_index(self, indexes: list[str]) -> dict[str, list[str]]:
        """Every alias on the service that binds one of ``indexes``; other aliases are not reported."""
        try:
            records = list(self.index_client.list_aliases())
        except Exception as exc:
            raise ContractError("ALIAS_UNAVAILABLE", "Cannot list Search aliases or insufficient rights") from exc
        wanted = set(indexes)
        bound: dict[str, list[str]] = {}
        for record in records:
            for index in get_field(record, "indexes") or []:
                if index in wanted:
                    bound.setdefault(index, []).append(get_field(record, "name"))
        return bound

    def switch_alias(self, alias: str, expected: str | None, target: str) -> None:
        self._approve(target, cutover=True, alias=alias)
        if target not in self.verified_indexes:
            raise ContractError("PUBLICATION_VERIFY_REQUIRED", "Verify physical index against expected output before cutover")
        if digest({doc["id"]: doc for doc in self.readback(target)}) != self.verified_fingerprints[target]:
            raise ContractError("PUBLICATION_VERIFY_FAILED", "Physical generation changed since verification")
        if self.resolve_alias(alias) != expected:
            raise ContractError("ALIAS_CHANGED", "Serving alias no longer points to expected prior generation")
        try:
            payload = {"name": alias, "indexes": [target]}
            if expected is None:
                self.index_client.create_alias(payload)
            else:
                self.index_client.create_or_update_alias(payload)
        except Exception as exc:
            raise ContractError("ALIAS_UNAVAILABLE", "Alias mutation failed or rights insufficient; previous generation must remain serving") from exc
        if self.resolve_alias(alias) != target:
            raise ContractError("ALIAS_CHANGED", "Alias readback did not confirm requested target")
