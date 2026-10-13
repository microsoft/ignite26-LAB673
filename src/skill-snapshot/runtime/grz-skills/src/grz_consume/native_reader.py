"""Reader for browsing communities directly from native GRZBuildPoc output artifacts.

Browses the coarse-first hierarchy, member keys, leaf centroids (.f32),
and receipt metrics produced by GRZBuildPoc.exe, optionally querying
a source-lookup provider for chunk texts and source identities.
Preserves partial coverage facts (assigned vs unassigned counts, node coverage).
"""

from __future__ import annotations

import base64
from typing import Any, Callable

import numpy as np

from grz_adapters.native_adapter import (
    NativeArtifacts,
    PartialCoverage,
    load_native_artifacts,
    native_artifacts_to_hierarchy,
)
from grz_build.centroids import Centroid
from grz_core.contracts import ContractError, Descriptor

from .checks import community_summary

MAX_PAGE_SIZE = 1000


def _encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        return int(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8"))
    except Exception as exc:
        raise ContractError("CURSOR_INVALID", "Invalid pagination cursor") from exc


class NativeConsumeReader:
    """Read-only browsing reader over native GRZBuildPoc build artifacts."""

    verification_scope = "native_hierarchy_and_receipt"

    def __init__(
        self,
        artifacts_or_dir: NativeArtifacts | str,
        descriptor: Descriptor,
        source_lookup: Callable[[str], dict[str, Any]] | None = None,
    ):
        if isinstance(artifacts_or_dir, NativeArtifacts):
            self.artifacts = artifacts_or_dir
        else:
            self.artifacts = load_native_artifacts(artifacts_or_dir, dimension=descriptor.dimension)

        self.descriptor = descriptor
        self.source_lookup = source_lookup
        self.coverage: PartialCoverage = self.artifacts.coverage

        # Convert to sidecar hierarchy: level 0 is finest leaf
        self.hierarchy, _ = native_artifacts_to_hierarchy(
            self.artifacts, descriptor.dimension
        )

        # Index communities by community_id
        self._by_id: dict[str, tuple[int, Centroid]] = {}
        # Parent to children mapping: parent_id -> list of child_ids
        self._children_by_parent: dict[str, list[str]] = {}
        # Chunk to community mapping: chunk_id -> list of community_ids
        self._communities_by_chunk: dict[str, list[str]] = {}

        for level, communities in enumerate(self.hierarchy):
            for cid, c in communities.items():
                self._by_id[cid] = (level, c)
                if c.parent:
                    self._children_by_parent.setdefault(c.parent, []).append(cid)
                for chunk in c.members:
                    self._communities_by_chunk.setdefault(chunk, []).append(cid)

    def manifest_payload(self) -> dict[str, Any]:
        """Synthesize manifest payload preserving partial coverage facts."""
        total_reps = sum(len(lvl) for lvl in self.hierarchy)
        total_memberships = sum(len(c.members) for lvl in self.hierarchy for c in lvl.values())
        return {
            "schema_version": self.descriptor.schema_version,
            "generation_id": self.descriptor.generation_id,
            "physical_index": self.descriptor.physical_index,
            "health": "verified",
            "counts": {
                "representative": total_reps,
                "membership": total_memberships,
                "evidence": self.coverage.assigned_node_count,
            },
            "source_document_count": self.coverage.source_document_count,
            "observed_node_count": self.coverage.observed_node_count,
            "assigned_node_count": self.coverage.assigned_node_count,
            "unassigned_source_document_count": self.coverage.unassigned_source_document_count,
            "node_coverage": self.coverage.node_coverage,
            "isolated_node_count": self.coverage.isolated_node_count,
            "label_stage": "post-clustering-enrichment",
            "labels_from_native_binary": False,
        }

    def level_counts(self) -> dict[int, int]:
        """Community counts per sidecar level (0 is finest leaf)."""
        return {level: len(communities) for level, communities in enumerate(self.hierarchy)}

    def representatives_at(self, level: int) -> tuple[list[dict[str, Any]], int]:
        """Representatives with centroids at level, plus total evidence count."""
        if level < 0 or level >= len(self.hierarchy):
            return [], self.coverage.assigned_node_count

        items = []
        for cid, c in sorted(self.hierarchy[level].items()):
            items.append({
                "community_id": cid,
                "level": level,
                "member_count": len(c.members),
                "parent_id": c.parent,
                "centroid": [float(x) for x in c.vector],
                "embedding_model_id": self.descriptor.embedding_model_id,
                "label": None,
                "label_status": "unnamed",
            })
        return items, self.coverage.assigned_node_count

    def list_communities(
        self, level: int | None = None, page_size: int = 100, cursor: str | None = None
    ) -> dict[str, Any]:
        """List communities, optionally filtered by level."""
        page_size = min(max(1, page_size), MAX_PAGE_SIZE)
        offset = _decode_cursor(cursor)

        all_items = []
        target_levels = [level] if level is not None else list(range(len(self.hierarchy)))
        for lvl in target_levels:
            if 0 <= lvl < len(self.hierarchy):
                for cid, c in sorted(self.hierarchy[lvl].items()):
                    all_items.append({
                        "community_id": cid,
                        "level": lvl,
                        "member_count": len(c.members),
                        "parent_id": c.parent,
                        "label": None,
                        "label_status": "unnamed",
                    })

        page = all_items[offset : offset + page_size]
        next_offset = offset + len(page)
        next_cursor = _encode_cursor(next_offset) if next_offset < len(all_items) else None
        return {"items": page, "next_cursor": next_cursor}

    def get_community(
        self,
        community_id: str,
        children_page_size: int = MAX_PAGE_SIZE,
        children_cursor: str | None = None,
    ) -> dict[str, Any]:
        """Retrieve single community summary with child IDs."""
        if community_id not in self._by_id:
            raise ContractError("COMMUNITY_NOT_FOUND", f"Community {community_id} not found")

        level, c = self._by_id[community_id]
        children = sorted(self._children_by_parent.get(community_id, []))
        ch_offset = _decode_cursor(children_cursor)
        ch_page = children[ch_offset : ch_offset + children_page_size]
        next_ch_offset = ch_offset + len(ch_page)
        next_ch_cursor = _encode_cursor(next_ch_offset) if next_ch_offset < len(children) else None

        row = {
            "community_id": community_id,
            "level": level,
            "member_count": len(c.members),
            "parent_id": c.parent,
            "centroid": [float(x) for x in c.vector],
            "embedding_model_id": self.descriptor.embedding_model_id,
            "label": None,
            "label_status": "unnamed",
        }
        res = community_summary(row, ch_page)
        res["children_next_cursor"] = next_ch_cursor
        return res

    def list_members(
        self, community_id: str, page_size: int = 100, cursor: str | None = None
    ) -> dict[str, Any]:
        """List member chunks belonging to community_id."""
        if community_id not in self._by_id:
            raise ContractError("COMMUNITY_NOT_FOUND", f"Community {community_id} not found")

        _, c = self._by_id[community_id]
        page_size = min(max(1, page_size), MAX_PAGE_SIZE)
        offset = _decode_cursor(cursor)

        members = sorted(c.members)
        chunk_ids = members[offset : offset + page_size]

        items = []
        for chk in chunk_ids:
            item = {"chunk_id": chk, "source_id": chk, "text": ""}
            if self.source_lookup:
                try:
                    info = self.source_lookup(chk)
                    item["source_id"] = info.get("source_id", chk)
                    item["text"] = info.get("text", "")
                except Exception:
                    pass
            items.append(item)

        next_offset = offset + len(chunk_ids)
        next_cursor = _encode_cursor(next_offset) if next_offset < len(members) else None
        return {"items": items, "next_cursor": next_cursor}

    def get_chunk(self, chunk_id: str) -> dict[str, Any]:
        """Look up chunk text, source reference, and community memberships."""
        if chunk_id not in self._communities_by_chunk and chunk_id not in self.artifacts.node_keys:
            raise ContractError("CHUNK_NOT_FOUND", f"Chunk {chunk_id} not found in native artifacts")

        item = {
            "chunk_id": chunk_id,
            "source_id": chunk_id,
            "text": "",
            "community_ids": sorted(self._communities_by_chunk.get(chunk_id, [])),
        }
        if self.source_lookup:
            try:
                info = self.source_lookup(chunk_id)
                item["source_id"] = info.get("source_id", chunk_id)
                item["text"] = info.get("text", "")
            except Exception:
                pass
        return item
