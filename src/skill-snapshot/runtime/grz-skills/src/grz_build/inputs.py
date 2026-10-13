"""Strict, offline portable snapshot loading for public/synthetic input."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from grz_core.contracts import INPUT_VERSION, ContractError, SourceIdentity, digest, require_public


@dataclass(frozen=True)
class Snapshot:
    source: SourceIdentity
    rows: tuple[dict[str, str], ...]
    vectors: np.ndarray
    digest: str

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(row["chunk_id"] for row in self.rows)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("INPUT_MALFORMED", f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _json(raw: str, label: str) -> Any:
    try:
        return json.loads(
            raw, object_pairs_hook=_unique_object,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except (ValueError, TypeError) as exc:
        raise ContractError("INPUT_MALFORMED", f"Invalid JSON in {label}") from exc


def _file(root: Path, name: Any) -> Path:
    if not isinstance(name, str) or not name or Path(name).is_absolute() or Path(name).drive:
        raise ContractError("INPUT_MALFORMED", "Snapshot file must be a relative path")
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ContractError("INPUT_MALFORMED", "Snapshot file must exist under manifest directory")
    return path


def _records(path: Path, expected_hash: Any) -> list[Any]:
    if expected_hash is not None and (
        not isinstance(expected_hash, str) or len(expected_hash) != 64
        or any(c not in "0123456789abcdef" for c in expected_hash)
    ):
        raise ContractError("INPUT_MALFORMED", "Invalid SHA-256 declaration")
    sha = hashlib.sha256()
    records = []
    with path.open("rb") as stream:
        for line in stream:
            sha.update(line)
            try:
                records.append(_json(line.decode("utf-8"), path.name))
            except UnicodeError as exc:
                raise ContractError("INPUT_MALFORMED", "JSONL must be UTF-8") from exc
    if expected_hash is not None and sha.hexdigest() != expected_hash:
        raise ContractError("INPUT_HASH_MISMATCH", f"Checksum mismatch: {path.name}")
    if not records:
        raise ContractError("INPUT_MALFORMED", f"Empty JSONL: {path.name}")
    return records


def _id(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def load_snapshot(path: str | Path) -> Snapshot:
    """Load a grz-input-v1 manifest, joining rows/vectors by unique case-sensitive ID."""
    manifest_path = Path(path).resolve()
    try:
        manifest = _json(manifest_path.read_text(encoding="utf-8"), manifest_path.name)
    except UnicodeError as exc:
        raise ContractError("INPUT_MALFORMED", "Manifest must be UTF-8") from exc
    required = {"version", "source", "rows_file", "vectors_file"}
    allowed = required | {"rows_sha256", "vectors_sha256", "provenance_status"}
    if not isinstance(manifest, dict) or not required <= manifest.keys() or manifest.keys() - allowed:
        raise ContractError("INPUT_MALFORMED", "Invalid manifest fields")
    if manifest["version"] != INPUT_VERSION:
        raise ContractError("SCHEMA_UNSUPPORTED", "Unsupported snapshot version")
    if "provenance_status" in manifest and manifest["provenance_status"] not in (
        "synthetic", "owner-attested", "verified",
    ):
        raise ContractError("INPUT_MALFORMED", "Unknown provenance")
    source_fields = {"service", "index", "frozen_generation", "embedding_model_id",
                     "dimension", "visibility", "expected_count"}
    fields = manifest["source"]
    if not isinstance(fields, dict) or not source_fields <= fields.keys() or fields.keys() - (source_fields | {"owner_approval"}):
        raise ContractError("INPUT_MALFORMED", "Invalid source identity fields")
    require_public(fields["visibility"])
    if any(not _id(fields[key]) for key in ("service", "index", "frozen_generation", "embedding_model_id")):
        raise ContractError("SOURCE_IDENTITY_INVALID", "Incomplete source identity")
    if any(type(fields[key]) is not int or fields[key] < 1 for key in ("dimension", "expected_count")):
        raise ContractError("SOURCE_IDENTITY_INVALID", "Positive integer dimension/count required")
    if "owner_approval" in fields and fields["owner_approval"] is not None and not _id(fields["owner_approval"]):
        raise ContractError("SOURCE_IDENTITY_INVALID", "Invalid owner approval")
    source = SourceIdentity(**fields)
    source.validate()
    rows_path = _file(manifest_path.parent, manifest["rows_file"])
    vectors_path = _file(manifest_path.parent, manifest["vectors_file"])
    if rows_path == vectors_path:
        raise ContractError("INPUT_MALFORMED", "Rows and vectors must be separate files")
    raw_rows = _records(rows_path, manifest.get("rows_sha256"))
    raw_vectors = _records(vectors_path, manifest.get("vectors_sha256"))
    rows: dict[str, dict[str, str]] = {}
    for row in raw_rows:
        if not isinstance(row, dict) or set(row) != {"chunk_id", "text", "source", "visibility"}:
            raise ContractError("INPUT_MALFORMED", "Invalid chunk row fields")
        require_public(row["visibility"])
        if not all(_id(row[key]) for key in ("chunk_id", "text", "source")):
            raise ContractError("INPUT_MALFORMED", "Chunk ID, text and source must be nonempty strings")
        if row["chunk_id"] in rows:
            raise ContractError("INPUT_DUPLICATE_ID", "Duplicate chunk ID")
        rows[row["chunk_id"]] = row
    vectors: dict[str, np.ndarray] = {}
    original_vectors: dict[str, list[int | float]] = {}
    for item in raw_vectors:
        if not isinstance(item, dict) or set(item) != {"chunk_id", "embedding"} or not _id(item["chunk_id"]):
            raise ContractError("INPUT_MALFORMED", "Invalid vector row fields")
        key = item["chunk_id"]
        if key in vectors:
            raise ContractError("INPUT_DUPLICATE_ID", "Duplicate vector ID")
        values = item["embedding"]
        if (not isinstance(values, list) or len(values) != source.dimension
                or any(type(value) not in (int, float) for value in values)):
            raise ContractError("INPUT_VECTOR_INVALID", "Vector dimension or numeric values invalid")
        try:
            array = np.asarray(values, dtype=np.float64)
        except (ValueError, OverflowError) as exc:
            raise ContractError("INPUT_VECTOR_INVALID", "Invalid numeric vector") from exc
        if not np.isfinite(array).all():
            raise ContractError("INPUT_VECTOR_INVALID", "Nonfinite vector")
        norm = np.linalg.norm(array)
        if not np.isfinite(norm) or norm <= 0:
            raise ContractError("INPUT_VECTOR_INVALID", "Zero or unrepresentable vector")
        normalized = (array / norm).astype(np.float32)
        if not np.isfinite(normalized).all() or not np.any(normalized):
            raise ContractError("INPUT_VECTOR_INVALID", "Vector cannot be represented in float32")
        normalized /= np.linalg.norm(normalized)
        vectors[key] = normalized
        original_vectors[key] = values
    if len(raw_rows) != source.expected_count or len(raw_vectors) != source.expected_count:
        raise ContractError("INPUT_COUNT_MISMATCH", "Source count does not match JSONL files")
    if rows.keys() != vectors.keys():
        raise ContractError("INPUT_ID_MISMATCH", "Row and vector IDs do not match")
    keys = sorted(rows)
    matrix = np.ascontiguousarray(np.stack([vectors[key] for key in keys]))
    matrix.flags.writeable = False
    identity = digest({
        "source": asdict(source), "provenance_status": manifest.get("provenance_status"),
        "rows": [rows[key] for key in keys],
        "raw_vectors": [original_vectors[key] for key in keys],
        "vectors_sha256": hashlib.sha256(matrix.tobytes()).hexdigest(),
    })
    return Snapshot(source, tuple(rows[key] for key in keys), matrix, identity)
