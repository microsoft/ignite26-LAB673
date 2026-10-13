"""Read-only local folder and ZIP source inventory with approval-bound bytes."""

from __future__ import annotations

import hashlib
import os
import stat
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from ekg_core.models import ManifestItem, SourceKind, SourceLocator, SourceManifest, stable_id


class SourceAdapterError(ValueError):
    """The local source cannot be inventoried or no longer matches approval."""


@dataclass(frozen=True)
class SourceLimits:
    max_entries: int = 10_000
    max_documents: int = 5_000
    max_file_bytes: int = 16 * 1024 * 1024
    max_total_bytes: int = 256 * 1024 * 1024
    max_archive_bytes: int = 256 * 1024 * 1024
    max_expansion_ratio: int = 100
    max_path_length: int = 1024
    max_depth: int = 32

    def __post_init__(self) -> None:
        if any(not isinstance(value, int) or isinstance(value, bool) or value <= 0
               for value in vars(self).values()):
            raise ValueError("source limits must be positive integers")


DEFAULT_LIMITS = SourceLimits()


@dataclass(frozen=True)
class ApprovedSourceBytes:
    item: ManifestItem
    content: bytes


def _path_parts(name: str, limits: SourceLimits) -> tuple[str, ...]:
    if (not name or name.startswith("/") or "\\" in name or
            len(name) > limits.max_path_length):
        raise SourceAdapterError(f"unsafe source path: {name!r}")
    parts = tuple(name.split("/"))
    if len(parts) > limits.max_depth:
        raise SourceAdapterError(f"source path exceeds depth limit: {name!r}")
    for part in parts:
        if (part in {"", ".", ".."} or part.endswith((" ", ".")) or ":" in part
                or any(ord(char) < 32 for char in part)
                or part.split(".", 1)[0].upper() in {
                    "CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                    *(f"LPT{i}" for i in range(1, 10)),
                }):
            raise SourceAdapterError(f"unsafe source path: {name!r}")
    return parts


def _key(parts: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(unicodedata.normalize("NFC", part).casefold() for part in parts)


def _no_link(path: Path) -> os.stat_result:
    info = path.lstat()
    if (stat.S_ISLNK(info.st_mode) or
            getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
        raise SourceAdapterError(f"source link or reparse point is not allowed: {path}")
    return info


def _source_path(reference: str) -> Path:
    path = Path(reference).absolute()
    for parent in reversed((path, *path.parents)):
        _no_link(parent)
    return path


def _same_file(left: os.stat_result, right: os.stat_result) -> bool:
    return all(getattr(left, name) == getattr(right, name) for name in (
        "st_dev", "st_ino", "st_size", "st_mtime_ns",
    ))


def _read_bytes(stream, max_bytes: int) -> bytes:
    data = bytearray()
    while chunk := stream.read(min(64 * 1024, max_bytes + 1 - len(data))):
        data.extend(chunk)
        if len(data) > max_bytes:
            raise SourceAdapterError("source file exceeds byte limit")
    return bytes(data)


def _eligible(name: str) -> bool:
    return Path(name).suffix.casefold() in {".md", ".txt"}


def _snapshot(source: SourceLocator, limits: SourceLimits) -> tuple[SourceManifest, tuple[ApprovedSourceBytes, ...]]:
    if source.kind not in {SourceKind.LOCAL_PATH, SourceKind.ZIP_ARCHIVE}:
        raise SourceAdapterError("local adapter requires a local_path or zip_archive locator")
    if not isinstance(limits, SourceLimits):
        raise TypeError("limits must be SourceLimits")
    path = _source_path(source.reference)
    items: list[tuple[str, ApprovedSourceBytes]] = []
    entries = 0
    total = 0

    def add(name: str, content: bytes, original_uri: str, archive_hash: str | None = None) -> None:
        if len(items) >= limits.max_documents:
            raise SourceAdapterError("source exceeds document count limit")
        identity = {"source_id": source.source_id, "path": name}
        if archive_hash is not None:
            identity["archive_sha256"] = archive_hash
        item = ManifestItem(
            source_id=stable_id("source-item", identity),
            original_uri=original_uri,
            citation_uri=original_uri,
            media_type="text/markdown" if name.casefold().endswith(".md") else "text/plain",
            version_or_hash=f"sha256:{hashlib.sha256(content).hexdigest()}",
        )
        items.append((name, ApprovedSourceBytes(item, content)))

    if source.kind is SourceKind.LOCAL_PATH:
        root = _no_link(path)
        if not (stat.S_ISDIR(root.st_mode) or stat.S_ISREG(root.st_mode)):
            raise SourceAdapterError("local source must be a regular file or folder")
        if stat.S_ISREG(root.st_mode) and not _eligible(path.name):
            raise SourceAdapterError("local source file must be .md or .txt")
        seen: set[tuple[str, ...]] = set()

        def walk(current: Path, relative: str = "") -> None:
            nonlocal entries, total
            before = _no_link(current)
            if stat.S_ISDIR(before.st_mode):
                with os.scandir(current) as listing:
                    children = sorted(list(listing), key=lambda entry: _key((entry.name,)))
                for child in children:
                    entries += 1
                    if entries > limits.max_entries:
                        raise SourceAdapterError("source exceeds entry count limit")
                    name = f"{relative}/{child.name}" if relative else child.name
                    key = _key(_path_parts(name, limits))
                    if key in seen:
                        raise SourceAdapterError(f"ambiguous source path: {name!r}")
                    seen.add(key)
                    walk(Path(child.path), name)
                if not _same_file(before, _no_link(current)):
                    raise SourceAdapterError(f"source changed during inventory: {current}")
                return
            if not stat.S_ISREG(before.st_mode):
                raise SourceAdapterError(f"source contains a non-regular entry: {current}")
            if not _eligible(current.name):
                return
            if before.st_size > limits.max_file_bytes:
                raise SourceAdapterError("source file exceeds byte limit")
            if total + before.st_size > limits.max_total_bytes:
                raise SourceAdapterError("source exceeds total byte limit")
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
            with os.fdopen(os.open(current, flags), "rb") as stream:
                if not _same_file(before, os.fstat(stream.fileno())):
                    raise SourceAdapterError(f"source changed during inventory: {current}")
                content = _read_bytes(stream, limits.max_file_bytes)
                if not _same_file(before, os.fstat(stream.fileno())):
                    raise SourceAdapterError(f"source changed during inventory: {current}")
            if not _same_file(before, _no_link(current)):
                raise SourceAdapterError(f"source changed during inventory: {current}")
            total += len(content)
            if total > limits.max_total_bytes:
                raise SourceAdapterError("source exceeds total byte limit")
            add(relative or current.name, content, current.as_uri())

        walk(path)
    else:
        archive = _no_link(path)
        if not stat.S_ISREG(archive.st_mode):
            raise SourceAdapterError("ZIP source must be a regular file")
        if archive.st_size > limits.max_archive_bytes:
            raise SourceAdapterError("ZIP exceeds archive byte limit")
        files: set[tuple[str, ...]] = set()
        directories: set[tuple[str, ...]] = set()
        explicit: set[tuple[str, ...]] = set()
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        with os.fdopen(os.open(path, flags), "rb") as stream:
            if not _same_file(archive, os.fstat(stream.fileno())):
                raise SourceAdapterError("ZIP changed during inventory")
            archive_digest = hashlib.sha256()
            archive_length = 0
            while block := stream.read(1024 * 1024):
                archive_length += len(block)
                if archive_length > limits.max_archive_bytes:
                    raise SourceAdapterError("ZIP exceeds archive byte limit")
                archive_digest.update(block)
            if archive_length != archive.st_size or not _same_file(archive, os.fstat(stream.fileno())):
                raise SourceAdapterError("ZIP changed during inventory")
            stream.seek(0)
            archive_hash = archive_digest.hexdigest()
            with zipfile.ZipFile(stream) as zipped:
                for info in zipped.infolist():
                    entries += 1
                    if entries > limits.max_entries:
                        raise SourceAdapterError("ZIP exceeds entry count limit")
                    _path_parts(
                        info.orig_filename[:-1] if info.is_dir() else info.orig_filename,
                        limits,
                    )
                    name = info.filename[:-1] if info.is_dir() else info.filename
                    key = _key(_path_parts(name, limits))
                    if key in explicit:
                        raise SourceAdapterError(f"ambiguous ZIP entry: {name!r}")
                    explicit.add(key)
                    if info.flag_bits & 1:
                        raise SourceAdapterError(f"encrypted ZIP entry: {name!r}")
                    mode = info.external_attr >> 16
                    kind = stat.S_IFMT(mode)
                    if kind not in {0, stat.S_IFDIR if info.is_dir() else stat.S_IFREG}:
                        raise SourceAdapterError(f"ZIP contains a link or special entry: {name!r}")
                    for depth in range(1, len(key)):
                        parent = key[:depth]
                        if parent in files:
                            raise SourceAdapterError(f"ZIP file/directory collision: {name!r}")
                        directories.add(parent)
                    if info.is_dir():
                        if key in files:
                            raise SourceAdapterError(f"ZIP file/directory collision: {name!r}")
                        directories.add(key)
                        continue
                    if key in directories:
                        raise SourceAdapterError(f"ZIP file/directory collision: {name!r}")
                    files.add(key)
                    if (info.file_size > limits.max_file_bytes or
                            total + info.file_size > limits.max_total_bytes):
                        raise SourceAdapterError("ZIP exceeds uncompressed byte limit")
                    if info.file_size > limits.max_expansion_ratio * max(info.compress_size, 1):
                        raise SourceAdapterError("ZIP exceeds expansion ratio limit")
                    with zipped.open(info) as member:
                        content = _read_bytes(member, limits.max_file_bytes)
                    if len(content) != info.file_size:
                        raise SourceAdapterError(f"ZIP entry size changed: {name!r}")
                    total += len(content)
                    if total > limits.max_total_bytes:
                        raise SourceAdapterError("ZIP exceeds uncompressed byte limit")
                    if _eligible(name):
                        add(name, content, f"zip+{path.as_uri()}!/{quote(name, safe='/')}", archive_hash)
            if not _same_file(archive, os.fstat(stream.fileno())):
                raise SourceAdapterError("ZIP changed during inventory")
        if not _same_file(archive, _no_link(path)):
            raise SourceAdapterError("ZIP changed during inventory")

    if not items:
        raise SourceAdapterError("source has no eligible .md or .txt documents")
    ordered = tuple(value for _, value in sorted(items, key=lambda pair: _key(tuple(pair[0].split("/")))))
    manifest = SourceManifest(
        version="1", source=source, observed_at=datetime.now(timezone.utc).isoformat(),
        items=tuple(value.item for value in ordered),
    )
    return manifest, ordered


def inventory_local_source(
    source: SourceLocator, *, limits: SourceLimits = DEFAULT_LIMITS,
) -> SourceManifest:
    """Inventory eligible local bytes without staging or changing the source."""
    try:
        return _snapshot(source, limits)[0]
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile, EOFError,
            NotImplementedError, RuntimeError) as error:
        raise SourceAdapterError(f"cannot inventory local source: {error}") from error


def approved_local_bytes(
    manifest: SourceManifest, approved_manifest_digest: str, *,
    limits: SourceLimits = DEFAULT_LIMITS,
) -> tuple[ApprovedSourceBytes, ...]:
    """Return an all-or-nothing byte snapshot only if source and approval still match."""
    if not isinstance(manifest, SourceManifest):
        raise TypeError("manifest must be a SourceManifest")
    if approved_manifest_digest != manifest.digest:
        raise SourceAdapterError("approved manifest digest differs")
    try:
        current, contents = _snapshot(manifest.source, limits)
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile, EOFError,
            NotImplementedError, RuntimeError) as error:
        raise SourceAdapterError(f"cannot verify local source: {error}") from error
    if current.digest != approved_manifest_digest or current.items != manifest.items:
        raise SourceAdapterError("local source changed after approval")
    return contents


def approved_local_sample(
    manifest: SourceManifest, corpus_digest: str, *,
    limits: SourceLimits = DEFAULT_LIMITS,
) -> tuple[ApprovedSourceBytes, ...]:
    """A trial stages a subset: the whole source must still match the approved corpus
    digest, and each sampled item must match exactly. Returned in manifest order."""
    try:
        current, contents = _snapshot(manifest.source, limits)
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile, EOFError,
            NotImplementedError, RuntimeError) as error:
        raise SourceAdapterError(f"cannot verify local source: {error}") from error
    if current.digest != corpus_digest:
        raise SourceAdapterError("local source changed after approval")
    found = {value.item.source_id: value for value in contents}
    if any(found.get(item.source_id) is None or found[item.source_id].item != item
           for item in manifest.items):
        raise SourceAdapterError("trial sample differs from the approved corpus")
    return tuple(found[item.source_id] for item in manifest.items)
