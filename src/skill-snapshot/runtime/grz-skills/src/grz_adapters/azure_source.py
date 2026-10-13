"""Read-only, stable keyset export of a frozen public Search index."""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from grz_core.contracts import INPUT_VERSION, VISIBILITY_BASES, ContractError, SourceIdentity, canonical_json, digest


def get_field(value: Any, name: str, default: Any = None) -> Any:
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def _fail(code: str, detail: str) -> None:
    raise ContractError(code, detail)


@dataclass(frozen=True)
class SourceFields:
    key: str
    text: str
    source: str
    vector: str
    scan_key: str
    security_fields: tuple[str, ...] = ()
    # "public-attested": the operator confirms the whole index is public because it has no
    # per-document visibility field. It never overrides a mapped field.
    visibility_basis: str = "per-document"


@dataclass(frozen=True)
class SourceExportApproval:
    tenant: str
    resource: str
    dataset: str
    owner_approval: str
    security_inspection: str
    frozen_evidence: str


class AzureSourceAdapter:
    """Requires query and index-read clients for the named *physical* source index.

    Export performs three ordered scans: baseline fingerprint, materialization,
    and post-export fingerprint. This detects changes, but cannot replace the
    producer's write freeze: Azure Search does not provide snapshot isolation.
    """

    def __init__(
        self, search_client: Any, index_client: Any, fields: SourceFields,
        *, approval: SourceExportApproval, page_size: int = 500,
    ):
        if not 1 <= page_size <= 1000:
            _fail("SOURCE_PAGE_INVALID", "Page size must be between 1 and 1000")
        self.search_client = search_client
        self.index_client = index_client
        self.fields = fields
        self.approval = approval
        self.page_size = page_size

    def _preflight(self, source: SourceIdentity) -> tuple[str, list[str]]:
        source.validate(live=True)
        approval = self.approval
        if not all((approval.tenant, approval.resource, approval.dataset,
                    approval.owner_approval, approval.security_inspection, approval.frozen_evidence)):
            _fail("SOURCE_APPROVAL_REQUIRED", "Named tenant/resource/dataset, owner, security inspection and freeze evidence required")
        if source.owner_approval != approval.owner_approval or source.frozen_generation != approval.frozen_evidence:
            _fail("SOURCE_APPROVAL_MISMATCH", "Owner approval and producer freeze evidence must match source identity")
        if source.service != approval.resource or source.index != approval.dataset:
            _fail("SOURCE_TARGET_MISMATCH", "Approval must identify the physical source service and index")
        bound = get_field(self.search_client, "index_name")
        if bound is not None and bound != source.index:
            _fail("SOURCE_TARGET_MISMATCH", "Search client is bound to a different physical index")
        if len({self.fields.key, self.fields.text, self.fields.source, self.fields.vector}) != 4:
            _fail("SOURCE_FIELDS_INVALID", "Key, text, source and vector fields must be distinct")
        try:
            index = self.index_client.get_index(source.index)
        except Exception as exc:
            raise ContractError("SOURCE_INSPECT_FAILED", "Cannot inspect the named physical source index") from exc
        if get_field(index, "name") != source.index:
            _fail("SOURCE_TARGET_MISMATCH", "Index definition does not match physical source index")
        definitions = {get_field(f, "name"): f for f in get_field(index, "fields", [])}
        requested = [self.fields.key, self.fields.text, self.fields.source, self.fields.vector, self.fields.scan_key]
        if any(not name or name not in definitions for name in requested + list(self.fields.security_fields)):
            _fail("SOURCE_FIELDS_INVALID", "Every mapped field must exist in the source index")
        if not get_field(definitions[self.fields.key], "key", False):
            _fail("SOURCE_KEY_INVALID", "Mapped document ID must be the physical index key")
        scan = definitions[self.fields.scan_key]
        if not get_field(scan, "sortable", False) or not get_field(scan, "filterable", False):
            _fail("SOURCE_SCAN_UNSUPPORTED", "A unique retrievable sortable/filterable string key is required; request a producer snapshot")
        for name in requested + list(self.fields.security_fields):
            field = definitions[name]
            if get_field(field, "hidden", False) or get_field(field, "retrievable", True) is False:
                code = "SOURCE_VECTORS_NOT_RETRIEVABLE" if name == self.fields.vector else "SOURCE_FIELDS_INVALID"
                _fail(code, f"Field {name!r} is not retrievable; request a producer-created portable snapshot")
        vector = definitions[self.fields.vector]
        if get_field(vector, "stored", True) is False:
            _fail("SOURCE_VECTORS_NOT_RETRIEVABLE", f"Field {self.fields.vector!r} is not stored; request a producer-created portable snapshot")
        if get_field(vector, "type") != "Collection(Edm.Single)" or get_field(vector, "vector_search_dimensions", get_field(vector, "dimensions")) != source.dimension:
            _fail("SOURCE_VECTOR_INVALID", "Stored vector type or dimension differs from the owner-provided model identity")
        for name in (self.fields.key, self.fields.scan_key, self.fields.text, self.fields.source):
            if get_field(definitions[name], "type") != "Edm.String":
                _fail("SOURCE_FIELDS_INVALID", f"Field {name!r} must be a string")
        if self.fields.scan_key != self.fields.key:
            # Search index metadata cannot prove another field unique. Even when
            # scans detect duplicates, it cannot prove no missing rows.
            _fail("SOURCE_SCAN_UNSUPPORTED", "Continuation must use the unique physical document key")
        suspicious = ("acl", "permission", "security", "visibility", "principal", "tenant", "group", "access")
        security_names = set(self.fields.security_fields)
        attested = self.fields.visibility_basis == "public-attested"
        if self.fields.visibility_basis not in VISIBILITY_BASES:
            _fail("SOURCE_VISIBILITY_INVALID", "--source-visibility must be per-document or public-attested")
        if any(any(part in str(name).lower() for part in suspicious) and name not in security_names
               for name in definitions):
            _fail("SOURCE_SECURITY_UNINSPECTED", "ACL/security-bearing fields must be explicitly mapped and inspected"
                  + ("; the whole-index attestation doesn't cover a per-document field" if attested else ""))
        if len(security_names) != len(self.fields.security_fields):
            _fail("SOURCE_SECURITY_UNINSPECTED", "Duplicate security field mapping")
        if not security_names and not attested:
            _fail("SOURCE_VISIBILITY_UNVERIFIED",
                  f"{source.index} has no mapped visibility field, so GRZ can't check each document is public")
        return digest([{"name": name, "type": get_field(f, "type"), "key": get_field(f, "key"),
                        "sortable": get_field(f, "sortable"), "filterable": get_field(f, "filterable"),
                        "hidden": get_field(f, "hidden"), "stored": get_field(f, "stored"),
                        "dimensions": get_field(f, "vector_search_dimensions", get_field(f, "dimensions"))}
                       for name, f in sorted(definitions.items())]), requested + list(security_names - set(requested))

    def _count(self, expected: int) -> None:
        try:
            actual = self.search_client.get_document_count()
        except Exception as exc:
            raise ContractError("SOURCE_COUNT_UNAVAILABLE", "Cannot verify full source count") from exc
        if actual != expected:
            _fail("SOURCE_CHANGED", f"Expected {expected} source rows; observed {actual}")

    def _scan(self, source: SourceIdentity, select: list[str]):
        last = None
        seen: set[str] = set()
        while True:
            continuation = None if last is None else f"{self.fields.scan_key} gt '{last.replace(chr(39), chr(39) * 2)}'"
            try:
                page = list(self.search_client.search(
                    search_text="*", filter=continuation,
                    order_by=[f"{self.fields.scan_key} asc"], select=select,
                    top=self.page_size,
                ))
            except Exception as exc:
                raise ContractError("SOURCE_SCAN_FAILED", "Cannot complete stable ordered source scan") from exc
            if len(page) > self.page_size:
                _fail("SOURCE_PAGE_INCOMPLETE", "Source returned an overfull bounded page")
            if not page:
                break
            for row in page:
                key = get_field(row, self.fields.key)
                if not isinstance(key, str) or not key.strip() or (last is not None and key <= last) or key in seen:
                    _fail("SOURCE_SCAN_UNSTABLE", "Missing, duplicate or out-of-order source key")
                seen.add(key)
                last = key
                text, ref, vector = (get_field(row, name) for name in (self.fields.text, self.fields.source, self.fields.vector))
                if not isinstance(text, str) or not text.strip() or not isinstance(ref, str) or not ref.strip():
                    _fail("SOURCE_ROW_INVALID", "Source row lacks text or source reference")
                if not isinstance(vector, (list, tuple)) or len(vector) != source.dimension or any(
                    isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in vector
                ) or not any(x != 0 for x in vector):
                    _fail("SOURCE_VECTORS_NOT_RETRIEVABLE", f"Missing/nonfinite/zero vector in {self.fields.vector!r}; request a producer snapshot")
                restricted = [field for field in self.fields.security_fields if get_field(row, field) != "public"]
                if restricted:
                    _fail("VISIBILITY_UNSUPPORTED", f"A document's {restricted[0]!r} isn't 'public'"
                          + ("; the whole-index attestation can't override per-document visibility"
                             if self.fields.visibility_basis == "public-attested" else ""))
                yield key, text, ref, list(vector)
                if len(seen) > source.expected_count:
                    _fail("SOURCE_CHANGED", "Scan exceeded expected source count")
            if len(page) < self.page_size:
                break
        if len(seen) != source.expected_count:
            _fail("SOURCE_PAGE_INCOMPLETE", "Scan ended before the expected count; producer snapshot required")

    def inspect(self, source: SourceIdentity) -> dict[str, Any]:
        schema_fingerprint, selected = self._preflight(source)
        self._count(source.expected_count)
        return {"source": asdict(source), "fields": asdict(self.fields),
                "schema_fingerprint": schema_fingerprint, "selected_fields": selected,
                "page_size": self.page_size, "snapshot_isolation": False}

    def export_snapshot(self, source: SourceIdentity, destination: Path) -> Path:
        preflight = self.inspect(source)
        select = preflight["selected_fields"]
        def fingerprint() -> str:
            h = hashlib.sha256()
            for row in self._scan(source, select):
                h.update((canonical_json(row) + "\n").encode("utf-8"))
            return h.hexdigest()

        baseline = fingerprint()
        self._count(source.expected_count)
        destination = Path(destination)
        if destination.exists() and any(destination.iterdir()):
            _fail("SNAPSHOT_DESTINATION_NOT_EMPTY", "Export destination must be empty")
        destination.mkdir(parents=True, exist_ok=True, mode=0o700)
        rows_path, vectors_path = destination / "rows.jsonl", destination / "vectors.jsonl"
        try:
            with rows_path.open("w", encoding="utf-8", newline="\n") as rows, vectors_path.open("w", encoding="utf-8", newline="\n") as vectors:
                h = hashlib.sha256()
                rows_hash = hashlib.sha256()
                vectors_hash = hashlib.sha256()
                for key, text, ref, vector in self._scan(source, select):
                    h.update((canonical_json([key, text, ref, vector]) + "\n").encode("utf-8"))
                    row_line = canonical_json({"chunk_id": key, "text": text, "source": ref, "visibility": "public"}) + "\n"
                    vector_line = canonical_json({"chunk_id": key, "embedding": vector}) + "\n"
                    rows.write(row_line)
                    vectors.write(vector_line)
                    rows_hash.update(row_line.encode("utf-8"))
                    vectors_hash.update(vector_line.encode("utf-8"))
            if h.hexdigest() != baseline or fingerprint() != baseline:
                _fail("SOURCE_CHANGED", "Source keys, content or vectors changed while exporting")
            self._count(source.expected_count)
            after = self._preflight(source)[0]
            if after != preflight["schema_fingerprint"]:
                _fail("SOURCE_CHANGED", "Source index field capabilities changed while exporting")
            manifest = {
                "version": INPUT_VERSION, "source": asdict(source),
                "rows_file": rows_path.name, "vectors_file": vectors_path.name,
                "rows_sha256": rows_hash.hexdigest(),
                "vectors_sha256": vectors_hash.hexdigest(),
                "provenance_status": "owner-attested",
            }
            result = destination / "manifest.json"
            result.write_text(canonical_json(manifest) + "\n", encoding="utf-8")
            return result
        except BaseException:
            for path in (rows_path, vectors_path, destination / "manifest.json"):
                path.unlink(missing_ok=True)
            raise
