"""Consume reader for Azure AI Search that uses only bounded, filtered queries.

A query-only consumer cannot rehash a whole generation with bounded requests,
so this reader trusts Build's published readback digest, rechecks live kind
counts against the manifest, and validates every row it returns.
"""

from __future__ import annotations

import re
from typing import Any

from grz_core.contracts import ContractError, Descriptor

from .checks import (
    KINDS, check_build_health, check_manifest_identity, community_summary, fail, has_evidence_text,
    is_valid_representative, member_summary,
)
from .paging import MAX_PAGE_SIZE, check_page_size, decode_cursor, encode_cursor, parallel_reads
from .search_store import AzureSearchReadStore

EVIDENCE_LOOKUP_BATCH = 32


class BoundedAzureReader:
    verification_scope = "build_attested_manifest_and_live_counts"

    def __init__(self, store: AzureSearchReadStore, descriptor: Descriptor):
        self.store = store
        self.descriptor = descriptor
        self._manifest_row: dict[str, Any] | None = None

    def manifest_payload(self) -> dict[str, Any]:
        desc = self.descriptor
        manifests = self.store.page(desc.physical_index, "manifest", desc.generation_id, 2)
        if len(manifests) != 1:
            fail("Exactly one generation manifest is required")
        row = manifests[0]
        self._check_identity("manifest", row)
        if self._manifest_row is not None and row != self._manifest_row:
            fail("Published manifest changed during browsing")
        payload = check_manifest_identity(row.get("payload"), desc)
        check_build_health(payload)
        self.store.bind_schema(desc.physical_index, desc.generation_id, desc.schema_version)
        if not isinstance(payload.get("documents_digest"), str) or not re.fullmatch(
            r"[0-9a-f]{64}", payload["documents_digest"]
        ):
            fail("Missing canonical Build readback digest")
        counts = payload.get("counts")
        if not isinstance(counts, dict) or any(
            type(counts.get(kind)) is not int or counts[kind] < 1
            or self.store.count(desc.physical_index, kind, desc.generation_id) != counts[kind]
            for kind in KINDS
        ):
            fail("Manifest kind counts are missing or differ from Search")
        self._manifest_row = row
        return payload

    def _check_identity(self, kind: str, row: dict[str, Any]) -> None:
        if not isinstance(row, dict) or row.get("kind") != kind or row.get("generation_id") != self.descriptor.generation_id:
            fail("Incorrect document kind or generation")
        if row.get("visibility") != "public":
            raise ContractError("VISIBILITY_UNSUPPORTED", "Restricted or unknown document visibility")
        if any(not isinstance(row.get(field), str) or not row[field] for field in ("id", "sort_key")):
            fail("Missing document ID or sort key")

    def _check_representative(self, row: dict[str, Any]) -> None:
        self._check_identity("representative", row)
        parent = row.get("parent_id")
        if not is_valid_representative(row, self.descriptor) or (
            parent is not None and (not isinstance(parent, str) or not parent)
        ):
            fail("Invalid representative")

    def _lookup(self, kind: str, field: str, value: str) -> dict[str, Any] | None:
        rows = self.store.lookup(self.descriptor.physical_index, kind, self.descriptor.generation_id, field, value)
        if len(rows) > 1:
            fail("Duplicate keyed document")
        if not rows:
            return None
        row = rows[0]
        self._check_identity(kind, row)
        if row.get(field) != value:
            fail("Search returned a mismatched lookup")
        return row

    def _context(self, operation: str, scope: Any) -> list[Any]:
        # Binding cursors to the readback digest invalidates them if the generation is ever replaced.
        return [
            self.descriptor.physical_index, self.descriptor.generation_id,
            self._manifest_row["payload"]["documents_digest"] if self._manifest_row else None,
            operation, scope,
        ]

    def _page(self, kind: str, size: int, cursor: str | None, context: list[Any], **filters: Any) -> dict[str, Any]:
        size = check_page_size(size)
        after = decode_cursor(cursor, context)
        desc = self.descriptor
        rows = self.store.page(desc.physical_index, kind, desc.generation_id,
                               min(size + 1, MAX_PAGE_SIZE), after=after, **filters)
        for row in rows:
            self._check_identity(kind, row)
            for key, value in filters.items():
                if value is not None and row.get(key) != value:
                    fail("Search returned a record outside the requested filter")
        has_more = len(rows) > size
        if len(rows) == size == MAX_PAGE_SIZE:
            # A full maximum page cannot fetch the extra lookahead row, so probe for one more.
            has_more = bool(self.store.page(desc.physical_index, kind, desc.generation_id, 1,
                                            after=rows[-1]["sort_key"], **filters))
        items = rows[:size]
        return {
            "items": items,
            "next_cursor": encode_cursor(items[-1]["sort_key"], context) if has_more and items else None,
        }

    def representatives_at(self, level: int) -> tuple[list[dict[str, Any]], int]:
        payload = self.manifest_payload()
        rows: list[dict[str, Any]] = []
        cursor: str | None = None
        context = self._context("representatives", level)
        while True:
            page = self._page("representative", MAX_PAGE_SIZE, cursor, context, level=level)
            for row in page["items"]:
                self._check_representative(row)
            rows.extend(page["items"])
            cursor = page["next_cursor"]
            if cursor is None:
                return rows, payload["counts"]["evidence"]

    def level_counts(self) -> dict[int, int]:
        payload = self.manifest_payload()
        desc = self.descriptor
        return {level: self.store.count(desc.physical_index, "representative", desc.generation_id, level=level)
                for level in range(int(payload.get("levels") or 0))}

    def list_communities(self, level: int | None, page_size: int, cursor: str | None) -> dict[str, Any]:
        self.manifest_payload()
        result = self._page("representative", page_size, cursor, self._context("community", level), level=level)
        result["items"] = parallel_reads(self._summary, result["items"])
        return result

    def _summary(self, row: dict[str, Any], children_page_size: int = MAX_PAGE_SIZE,
                 children_cursor: str | None = None) -> dict[str, Any]:
        self._check_representative(row)
        cid = row["community_id"]
        children = self._page("representative", children_page_size, children_cursor,
                              self._context("children", cid), parent_id=cid)
        for child in children["items"]:
            self._check_representative(child)
            if child["level"] != row["level"] - 1:
                fail("Child is not at the immediately finer level")
        result = community_summary(row, [child["community_id"] for child in children["items"]])
        result["children_next_cursor"] = children["next_cursor"]
        return result

    def get_community(self, community_id: str, children_page_size: int,
                      children_cursor: str | None) -> dict[str, Any]:
        self.manifest_payload()
        row = self._lookup("representative", "community_id", community_id)
        if row is None:
            raise ContractError("COMMUNITY_NOT_FOUND", community_id)
        return self._summary(row, children_page_size, children_cursor)

    def list_members(self, community_id: str, page_size: int, cursor: str | None) -> dict[str, Any]:
        self.manifest_payload()
        rep = self._lookup("representative", "community_id", community_id)
        if rep is None:
            raise ContractError("COMMUNITY_NOT_FOUND", community_id)
        self._check_representative(rep)
        desc = self.descriptor
        if self.store.count(desc.physical_index, "membership", desc.generation_id,
                            community_id=community_id) != rep["member_count"]:
            fail("Community membership count differs from representative")
        result = self._page("membership", page_size, cursor, self._context("member", community_id),
                            community_id=community_id)
        chunk_ids: set[str] = set()
        for row in result["items"]:
            chunk = row.get("chunk_id")
            if row.get("level") != rep["level"] or not isinstance(chunk, str) or not chunk or chunk in chunk_ids:
                fail("Invalid or duplicate community member")
            chunk_ids.add(chunk)
        evidence = self._evidence_for(chunk_ids)
        result["items"] = [member_summary(row, evidence[row["chunk_id"]]) for row in result["items"]]
        return result

    def _evidence_for(self, chunk_ids: set[str]) -> dict[str, dict[str, Any]]:
        desc = self.descriptor
        ordered = sorted(chunk_ids)
        groups = [ordered[start:start + EVIDENCE_LOOKUP_BATCH] for start in range(0, len(ordered), EVIDENCE_LOOKUP_BATCH)]
        fetched = parallel_reads(
            lambda group: list(self.store.evidence_for_chunks(desc.physical_index, desc.generation_id, group)),
            groups,
        )
        found: dict[str, dict[str, Any]] = {}
        for group, rows in zip(groups, fetched):
            for row in rows:
                self._check_identity("evidence", row)
                chunk = row.get("chunk_id")
                if chunk not in group or chunk in found or not has_evidence_text(row):
                    fail("Invalid or duplicate member evidence")
                found[chunk] = row
        if set(found) != chunk_ids:
            fail("Member references missing chunk evidence")
        return found

    def get_chunk(self, chunk_id: str) -> dict[str, Any]:
        self.manifest_payload()
        row = self._lookup("evidence", "chunk_id", chunk_id)
        if row is None:
            raise ContractError("CHUNK_NOT_FOUND", chunk_id)
        if not has_evidence_text(row):
            fail("Invalid chunk evidence")
        self._check_chunk_membership(chunk_id)
        return {"chunk_id": chunk_id, "source_id": row["source_id"], "text": row["text"]}

    def _check_chunk_membership(self, chunk_id: str) -> None:
        """Evidence alone is not enough: the chunk must belong to a valid community in this generation."""
        desc = self.descriptor
        memberships = self.store.page(desc.physical_index, "membership", desc.generation_id, 1, chunk_id=chunk_id)
        if not memberships:
            fail("Chunk evidence has no evidenced membership")
        member = memberships[0]
        self._check_identity("membership", member)
        if (member.get("chunk_id") != chunk_id
                or not isinstance(member.get("community_id"), str) or not member["community_id"]):
            fail("Chunk membership lookup mismatch")
        rep = self._lookup("representative", "community_id", member.get("community_id"))
        if rep is None or member.get("level") != rep.get("level"):
            fail("Chunk membership has no valid community")
        self._check_representative(rep)
