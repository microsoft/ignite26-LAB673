"""Integrity checks shared by both Consume readers."""

from __future__ import annotations

import math
import struct
from typing import Any

from grz_core.contracts import ContractError, Descriptor, digest

KINDS = ("representative", "membership", "evidence")
LABEL_STATUSES = ("unnamed", "named", "failed")


def fail(detail: str) -> None:
    raise ContractError("SIDECAR_INTEGRITY_FAILED", detail)


def _single(value: Any) -> Any:
    # Search stores centroids as Edm.Single and returns the shortest float32 decimal.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


def normalize_document(row: dict[str, Any]) -> dict[str, Any]:
    """Drop null/empty/Search-metadata fields and round centroids to their stored float32 values."""
    # Search returns unset Collection fields (e.g. centroid on evidence rows) as [].
    normalized = {key: value for key, value in row.items()
                  if value is not None and value != [] and not key.startswith("@search.")}
    for vector_field in ("centroid", "chunk_vector"):
        if isinstance(normalized.get(vector_field), (list, tuple)):
            normalized[vector_field] = [_single(x) for x in normalized[vector_field]]
    return normalized


def documents_digest(documents: list[dict[str, Any]]) -> str:
    """Digest stable fields, ignoring absent/null fields and Search metadata."""
    normalized = [normalize_document(row) for row in documents]
    return digest(sorted(normalized, key=lambda row: (row["kind"], row["id"])))


def check_manifest_identity(payload: Any, descriptor: Descriptor) -> dict[str, Any]:
    """The manifest must describe exactly the generation the descriptor binds."""
    if not isinstance(payload, dict):
        fail("Manifest payload is required")
    for field, expected in (
        ("schema_version", descriptor.schema_version),
        ("generation_id", descriptor.generation_id),
        ("physical_index", descriptor.physical_index),
        ("source_service", descriptor.source_service),
        ("source_index", descriptor.source_index),
        ("embedding_model_id", descriptor.embedding_model_id),
        ("dimension", descriptor.dimension),
        ("visibility", "public"),
    ):
        if field == "visibility" and payload.get(field) != expected:
            raise ContractError("VISIBILITY_UNSUPPORTED", "Manifest must verify a public corpus")
        if payload.get(field) != expected:
            fail(f"Manifest {field} does not match descriptor")
    if payload.get("source_visibility", "public") != "public" or payload.get("acl_mode", "public-only") != "public-only":
        raise ContractError("VISIBILITY_UNSUPPORTED", "Restricted source or ACL mode is unsupported")
    if payload.get("visibility_basis", "per-document") != descriptor.visibility_basis:
        fail("Manifest visibility_basis does not match descriptor")
    return payload


def check_build_health(payload: dict[str, Any]) -> None:
    health = payload.get("health")
    state = health if isinstance(health, str) else health.get("state") if isinstance(health, dict) else None
    if state not in ("verified", "published"):
        fail("Manifest build health is not verified")


def is_valid_representative(row: dict[str, Any], descriptor: Descriptor) -> bool:
    vector = row.get("centroid")
    return not (
        not isinstance(row.get("community_id"), str) or not row["community_id"]
        or type(row.get("level")) is not int or row["level"] < 0
        or type(row.get("member_count")) is not int or row["member_count"] < 1
        or row.get("embedding_model_id") != descriptor.embedding_model_id
        or row.get("label_status") not in LABEL_STATUSES
        or not isinstance(vector, list) or len(vector) != descriptor.dimension
        or not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in vector)
        or not math.isfinite(math.hypot(*vector)) or math.hypot(*vector) == 0
    )


def has_evidence_text(row: dict[str, Any]) -> bool:
    return (isinstance(row.get("source_id"), str) and bool(row["source_id"])
            and isinstance(row.get("text"), str) and bool(row["text"]))


def community_summary(row: dict[str, Any], children: list[str]) -> dict[str, Any]:
    return {
        "community_id": row["community_id"],
        "level": row["level"],
        "parent_id": row.get("parent_id"),
        "children": sorted(children),
        "member_count": row["member_count"],
        "label": row.get("label"),
        "label_status": row["label_status"],
    }


def member_summary(membership: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    return {"chunk_id": membership["chunk_id"], "source_id": evidence["source_id"],
            "sort_key": membership["sort_key"]}
