"""Full readback validation of one generation index before it can be published."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

import numpy as np

from grz_consume.checks import documents_digest
from grz_core.contracts import (
    SIDECAR_VERSION, ContractError, SourceIdentity, community_id, document_id, require_public,
)

KINDS = ("representative", "membership", "evidence")


def _mismatch(detail: str) -> None:
    raise ContractError("READBACK_MISMATCH", detail)


def check_readback(documents: list[dict[str, Any]], generation: str, source: SourceIdentity) -> dict[str, int]:
    """Prove the index holds exactly one complete, nested, generation-scoped hierarchy; return kind counts."""
    groups = {kind: [d for d in documents if d["kind"] == kind] for kind in (*KINDS, "manifest")}
    _check_keys(documents, generation)
    if len(groups["manifest"]) != 1 or len(groups["evidence"]) != source.expected_count:
        _mismatch("Manifest or evidence cardinality differs")
    counts = _check_manifest(groups, documents, generation, source)
    evidence_ids = _check_evidence(groups["evidence"], generation, source)
    evidence_by_chunk = {d["chunk_id"]: d for d in groups["evidence"]}
    reps = {d["community_id"]: d for d in groups["representative"]}
    if len(reps) != len(groups["representative"]):
        _mismatch("Duplicate representative community")
    members_by_community, top_level = _check_membership(groups["membership"], reps, evidence_ids, generation)
    _check_evidence_membership(evidence_by_chunk, members_by_community, source)
    for id_, representative in reps.items():
        _check_representative(id_, representative, reps, members_by_community, top_level, generation, source)
    return counts


def _check_keys(documents: list[dict[str, Any]], generation: str) -> None:
    if any(d.get("generation_id") != generation for d in documents) or len({d["id"] for d in documents}) != len(documents):
        _mismatch("Generation or document keys differ")
    for doc in documents:
        require_public(doc.get("visibility"))
        if doc.get("sort_key") != doc.get("id"):
            _mismatch("Document sort key differs from immutable key")


def _check_manifest(groups: dict[str, list[dict[str, Any]]], documents: list[dict[str, Any]],
                    generation: str, source: SourceIdentity) -> dict[str, int]:
    payload = groups["manifest"][0]["payload"]
    if (payload["generation_id"] != generation or payload["schema_version"] != SIDECAR_VERSION
            or payload["source_service"] != source.service or payload["source_index"] != source.index
            or payload["embedding_model_id"] != source.embedding_model_id or payload["dimension"] != source.dimension
            or payload["health"] not in ("verified", "published")):
        _mismatch("Manifest/source identity differs")
    counts = {kind: len(groups[kind]) for kind in KINDS}
    if payload["counts"] != counts or payload["documents_digest"] != documents_digest([d for d in documents if d["kind"] != "manifest"]):
        _mismatch("Readback document digest or counts differ")
    return counts


def _check_evidence(evidence: list[dict[str, Any]], generation: str, source: SourceIdentity) -> list[str]:
    evidence_ids = [d["chunk_id"] for d in evidence]
    if len(set(evidence_ids)) != source.expected_count:
        _mismatch("Evidence must cover every distinct source chunk")
    for doc in evidence:
        if doc["id"] != document_id(generation, "evidence", doc["chunk_id"]):
            _mismatch("Evidence key is not generation scoped")
        vector = np.asarray(doc.get("chunk_vector"), dtype=np.float64)
        if len(vector) != source.dimension or not np.isfinite(vector).all() or not np.isclose(np.linalg.norm(vector), 1, atol=1e-5):
            _mismatch("Evidence vector dimension, magnitude or finiteness invalid")
    return evidence_ids


def _check_evidence_membership(evidence: dict[str, dict[str, Any]], members_by_community: dict[str, set[str]],
                               source: SourceIdentity) -> None:
    expected: dict[str, set[str]] = defaultdict(set)
    for cid, chunks in members_by_community.items():
        for chunk in chunks:
            expected[chunk].add(cid)
    for chunk, doc in evidence.items():
        ids = doc.get("community_ids")
        if not isinstance(ids, list) or set(ids) != expected[chunk] or ids != sorted(ids):
            _mismatch("Evidence community_ids differ from membership")


def _check_membership(membership: list[dict[str, Any]], reps: dict[str, dict[str, Any]],
                      evidence_ids: list[str], generation: str) -> tuple[dict[str, set[str]], int]:
    evidence_set = set(evidence_ids)
    by_level: dict[int, list[dict[str, Any]]] = defaultdict(list)
    members_by_community: dict[str, set[str]] = defaultdict(set)
    for member in membership:
        if member["chunk_id"] not in evidence_set or member["community_id"] not in reps:
            _mismatch("Member evidence or representative missing")
        if member["level"] != reps[member["community_id"]]["level"]:
            _mismatch("Member level differs from representative")
        by_level[member["level"]].append(member)
        members_by_community[member["community_id"]].add(member["chunk_id"])
    if not by_level or set(by_level) != set(range(max(by_level) + 1)):
        _mismatch("Missing hierarchy level")
    for level, members in by_level.items():
        if Counter(d["chunk_id"] for d in members) != Counter(evidence_ids):
            _mismatch(f"Membership coverage at level {level} differs")
    if any(d["id"] != document_id(generation, "membership", f"{d['community_id']}:{d['chunk_id']}")
           for d in membership):
        _mismatch("Membership key is not generation scoped")
    return members_by_community, max(by_level)


def _check_representative(id_: str, representative: dict[str, Any], reps: dict[str, dict[str, Any]],
                          members_by_community: dict[str, set[str]], top_level: int,
                          generation: str, source: SourceIdentity) -> None:
    members = members_by_community[id_]
    if id_ != community_id(generation, representative["level"], list(members)):
        _mismatch("Community identity differs from complete member set")
    if representative["id"] != document_id(generation, "representative", id_):
        _mismatch("Representative key is not generation scoped")
    if representative["member_count"] != len(members):
        _mismatch("Representative member count differs")
    vector = np.asarray(representative["centroid"], dtype=np.float64)
    if len(vector) != source.dimension or not np.isfinite(vector).all() or not np.isclose(np.linalg.norm(vector), 1, atol=1e-5):
        _mismatch("Centroid dimension, magnitude or finiteness invalid")
    parent = representative.get("parent_id")
    if parent:
        if parent not in reps or reps[parent]["level"] != representative["level"] + 1:
            _mismatch("Parent missing or wrong level")
        if not members.issubset(members_by_community[parent]):
            _mismatch("Community is not contained by parent")
    elif representative["level"] != top_level:
        _mismatch("Only coarsest communities may lack parents")
