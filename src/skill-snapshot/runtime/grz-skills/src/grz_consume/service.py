"""Validated, generation-bound browsing of the candidate sidecar."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from grz_core.adapters import ReadStore
from grz_core.contracts import ContractError, Descriptor, SIDECAR_VERSION

from .bounded_azure import BoundedAzureReader
from .checks import documents_digest, normalize_document
from .search_store import AzureSearchReadStore

if TYPE_CHECKING:
    from .native_reader import NativeConsumeReader

__all__ = ["ConsumeService", "documents_digest", "normalize_document"]


def __getattr__(name: str) -> Any:
    if name == "NativeConsumeReader":
        from .native_reader import NativeConsumeReader
        return NativeConsumeReader
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _check_level(level: Any) -> None:
    if type(level) is not int or level < 0:
        raise ContractError("LEVEL_INVALID", "level must be a nonnegative integer")


BROWSE_TARGET = 20
MAX_RANKED_MEMBERS = 50
CANDIDATE_FACTOR = 4


def browse_level(per_level: dict[int, int]) -> int | None:
    """Pick the level a person can scan at a glance: 10-30 communities, else the count nearest 20."""
    if not per_level:
        return None
    return min(per_level, key=lambda level: (not 10 <= per_level[level] <= 30,
                                             abs(per_level[level] - BROWSE_TARGET), -level))


def _validate_top_k(k: Any) -> int:
    if type(k) is not int or not 1 <= k <= MAX_RANKED_MEMBERS:
        raise ContractError("LIMIT_INVALID", "top_k must be between 1 and 50")
    return k


def _normalize_query_vector(vector: Any, dimension: int) -> list[float]:
    if (
        not isinstance(vector, (list, tuple)) or len(vector) != dimension
        or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in vector)
    ):
        raise ContractError("QUERY_VECTOR_INVALID", "Question vector must be finite and match descriptor dimension")
    norm = math.sqrt(sum(float(x) * float(x) for x in vector))
    if not norm or not math.isfinite(norm):
        raise ContractError("QUERY_VECTOR_INVALID", "Question vector must have finite nonzero norm")
    return [float(x) / norm for x in vector]


class ConsumeService:
    """Browse one explicitly bound physical generation without alias privileges.

    The store needs only read access: no alias, index-management, embedding or
    mutation capability. Callers opt into a new descriptor when a publisher cuts
    over the serving alias. Azure Search stores use a bounded or native reader.
    """

    def __init__(self, store: ReadStore, descriptor: Descriptor):
        descriptor.validate()
        self.store = store
        self.descriptor = descriptor
        if hasattr(store, "native_reader"):
            self._reader = store.native_reader(descriptor)
        elif isinstance(store, AzureSearchReadStore):
            self._reader = BoundedAzureReader(store, descriptor)
        else:
            raise ContractError("SOURCE_REQUIRED", "This snapshot requires an Azure Search reader")

    def status(self) -> dict[str, Any]:
        payload = self._reader.manifest_payload()
        per_level = self._reader.level_counts()
        res = {
            "physical_index": self.descriptor.physical_index,
            "generation_id": self.descriptor.generation_id,
            "schema_version": self.descriptor.schema_version,
            "visibility_basis": self.descriptor.visibility_basis,
            "build_health": payload.get("health", "unknown"),
            "active": "unknown",
            "verified": True,
            "verification_scope": self._reader.verification_scope,
            "communities_per_level": {str(level): count for level, count in per_level.items()},
            "browse_level": browse_level(per_level),
        }
        for k in (
            "assigned_node_count",
            "unassigned_source_document_count",
            "node_coverage",
            "source_document_count",
            "isolated_node_count",
        ):
            if k in payload:
                res[k] = payload[k]
        return res

    def browse_level(self) -> int | None:
        """The level to show when the caller doesn't pick one."""
        return browse_level(self._reader.level_counts())

    def representatives_at(self, level: int) -> tuple[list[dict[str, Any]], int]:
        """Validated representatives (with centroids) at one level plus the evidence count."""
        _check_level(level)
        return self._reader.representatives_at(level)

    def list_communities(
        self, level: int | None = None, page_size: int = 100, cursor: str | None = None
    ) -> dict[str, Any]:
        if level is not None:
            _check_level(level)
        return self._reader.list_communities(level, page_size, cursor)

    def get_community(
        self, community_id: str, children_page_size: int = 1000, children_cursor: str | None = None,
    ) -> dict[str, Any]:
        return self._reader.get_community(community_id, children_page_size, children_cursor)

    def list_members(self, community_id: str, page_size: int = 100, cursor: str | None = None) -> dict[str, Any]:
        return self._reader.list_members(community_id, page_size, cursor)

    def get_chunk(self, chunk_id: str) -> dict[str, Any]:
        return self._reader.get_chunk(chunk_id)

    def rank_members(self, community_id: str, question_vector: list[float], k: int = 10) -> dict[str, Any]:
        """Rank this community's evidence chunks against one normalized question vector."""
        k = _validate_top_k(k)
        if self.descriptor.schema_version != SIDECAR_VERSION:
            raise ContractError(
                "MEMBER_RANKING_UNAVAILABLE",
                "This generation predates question-ranked members; rebuild it, or list members without a question",
            )
        vector = _normalize_query_vector(question_vector, self.descriptor.dimension)
        community = self.get_community(community_id)
        candidates = min(k * CANDIDATE_FACTOR, 200)
        if isinstance(self._reader, BoundedAzureReader):
            rows = self.store.rank_evidence(
                self.descriptor.physical_index, self.descriptor.generation_id, community_id, vector, candidates,
            )
            items = self._ranked_items_from_rows(rows, community_id, k)
        else:
            items, candidates = self._ranked_items_from_full_generation(community_id, vector, k, candidates)
        return {
            "community_id": community_id, "level": community["level"],
            "ranked_by": "question", "dedupe": "source_id",
            "candidates_scored": candidates, "items": items,
        }

    def _ranked_items_from_rows(self, rows: list[dict[str, Any]], community_id: str, k: int) -> list[dict[str, Any]]:
        best: dict[str, dict[str, Any]] = {}
        for row in rows:
            if row.get("kind") != "evidence" or row.get("generation_id") != self.descriptor.generation_id or row.get("visibility") != "public":
                raise ContractError("SIDECAR_INTEGRITY_FAILED", "Ranked row identity mismatch")
            if community_id not in (row.get("community_ids") or []):
                raise ContractError("SIDECAR_INTEGRITY_FAILED", "Ranked row is outside the requested community")
            source, chunk = row.get("source_id"), row.get("chunk_id")
            score = row.get("score")
            if not isinstance(source, str) or not source or not isinstance(chunk, str) or not chunk:
                raise ContractError("SIDECAR_INTEGRITY_FAILED", "Ranked row lacks evidence identity")
            if not isinstance(score, (int, float)) or isinstance(score, bool) or not math.isfinite(score):
                raise ContractError("SIDECAR_INTEGRITY_FAILED", "Ranked row lacks a finite score")
            item = {"chunk_id": chunk, "source_id": source, "score": float(score)}
            if source not in best or (item["score"], item["chunk_id"]) > (best[source]["score"], best[source]["chunk_id"]):
                best[source] = item
        return sorted(best.values(), key=lambda item: (-item["score"], item["chunk_id"]))[:k]

    def _ranked_items_from_full_generation(
        self, community_id: str, vector: list[float], k: int, candidates: int,
    ) -> tuple[list[dict[str, Any]], int]:
        _payload, records = self._reader.load()
        member_chunks = {row["chunk_id"] for row in records["membership"] if row["community_id"] == community_id}
        rows: list[dict[str, Any]] = []
        for row in records["evidence"]:
            if row["chunk_id"] not in member_chunks:
                continue
            chunk_vector = row.get("chunk_vector")
            if not isinstance(chunk_vector, list) or len(chunk_vector) != self.descriptor.dimension:
                raise ContractError("SIDECAR_INTEGRITY_FAILED", "Evidence lacks a ranking vector")
            score = sum(float(a) * float(b) for a, b in zip(vector, chunk_vector))
            rows.append({**row, "score": score})
        rows.sort(key=lambda row: (-row["score"], row["chunk_id"]))
        limited = rows[:candidates]
        return self._ranked_items_from_rows(limited, community_id, k), len(limited)
