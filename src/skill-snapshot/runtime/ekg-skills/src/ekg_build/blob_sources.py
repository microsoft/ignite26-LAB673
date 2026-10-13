"""Read-only, exact-account inventory and pinned reads for an existing Blob prefix."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol
from urllib.parse import quote
from xml.etree import ElementTree

from ekg_core import az_identity
from ekg_core.models import ManifestItem, SourceKind, SourceLocator, SourceManifest, stable_id


class BlobSourceError(RuntimeError):
    """A source cannot be safely inventoried or read without further intervention."""


@dataclass(frozen=True)
class BlobLimits:
    page_size: int = 100
    max_pages: int = 20
    max_items: int = 1000
    max_blob_bytes: int = 20_000_000
    max_total_bytes: int = 200_000_000

    def __post_init__(self) -> None:
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 1
               for value in (self.page_size, self.max_pages, self.max_items,
                             self.max_blob_bytes, self.max_total_bytes)):
            raise ValueError("Blob inventory limits must be positive integers")
        if self.page_size > 5000:
            raise ValueError("Blob listing page size cannot exceed 5000")


@dataclass(frozen=True)
class BlobProperties:
    name: str
    etag: str
    size: int
    content_type: str
    version_id: str | None = None
    content_md5: str | None = None
    snapshot: str | None = None
    deleted: bool = False
    blob_type: str = "BlockBlob"
    resource_type: str | None = None
    is_current_version: bool = True


@dataclass(frozen=True)
class BlobPage:
    blobs: tuple[BlobProperties, ...]
    next_marker: str | None = None


class BlobReader(Protocol):
    def inspect_account(self, resource_id: str, tenant_id: str) -> dict[str, Any]: ...
    def list_blobs(self, source: SourceLocator, marker: str | None,
                   max_results: int) -> BlobPage: ...
    def get_blob(self, source: SourceLocator, name: str) -> BlobProperties: ...
    def download_blob(self, source: SourceLocator, name: str, etag: str,
                      version_id: str | None, max_bytes: int) -> tuple[BlobProperties, bytes]: ...


@dataclass(frozen=True)
class BlobPin:
    source_id: str
    name: str
    etag: str
    version_id: str | None
    size: int
    content_md5: str | None
    content_type: str


@dataclass(frozen=True)
class BlobInventory:
    manifest: SourceManifest
    pins: tuple[BlobPin, ...]
    page_count: int
    blob_count: int
    total_bytes: int

    def __post_init__(self) -> None:
        if (self.manifest.source.kind is not SourceKind.BLOB_PREFIX
                or self.blob_count != len(self.pins)
                or self.blob_count != self.manifest.document_count
                or self.blob_count < 1 or self.page_count < 1
                or self.total_bytes != sum(pin.size for pin in self.pins)
                or len({pin.name for pin in self.pins}) != len(self.pins)
                or tuple(sorted(self.pins, key=lambda pin: pin.name)) != self.pins):
            raise ValueError("Blob inventory counts or pins do not match the manifest")
        for pin, item in zip(self.pins, self.manifest.items):
            if (pin.source_id != item.source_id
                    or item.version_or_hash != _identity(pin)
                    or pin.content_type != item.media_type
                    or item.original_uri != _blob_uri(self.manifest.source, pin.name)
                    or item.citation_uri != item.original_uri):
                raise ValueError("Blob inventory pin differs from original manifest provenance")


@dataclass(frozen=True)
class PinnedBlob:
    pin: BlobPin
    data: bytes
    sha256: str


_STORAGE_ID = re.compile(
    r"/subscriptions/([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})"
    r"/resourceGroups/([^/]+)/providers/Microsoft\.Storage/storageAccounts/([a-z0-9]{3,24})",
    re.IGNORECASE,
)
_SUPPORTED_TYPES = {"text/plain", "text/markdown", "application/octet-stream"}


def _account(source: SourceLocator, reader: BlobReader, tenant_id: str) -> None:
    if not isinstance(source, SourceLocator) or source.kind is not SourceKind.BLOB_PREFIX:
        raise ValueError("Blob source requires a blob_prefix SourceLocator")
    if not source.prefix:
        raise BlobSourceError("SOURCE_SCOPE_MISSING: a nonempty Blob prefix is required")
    match = _STORAGE_ID.fullmatch(source.resource_id or "")
    if not match or source.reference != f"https://{match[3]}.blob.core.windows.net":
        raise BlobSourceError("SOURCE_ID_MISMATCH: exact Blob account ARM ID and endpoint are required")
    if not isinstance(tenant_id, str) or not re.fullmatch(
        r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", tenant_id
    ):
        raise ValueError("an explicit tenant ID is required for Blob source inspection")
    observed = reader.inspect_account(source.resource_id, tenant_id)
    if not isinstance(observed, dict):
        raise BlobSourceError("SOURCE_ID_MISMATCH: account inspection returned no identity")
    props = observed.get("properties")
    endpoints = props.get("primaryEndpoints") if isinstance(props, dict) else None
    endpoint = endpoints.get("blob") if isinstance(endpoints, dict) else None
    if (str(observed.get("id", "")).casefold() != source.resource_id.casefold()
            or str(observed.get("name", "")).casefold() != match[3].casefold()
            or str(observed.get("type", "")).casefold() != "microsoft.storage/storageaccounts"
            or not isinstance(endpoint, str) or endpoint.rstrip("/") != source.reference):
        raise BlobSourceError("SOURCE_ID_MISMATCH: observed account or Blob endpoint differs")
    if str(props.get("provisioningState", "")).casefold() != "succeeded":
        raise BlobSourceError("SOURCE_NOT_READY: observed account is not provisioned")
    if observed.get("tenant_id") and str(observed["tenant_id"]).casefold() != tenant_id.casefold():
        raise BlobSourceError("TENANT_MISMATCH: observed account belongs to another tenant")
    if observed.get("permissions") == "denied":
        raise BlobSourceError("PERMISSION_DENIED: source account inspection was denied")


def _validate_blob(blob: BlobProperties, source: SourceLocator, limits: BlobLimits) -> None:
    if not isinstance(blob, BlobProperties) or not isinstance(blob.name, str) or not blob.name:
        raise BlobSourceError("SOURCE_ENTRY_INVALID: listing returned an unnamed entry")
    if (not blob.name.startswith(source.prefix) or blob.name.startswith("/")
            or "\\" in blob.name or any(part in {"", ".", ".."} for part in blob.name.split("/"))
            or blob.snapshot is not None or blob.deleted or not blob.is_current_version
            or blob.blob_type != "BlockBlob"
            or blob.resource_type not in (None, "file")):
        raise BlobSourceError("SOURCE_ENTRY_INVALID: listing contains an out-of-scope or unsupported entry")
    if not blob.name.lower().endswith((".md", ".txt")) or (
        not isinstance(blob.content_type, str)
        or blob.content_type.split(";", 1)[0].strip().lower() not in _SUPPORTED_TYPES
    ):
        raise BlobSourceError("SOURCE_ENTRY_UNSUPPORTED: only text .md/.txt blobs are supported")
    if not isinstance(blob.etag, str) or not blob.etag.strip() or (
        blob.version_id is not None and (not isinstance(blob.version_id, str) or not blob.version_id)
    ):
        raise BlobSourceError("SOURCE_IDENTITY_MISSING: blob ETag or version is missing")
    if not isinstance(blob.size, int) or isinstance(blob.size, bool) or blob.size < 1:
        raise BlobSourceError("SOURCE_ENTRY_INVALID: empty or unmeasured blob")
    if blob.size > limits.max_blob_bytes:
        raise BlobSourceError("SOURCE_LIMIT_EXCEEDED: per-blob byte limit")
    if blob.content_md5 is not None:
        try:
            digest = base64.b64decode(blob.content_md5, validate=True)
        except (ValueError, base64.binascii.Error) as error:
            raise BlobSourceError("SOURCE_ENTRY_INVALID: malformed service MD5") from error
        if len(digest) != 16:
            raise BlobSourceError("SOURCE_ENTRY_INVALID: malformed service MD5")


def _pin(blob: BlobProperties, source: SourceLocator) -> BlobPin:
    return BlobPin(
        stable_id("blob", {"source": source.source_id, "name": blob.name}),
        blob.name, blob.etag, blob.version_id, blob.size, blob.content_md5,
        blob.content_type,
    )


def _identity(pin: BlobPin) -> str:
    return f"version:{pin.version_id}" if pin.version_id else f"etag:{pin.etag}"


def _blob_uri(source: SourceLocator, name: str) -> str:
    return f"{source.reference}/{quote(source.container, safe='')}/{quote(name, safe='/')}"


def _assert_pin(blob: BlobProperties, pin: BlobPin) -> None:
    if (not isinstance(blob, BlobProperties) or blob.name != pin.name
            or blob.etag != pin.etag or blob.version_id != pin.version_id
            or blob.size != pin.size or blob.content_md5 != pin.content_md5
            or blob.content_type != pin.content_type or blob.deleted or blob.snapshot is not None
            or blob.blob_type != "BlockBlob" or blob.resource_type not in (None, "file")
            or not blob.is_current_version):
        raise BlobSourceError("SOURCE_DRIFT: source blob identity or properties changed")


def inventory_blob_prefix(
    source: SourceLocator, reader: BlobReader, *, tenant_id: str,
    limits: BlobLimits = BlobLimits(),
) -> BlobInventory:
    """Inventory one exact existing account/prefix; never create or modify source data."""
    _account(source, reader, tenant_id)
    pins: list[BlobPin] = []
    marker: str | None = None
    seen_markers: set[str] = set()
    pages = 0
    total = 0
    while True:
        if pages >= limits.max_pages:
            raise BlobSourceError("SOURCE_LIMIT_EXCEEDED: listing page limit")
        page = reader.list_blobs(source, marker, limits.page_size)
        pages += 1
        if not isinstance(page, BlobPage) or len(page.blobs) > limits.page_size:
            raise BlobSourceError("SOURCE_ENTRY_INVALID: malformed listing page")
        for blob in page.blobs:
            _validate_blob(blob, source, limits)
            total += blob.size
            if len(pins) >= limits.max_items or total > limits.max_total_bytes:
                raise BlobSourceError("SOURCE_LIMIT_EXCEEDED: item or total byte limit")
            pins.append(_pin(blob, source))
        if page.next_marker is None:
            break
        if (not isinstance(page.next_marker, str) or not page.next_marker
                or page.next_marker == marker or page.next_marker in seen_markers):
            raise BlobSourceError("SOURCE_ENTRY_INVALID: ambiguous listing continuation")
        seen_markers.add(page.next_marker)
        marker = page.next_marker
    if not pins:
        raise BlobSourceError("EMPTY_MANIFEST: Blob prefix contains no supported documents")
    pins.sort(key=lambda pin: pin.name)
    if len({pin.name for pin in pins}) != len(pins):
        raise BlobSourceError("SOURCE_ENTRY_INVALID: duplicate blob name across pages")
    items = tuple(ManifestItem(
        source_id=pin.source_id,
        original_uri=_blob_uri(source, pin.name),
        citation_uri=_blob_uri(source, pin.name),
        media_type=pin.content_type, version_or_hash=_identity(pin),
    ) for pin in pins)
    manifest = SourceManifest("1", source, datetime.now(timezone.utc).isoformat(), items)
    return BlobInventory(manifest, tuple(pins), pages, len(pins), total)


def recheck_blob_inventory(inventory: BlobInventory, reader: BlobReader, *,
                           tenant_id: str, limits: BlobLimits = BlobLimits()) -> None:
    """Reject additions, removals and property drift before an approved staging operation."""
    fresh = inventory_blob_prefix(inventory.manifest.source, reader, tenant_id=tenant_id, limits=limits)
    if fresh.manifest.digest != inventory.manifest.digest or fresh.pins != inventory.pins:
        raise BlobSourceError("SOURCE_DRIFT: prefix membership or blob identity changed")
    for pin in inventory.pins:
        _assert_pin(reader.get_blob(inventory.manifest.source, pin.name), pin)


def read_pinned_blob(
    inventory: BlobInventory, pin: BlobPin, reader: BlobReader, *,
    tenant_id: str, limits: BlobLimits = BlobLimits(),
) -> PinnedBlob:
    """Read only a manifest pin, conditional on the current ETag; caller owns any staging."""
    if pin not in inventory.pins or pin.size > limits.max_blob_bytes:
        raise BlobSourceError("SOURCE_PIN_INVALID: pin is not in the bounded inventory")
    _account(inventory.manifest.source, reader, tenant_id)
    _assert_pin(reader.get_blob(inventory.manifest.source, pin.name), pin)
    observed, data = reader.download_blob(inventory.manifest.source, pin.name,
                                          pin.etag, pin.version_id, limits.max_blob_bytes)
    _assert_pin(observed, pin)
    if not isinstance(data, bytes) or len(data) != pin.size or len(data) > limits.max_blob_bytes:
        raise BlobSourceError("SOURCE_DRIFT: downloaded byte count differs from the pin")
    if pin.content_md5 and base64.b64encode(
        hashlib.md5(data).digest()
    ).decode("ascii") != pin.content_md5:
        raise BlobSourceError("SOURCE_DRIFT: downloaded bytes differ from service MD5")
    return PinnedBlob(pin, data, f"sha256:{hashlib.sha256(data).hexdigest()}")


class AzureBlobReader:
    """Entra-authenticated ARM and Blob REST reader; GET/HEAD only."""

    def __init__(self, *, tenant_id: str, credential: Any = None) -> None:
        self.tenant_id = tenant_id
        self.credential = az_identity.cached(
            credential if credential is not None else az_identity.cli_credential(tenant_id))

    def _request(self, method: str, url: str, scope: str, *,
                 params: dict[str, str | int] | None = None,
                 headers: dict[str, str] | None = None, max_bytes: int | None = None):
        import httpx

        token = self.credential.get_token(scope).token
        if not az_identity.token_in_tenant(token, self.tenant_id):
            raise BlobSourceError("TENANT_MISMATCH: source credential tenant differs")
        with httpx.stream(method, url, params=params, headers={
            "Authorization": f"Bearer {token}", "x-ms-version": "2023-11-03",
            "x-ms-date": datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT"),
            **(headers or {}),
        }, timeout=90) as response:
            if response.status_code >= 400:
                raise BlobSourceError(f"SOURCE_READ_FAILED: {method} returned HTTP {response.status_code}")
            if max_bytes is None:
                return response.headers, b""
            data = bytearray()
            for chunk in response.iter_bytes():
                data.extend(chunk)
                if len(data) > max_bytes:
                    raise BlobSourceError("SOURCE_LIMIT_EXCEEDED: response byte limit")
            return response.headers, bytes(data)

    def inspect_account(self, resource_id: str, tenant_id: str) -> dict[str, Any]:
        if tenant_id.casefold() != self.tenant_id.casefold():
            raise BlobSourceError("TENANT_MISMATCH: reader is bound to another tenant")
        _, data = self._request(
            "GET", f"https://management.azure.com{resource_id}",
            "https://management.azure.com/.default", params={"api-version": "2024-01-01"},
            max_bytes=100_000,
        )
        return json.loads(data)

    def list_blobs(self, source: SourceLocator, marker: str | None,
                   max_results: int) -> BlobPage:
        params: dict[str, str | int] = {
            "restype": "container", "comp": "list", "prefix": source.prefix,
            "maxresults": max_results,
        }
        if marker is not None:
            params["marker"] = marker
        _, data = self._request(
            "GET", f"{source.reference}/{quote(source.container, safe='')}",
            "https://storage.azure.com/.default", params=params,
            max_bytes=2_000_000,
        )
        root = ElementTree.fromstring(data)
        blobs = root.find("Blobs")
        if (root.tag != "EnumerationResults" or blobs is None
                or root.attrib.get("ServiceEndpoint", "").rstrip("/") != source.reference
                or root.attrib.get("ContainerName") != source.container
                or root.findtext("Prefix") != source.prefix):
            raise BlobSourceError("SOURCE_ENTRY_INVALID: malformed Blob listing")
        if any(entry.tag != "Blob" for entry in blobs):
            raise BlobSourceError("SOURCE_ENTRY_UNSUPPORTED: BlobPrefix or unknown listing entry")
        result = []
        for entry in blobs:
            props = entry.find("Properties")
            if props is None:
                raise BlobSourceError("SOURCE_ENTRY_INVALID: listing lacks blob properties")
            name = entry.find("Name")
            if name is not None and name.attrib.get("Encoded", "").lower() == "true":
                raise BlobSourceError("SOURCE_ENTRY_UNSUPPORTED: encoded Blob name")
            result.append(BlobProperties(
                name=entry.findtext("Name") or "", etag=props.findtext("Etag") or "",
                size=_size(props.findtext("Content-Length")),
                content_type=props.findtext("Content-Type") or "",
                version_id=entry.findtext("VersionId"),
                content_md5=props.findtext("Content-MD5") or None,
                snapshot=entry.findtext("Snapshot"),
                deleted=entry.findtext("Deleted") == "true",
                blob_type=props.findtext("BlobType") or "",
                resource_type=props.findtext("ResourceType"),
                is_current_version=entry.findtext("IsCurrentVersion") != "false",
            ))
        return BlobPage(tuple(result), root.findtext("NextMarker") or None)

    def get_blob(self, source: SourceLocator, name: str) -> BlobProperties:
        url = f"{source.reference}/{quote(source.container, safe='')}/{quote(name, safe='/')}"
        headers, _ = self._request("HEAD", url, "https://storage.azure.com/.default")
        return _headers_blob(name, headers)

    def download_blob(self, source: SourceLocator, name: str, etag: str,
                      version_id: str | None, max_bytes: int) -> tuple[BlobProperties, bytes]:
        url = f"{source.reference}/{quote(source.container, safe='')}/{quote(name, safe='/')}"
        params = {"versionid": version_id} if version_id else None
        headers, data = self._request(
            "GET", url, "https://storage.azure.com/.default",
            params=params, headers={"If-Match": etag}, max_bytes=max_bytes,
        )
        return _headers_blob(name, headers), data


def _size(value: str | None) -> int:
    try:
        return int(value) if value is not None else -1
    except ValueError:
        return -1


def _headers_blob(name: str, headers: Any) -> BlobProperties:
    return BlobProperties(
        name, headers.get("etag", ""), _size(headers.get("content-length")),
        headers.get("content-type", ""), headers.get("x-ms-version-id"),
        headers.get("content-md5"), blob_type=headers.get("x-ms-blob-type", ""),
    )
