"""Bounded, read-only SharePoint library inventory through an injected reader."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Literal, Protocol
from urllib.parse import quote, unquote, urlsplit

from ekg_core.models import ManifestItem, SourceKind, SourceLocator, SourceManifest, stable_id


class SharePointSourceError(RuntimeError):
    """The source cannot be safely inventoried or has changed since inventory."""


class SharePointReadError(RuntimeError):
    """A reader reports a failed metadata request, without retrying another scope."""

    def __init__(self, status: int, message: str = "") -> None:
        self.status = status
        super().__init__(message or f"SharePoint metadata request failed (HTTP {status})")


@dataclass(frozen=True)
class SharePointLimits:
    page_size: int = 100
    max_pages: int = 50
    max_entries: int = 1000
    max_file_bytes: int = 20_000_000
    max_total_bytes: int = 200_000_000
    max_depth: int = 16

    def __post_init__(self) -> None:
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 1
               for value in vars(self).values()):
            raise ValueError("SharePoint inventory limits must be positive integers")
        if self.page_size > 1000:
            raise ValueError("SharePoint page size cannot exceed 1000")


@dataclass(frozen=True)
class SharePointSite:
    id: str
    web_url: str
    tenant_id: str
    permission_evidence: str


@dataclass(frozen=True)
class SharePointLibrary:
    id: str
    site_id: str
    drive_id: str
    web_url: str
    tenant_id: str
    permission_evidence: str


@dataclass(frozen=True)
class SharePointDrive:
    id: str
    site_id: str
    library_id: str
    root_item_id: str
    web_url: str
    tenant_id: str
    permission_evidence: str


@dataclass(frozen=True)
class SharePointItem:
    id: str
    parent_id: str
    site_id: str
    drive_id: str
    name: str
    web_url: str
    kind: Literal["file", "folder"]
    etag: str
    version: str | None
    size: int
    permission_evidence: str
    media_type: str | None = None


@dataclass(frozen=True)
class SharePointPage:
    site_id: str
    drive_id: str
    parent_id: str
    items: tuple[SharePointItem, ...]
    next_token: str | None
    permission_evidence: str


class SharePointReader(Protocol):
    def inspect_site(self, reference: str, tenant_id: str) -> SharePointSite: ...
    def inspect_library(self, site_id: str, library_id: str,
                        tenant_id: str) -> SharePointLibrary: ...
    def inspect_drive(self, site_id: str, drive_id: str,
                      tenant_id: str) -> SharePointDrive: ...
    def list_children(self, site_id: str, drive_id: str, parent_id: str,
                      token: str | None, page_size: int, tenant_id: str) -> SharePointPage: ...
    def get_item(self, site_id: str, drive_id: str, item_id: str,
                 tenant_id: str) -> SharePointItem: ...


@dataclass(frozen=True)
class SharePointPin:
    source_id: str
    id: str
    parent_id: str
    path: str
    kind: Literal["file", "folder"]
    etag: str
    version: str | None
    size: int
    media_type: str | None


@dataclass(frozen=True)
class SharePointInventory:
    manifest: SourceManifest
    site_id: str
    library_id: str
    drive_id: str
    root_item_id: str
    library_web_url: str
    pins: tuple[SharePointPin, ...]
    page_count: int
    entry_count: int
    file_count: int
    folder_count: int
    total_bytes: int
    permission_uncertainty: tuple[str, ...] = (
        "Effective item permissions, inheritance, and future reader access are not verified",
        "Metadata listing is not authorization to read content or copy data",
    )

    def __post_init__(self) -> None:
        if (self.manifest.source.kind is not SourceKind.SHAREPOINT_LIBRARY
                or self.manifest.source.library_id != self.library_id
                or not all(_id(value) for value in (
                    self.site_id, self.library_id, self.drive_id, self.root_item_id,
                ))
                or not _library_url(self.manifest.source.reference, self.library_web_url)
                or self.page_count < 1 or self.file_count < 1
                or self.entry_count != len(self.pins)
                or self.file_count != self.manifest.document_count
                or self.folder_count != self.entry_count - self.file_count
                or self.total_bytes != sum(pin.size for pin in self.pins if pin.kind == "file")
                or len({pin.id for pin in self.pins}) != len(self.pins)
                or len({pin.path for pin in self.pins}) != len(self.pins)
                or tuple(sorted(self.pins, key=lambda pin: pin.path)) != self.pins
                or not self.permission_uncertainty):
            raise ValueError("SharePoint inventory counts or pins do not match the manifest")
        for pin in self.pins:
            expected_id = stable_id("sharepoint-item", {
                "source": self.manifest.source.source_id, "site": self.site_id,
                "library": self.library_id, "drive": self.drive_id, "item": pin.id,
            })
            if (pin.source_id != expected_id or not _id(pin.id) or not _id(pin.parent_id)
                    or pin.id == self.root_item_id or not pin.path
                    or any(not _name(part) for part in pin.path.split("/"))
                    or pin.kind not in {"file", "folder"}
                    or not isinstance(pin.etag, str) or not pin.etag.strip()
                    or not isinstance(pin.size, int) or isinstance(pin.size, bool)
                    or pin.size < 0
                    or pin.kind == "folder" and pin.media_type is not None
                    or pin.kind == "file" and (
                        not pin.version or not pin.media_type or pin.size < 1
                    )):
                raise ValueError("SharePoint inventory pin differs from source identity")
        files = tuple(pin for pin in self.pins if pin.kind == "file")
        for pin, item in zip(files, self.manifest.items):
            uri = _child_url(self.library_web_url, pin.path)
            if (pin.source_id != item.source_id
                    or item.version_or_hash != _version(pin)
                    or pin.media_type != item.media_type
                    or item.original_uri != uri or item.citation_uri != uri
                    or item.observed_permissions or item.materialized_blob_path is not None):
                raise ValueError("SharePoint inventory pin differs from manifest provenance")

    @property
    def digest(self) -> str:
        payload = {
            "manifest_digest": self.manifest.digest,
            "site_id": self.site_id,
            "library_id": self.library_id,
            "drive_id": self.drive_id,
            "root_item_id": self.root_item_id,
            "library_web_url": self.library_web_url,
            "pins": [asdict(pin) for pin in self.pins],
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return f"sha256:{hashlib.sha256(raw).hexdigest()}"


_GUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_ID = re.compile(r"[A-Za-z0-9{}!._,:-]+")
_SITE_PATH = re.compile(r"/(?:sites|teams)/[A-Za-z0-9._~-]+")
_MEDIA_TYPES = {"text/plain", "text/markdown", "application/octet-stream"}


def _id(value: str) -> bool:
    return isinstance(value, str) and len(value) <= 256 and _ID.fullmatch(value) is not None


def _site_reference(reference: str) -> bool:
    if not isinstance(reference, str):
        return False
    parsed = urlsplit(reference)
    return bool(
        parsed.scheme == "https" and parsed.hostname
        and re.fullmatch(r"[a-z0-9-]+\.sharepoint\.(?:com|us|cn|de)", parsed.hostname)
        and parsed.netloc == parsed.hostname and not parsed.query and not parsed.fragment
        and (not parsed.path or _SITE_PATH.fullmatch(parsed.path))
        and reference == f"https://{parsed.netloc}{parsed.path}"
    )


def _child_url(parent: str, path: str) -> str:
    return parent + "/" + "/".join(quote(part, safe="") for part in path.split("/"))


def _library_url(site_url: str, library_url: str) -> bool:
    if not isinstance(library_url, str) or not library_url.startswith(site_url + "/"):
        return False
    segment = library_url[len(site_url) + 1:]
    try:
        name = unquote(segment, encoding="utf-8", errors="strict")
    except UnicodeDecodeError:
        return False
    return _name(name) and library_url == _child_url(site_url, name)


def _name(name: str) -> bool:
    return bool(
        isinstance(name, str) and name not in {"", ".", ".."}
        and len(name) <= 255 and name == unicodedata.normalize("NFC", name)
        and not name.endswith((" ", ".")) and "/" not in name and "\\" not in name
        and not any(ord(character) < 32 or ord(character) == 127 for character in name)
    )


def _version(pin: SharePointPin) -> str:
    return f"version:{pin.version};etag:{pin.etag}"


def _read(operation, *args):
    try:
        return operation(*args)
    except SharePointReadError as error:
        if error.status == 403:
            raise SharePointSourceError("PERMISSION_DENIED: metadata request returned HTTP 403") from error
        if error.status == 404:
            raise SharePointSourceError("SOURCE_NOT_FOUND: metadata request returned HTTP 404") from error
        raise SharePointSourceError(
            f"SOURCE_READ_FAILED: metadata request returned HTTP {error.status}"
        ) from error


def _identities(source: SourceLocator, reader: SharePointReader, tenant_id: str
                ) -> tuple[SharePointSite, SharePointLibrary, SharePointDrive]:
    if not isinstance(source, SourceLocator) or source.kind is not SourceKind.SHAREPOINT_LIBRARY:
        raise ValueError("SharePoint inventory requires a sharepoint_library SourceLocator")
    if not _site_reference(source.reference) or not _id(source.library_id):
        raise SharePointSourceError("SOURCE_SCOPE_INVALID: exact canonical site URL and library ID required")
    if not isinstance(tenant_id, str) or not _GUID.fullmatch(tenant_id):
        raise ValueError("an explicit tenant ID is required for SharePoint discovery")
    site = _read(reader.inspect_site, source.reference, tenant_id)
    if (not isinstance(site, SharePointSite) or not _id(site.id)
            or site.web_url != source.reference or site.tenant_id != tenant_id
            or site.permission_evidence != "metadata_read"):
        raise SharePointSourceError("SOURCE_ID_MISMATCH: site URL, tenant or evidence differs")
    library = _read(reader.inspect_library, site.id, source.library_id, tenant_id)
    if (not isinstance(library, SharePointLibrary) or library.site_id != site.id
            or library.id != source.library_id or not _id(library.drive_id)
            or library.tenant_id != tenant_id or library.permission_evidence != "metadata_read"
            or not _library_url(source.reference, library.web_url)):
        raise SharePointSourceError("SOURCE_ID_MISMATCH: library identity, URL or evidence differs")
    drive = _read(reader.inspect_drive, site.id, library.drive_id, tenant_id)
    if (not isinstance(drive, SharePointDrive) or drive.id != library.drive_id
            or drive.site_id != site.id or drive.library_id != library.id
            or not _id(drive.root_item_id) or drive.web_url != library.web_url
            or drive.tenant_id != tenant_id or drive.permission_evidence != "metadata_read"):
        raise SharePointSourceError("SOURCE_ID_MISMATCH: drive, library or tenant differs")
    return site, library, drive


def _pin(item: SharePointItem, path: str, source: SourceLocator,
         site: SharePointSite, drive: SharePointDrive,
         library: SharePointLibrary, limits: SharePointLimits) -> SharePointPin:
    if (not isinstance(item, SharePointItem) or item.site_id != site.id
            or item.drive_id != drive.id or not _id(item.id) or not _id(item.parent_id)
            or item.id == drive.root_item_id or not _name(item.name)
            or path.split("/")[-1] != item.name
            or item.kind not in {"file", "folder"}
            or item.web_url != _child_url(library.web_url, path)
            or item.permission_evidence != "metadata_read"):
        raise SharePointSourceError("SOURCE_ENTRY_INVALID: out-of-scope or unverified item")
    if (not isinstance(item.etag, str) or not item.etag.strip()
            or len(item.etag) > 256 or item.version is not None and (
                not isinstance(item.version, str) or not item.version.strip()
                or len(item.version) > 256
            )):
        raise SharePointSourceError("SOURCE_IDENTITY_MISSING: item ETag or version is invalid")
    if not isinstance(item.size, int) or isinstance(item.size, bool) or item.size < 0:
        raise SharePointSourceError("SOURCE_ENTRY_INVALID: item byte length is missing")
    if item.kind == "file":
        if not item.version:
            raise SharePointSourceError("SOURCE_IDENTITY_MISSING: file version is missing")
        if (not item.name.casefold().endswith((".md", ".txt"))
                or not isinstance(item.media_type, str)
                or item.media_type.lower() not in _MEDIA_TYPES):
            raise SharePointSourceError("SOURCE_ENTRY_UNSUPPORTED: only .md/.txt text files are supported")
        if item.size < 1:
            raise SharePointSourceError("SOURCE_ENTRY_INVALID: empty file")
        if item.size > limits.max_file_bytes:
            raise SharePointSourceError("SOURCE_LIMIT_EXCEEDED: per-file byte limit")
    elif item.media_type is not None:
        raise SharePointSourceError("SOURCE_ENTRY_INVALID: folder contains file metadata")
    return SharePointPin(
        stable_id("sharepoint-item", {
            "source": source.source_id, "site": site.id, "library": library.id,
            "drive": drive.id, "item": item.id,
        }), item.id, item.parent_id, path, item.kind, item.etag, item.version,
        item.size, item.media_type,
    )


def inventory_sharepoint_library(
    source: SourceLocator, reader: SharePointReader, *, tenant_id: str,
    limits: SharePointLimits = SharePointLimits(),
) -> SharePointInventory:
    """Discover metadata only within one exact site/library; never read document bytes."""
    if not isinstance(limits, SharePointLimits):
        raise TypeError("limits must be SharePointLimits")
    site, library, drive = _identities(source, reader, tenant_id)
    pending = [(drive.root_item_id, "", 0)]
    pins: list[SharePointPin] = []
    seen_ids: set[str] = {drive.root_item_id}
    seen_paths: set[str] = set()
    pages = 0
    total = 0
    while pending:
        parent_id, parent_path, depth = pending.pop(0)
        token: str | None = None
        seen_tokens: set[str] = set()
        while True:
            if pages >= limits.max_pages:
                raise SharePointSourceError("SOURCE_LIMIT_EXCEEDED: listing page limit")
            page = _read(reader.list_children, site.id, drive.id, parent_id,
                         token, limits.page_size, tenant_id)
            pages += 1
            if (not isinstance(page, SharePointPage)
                    or page.site_id != site.id or page.drive_id != drive.id
                    or page.parent_id != parent_id or page.permission_evidence != "children_listed"
                    or not isinstance(page.items, tuple) or len(page.items) > limits.page_size):
                raise SharePointSourceError("SOURCE_ENTRY_INVALID: out-of-scope or malformed page")
            for item in page.items:
                if not isinstance(item, SharePointItem) or item.parent_id != parent_id:
                    raise SharePointSourceError("SOURCE_ENTRY_INVALID: item parent differs")
                path = parent_path + "/" + item.name if parent_path else item.name
                if depth + 1 > limits.max_depth or len(path) > 1024:
                    raise SharePointSourceError("SOURCE_LIMIT_EXCEEDED: item path or depth limit")
                pin = _pin(item, path, source, site, drive, library, limits)
                path_key = unicodedata.normalize("NFC", path).casefold()
                if pin.id in seen_ids or path_key in seen_paths:
                    raise SharePointSourceError("SOURCE_ENTRY_INVALID: duplicate item, path or folder cycle")
                seen_ids.add(pin.id)
                seen_paths.add(path_key)
                pins.append(pin)
                if len(pins) > limits.max_entries:
                    raise SharePointSourceError("SOURCE_LIMIT_EXCEEDED: entry count limit")
                if pin.kind == "folder":
                    pending.append((pin.id, path, depth + 1))
                else:
                    total += pin.size
                    if total > limits.max_total_bytes:
                        raise SharePointSourceError("SOURCE_LIMIT_EXCEEDED: total byte limit")
            if page.next_token is None:
                break
            next_token = page.next_token
            if (not isinstance(next_token, str) or not 0 < len(next_token) <= 2048
                    or any(character.isspace() or character in "/\\?#" for character in next_token)
                    or "://" in next_token or next_token == token
                    or next_token in seen_tokens or not page.items):
                raise SharePointSourceError("SOURCE_ENTRY_INVALID: ambiguous listing continuation")
            seen_tokens.add(next_token)
            token = next_token
    files = [pin for pin in pins if pin.kind == "file"]
    if not files:
        raise SharePointSourceError("EMPTY_MANIFEST: library contains no supported documents")
    pins.sort(key=lambda pin: pin.path)
    items = tuple(ManifestItem(
        source_id=pin.source_id,
        original_uri=_child_url(library.web_url, pin.path),
        citation_uri=_child_url(library.web_url, pin.path),
        media_type=pin.media_type or "",
        version_or_hash=_version(pin),
    ) for pin in pins if pin.kind == "file")
    manifest = SourceManifest("1", source, datetime.now(timezone.utc).isoformat(), items)
    return SharePointInventory(manifest, site.id, library.id, drive.id,
                               drive.root_item_id, library.web_url, tuple(pins),
                               pages, len(pins), len(files), len(pins) - len(files), total)


def recheck_sharepoint_inventory(
    inventory: SharePointInventory, reader: SharePointReader, *, tenant_id: str,
    limits: SharePointLimits = SharePointLimits(),
) -> None:
    """Re-list the whole library and re-read each item's metadata before any future handoff."""
    if not isinstance(inventory, SharePointInventory):
        raise TypeError("inventory must be SharePointInventory")
    fresh = inventory_sharepoint_library(inventory.manifest.source, reader,
                                         tenant_id=tenant_id, limits=limits)
    if (fresh.manifest.digest != inventory.manifest.digest
            or fresh.pins != inventory.pins
            or (fresh.site_id, fresh.library_id, fresh.drive_id, fresh.root_item_id,
                fresh.library_web_url) != (inventory.site_id, inventory.library_id,
                                           inventory.drive_id, inventory.root_item_id,
                                           inventory.library_web_url)):
        raise SharePointSourceError("SOURCE_DRIFT: site, drive, membership or item identity changed")
    site = SharePointSite(inventory.site_id, inventory.manifest.source.reference,
                          tenant_id, "metadata_read")
    library = SharePointLibrary(inventory.library_id, inventory.site_id, inventory.drive_id,
                                inventory.library_web_url, tenant_id, "metadata_read")
    drive = SharePointDrive(inventory.drive_id, inventory.site_id, inventory.library_id,
                            inventory.root_item_id, inventory.library_web_url,
                            tenant_id, "metadata_read")
    for pin in inventory.pins:
        item = _read(reader.get_item, site.id, drive.id, pin.id, tenant_id)
        if (not isinstance(item, SharePointItem) or item.parent_id != pin.parent_id
                or _pin(item, pin.path, inventory.manifest.source, site, drive,
                        library, limits) != pin):
            raise SharePointSourceError("SOURCE_DRIFT: item metadata changed")
