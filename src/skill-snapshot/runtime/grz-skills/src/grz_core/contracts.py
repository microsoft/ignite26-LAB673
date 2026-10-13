"""Versioned standalone contracts and deterministic identities."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Literal

INPUT_VERSION = "grz-input-v1"
BUILD_VERSION = "grz-build-v1"
SIDECAR_VERSION = "grz-sidecar-v2"
DESCRIPTOR_VERSION = "grz-descriptor-v1"
ALGORITHM_REVISION = "grz-native-poc-v1"
PINNED_DEPENDENCIES = {"numpy": "2.2.6", "GRZBuildPoc": "0.1.4-local"}


class ContractError(ValueError):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


SIDECAR_VERSIONS = ("grz-sidecar-v1", SIDECAR_VERSION)
VISIBILITY_BASES = ("per-document", "public-attested")


def attestation_text(index: str) -> str:
    return f"You're confirming every document in {index} is public"


def require_public(visibility: str | None) -> None:
    if visibility != "public":
        raise ContractError("VISIBILITY_UNSUPPORTED", "Only verified public/synthetic data is supported")


@dataclass(frozen=True)
class SourceIdentity:
    service: str
    index: str
    frozen_generation: str
    embedding_model_id: str
    dimension: int
    visibility: str
    expected_count: int
    owner_approval: str | None = None

    def validate(self, live: bool = False) -> None:
        require_public(self.visibility)
        if not all((self.service, self.index, self.frozen_generation, self.embedding_model_id)):
            raise ContractError("SOURCE_IDENTITY_INVALID", "Service, index, freeze evidence and model ID are required")
        if self.dimension < 1 or self.expected_count < 1:
            raise ContractError("SOURCE_IDENTITY_INVALID", "Positive dimension and count are required")
        if live and not self.owner_approval:
            raise ContractError("OWNER_APPROVAL_REQUIRED", "Named source and security inspection approval required")


@dataclass(frozen=True)
class BuildProfile:
    k: int = 10
    candidate_probes: int = 32
    similarity_cutoff: float = 0.0
    cluster_size_limit: int = 1000
    memory_budget_bytes: int = 512_000_000
    seed: int = 42
    strategy: Literal["exact", "hnsw"] = "exact"
    version: str = BUILD_VERSION

    def validate(self) -> None:
        if self.version != BUILD_VERSION or self.k < 1 or self.candidate_probes < self.k:
            raise ContractError("BUILD_PROFILE_INVALID", "Unsupported version, k or probe count")
        if not -1 <= self.similarity_cutoff <= 1 or self.cluster_size_limit < 1 or self.memory_budget_bytes < 1:
            raise ContractError("BUILD_PROFILE_INVALID", "Invalid cutoff, cluster limit or memory budget")


@dataclass(frozen=True)
class Descriptor:
    physical_index: str
    generation_id: str
    source_service: str
    source_index: str
    embedding_model_id: str
    dimension: int
    visibility: str = "public"
    schema_version: str = SIDECAR_VERSION
    version: str = DESCRIPTOR_VERSION
    visibility_basis: str = "per-document"

    def validate(self) -> None:
        require_public(self.visibility)
        if self.visibility_basis not in VISIBILITY_BASES:
            raise ContractError("DESCRIPTOR_INVALID", "Unknown visibility basis")
        if self.version != DESCRIPTOR_VERSION or self.schema_version not in SIDECAR_VERSIONS:
            raise ContractError("SCHEMA_UNSUPPORTED", "Descriptor/schema version mismatch")
        if not all((self.physical_index, self.generation_id, self.source_service, self.source_index, self.embedding_model_id)) or self.dimension < 1:
            raise ContractError("DESCRIPTOR_INVALID", "Incomplete physical index/generation/model identity")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def document_id(generation_id: str, kind: str, stable_id: str) -> str:
    return digest([generation_id, kind, stable_id])


def community_id(generation_id: str, level: int, members: list[str]) -> str:
    if len(members) != len(set(members)):
        raise ContractError("DUPLICATE_MEMBER", "Community IDs require unique members")
    return digest([generation_id, level, sorted(members)])


def validate_alias(alias: str) -> None:
    """The one serving-alias rule: GRZ owns only lowercase Search-safe names under grz-."""
    if not alias.startswith("grz-") or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in alias):
        raise ContractError("ALIAS_INVALID", "GRZ serving aliases must start with grz- and be lowercase Search-safe")
