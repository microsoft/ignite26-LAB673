"""Assemble the immutable sidecar documents and generation identity for one build."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import asdict
from typing import Any

from grz_build.centroids import Centroid
from grz_build.inputs import Snapshot
from grz_consume.checks import documents_digest
from grz_core.contracts import (
    ALGORITHM_REVISION, PINNED_DEPENDENCIES, SIDECAR_VERSION, BuildProfile, ContractError,
    SourceIdentity, canonical_json, community_id, digest, document_id,
)

Hierarchy = list[dict[str, Centroid]]


def sidecar_record(generation: str, kind: str, key: str, **fields: Any) -> dict[str, Any]:
    id_ = document_id(generation, kind, key)
    return {"id": id_, "sort_key": id_, "kind": kind, "generation_id": generation,
            "visibility": "public", **fields}


def staging_bytes_estimate(snapshot: Snapshot, centroids: Hierarchy, dimension: int) -> int:
    link_count = sum(len(c.members) for communities in centroids for c in communities.values())
    community_id_bytes = link_count * 80
    return (
        sum(len(canonical_json(row).encode("utf-8")) for row in snapshot.rows)
        + snapshot.vectors.nbytes + link_count * 320 + community_id_bytes
        + sum(len(communities) for communities in centroids) * (dimension * 4 + 512)
    )


def hierarchy_digest(centroids: Hierarchy) -> str:
    return digest([{
        "level": level, "communities": [
            {"members": sorted(c.members), "parent": c.parent,
             "centroid": [float(x) for x in c.vector]}
            for c in sorted(by_id.values(), key=lambda item: item.community_id)]
    } for level, by_id in enumerate(centroids)])


def generation_id(snapshot: Snapshot, profile: BuildProfile, hierarchy: str, labels: dict[str, Any]) -> str:
    """Same input, algorithm, pinned dependencies, config and labels always give the same generation."""
    return digest({
        "schema_version": SIDECAR_VERSION, "snapshot_digest": snapshot.digest, "algorithm_revision": ALGORITHM_REVISION,
        "pinned_dependency_versions": PINNED_DEPENDENCIES, "effective_graph_config": asdict(profile),
        "hierarchy_centroid_digest": hierarchy, "label_output_digest": digest(labels),
    })


def community_documents(generation: str, centroids: Hierarchy, labels: dict[str, Any],
                        snapshot: Snapshot, source: SourceIdentity) -> list[dict[str, Any]]:
    return list(iter_community_documents(generation, centroids, labels, snapshot, source))


def documents_bytes(documents: Iterable[dict[str, Any]]) -> int:
    """Upload bytes as apply's budget check counts them: canonical JSON, UTF-8."""
    return sum(len(canonical_json(doc).encode("utf-8")) for doc in documents)


def provisional_documents_bytes(centroids: Hierarchy, snapshot: Snapshot, source: SourceIdentity,
                                label_chars: int) -> int:
    """Upper bound on upload bytes before naming: every label at its longest, 4 UTF-8 bytes per character."""
    keys = [f"{level}:{local}" for level, communities in enumerate(centroids) for local in communities]
    labels = {key: {"label": "x" * (4 * label_chars), "label_status": "unnamed"} for key in keys}
    return documents_bytes(iter_community_documents("0" * 64, centroids, labels, snapshot, source))


def iter_community_documents(generation: str, centroids: Hierarchy, labels: dict[str, Any],
                             snapshot: Snapshot, source: SourceIdentity) -> Iterator[dict[str, Any]]:
    """Representative and membership docs per community, then one evidence doc per chunk."""
    local_ids = {(level, local): community_id(generation, level, list(c.members))
                 for level, communities in enumerate(centroids) for local, c in communities.items()}
    if len(set(local_ids.values())) != len(local_ids):
        raise ContractError("COMMUNITY_ID_COLLISION", "Community ID digest collision")
    for level, communities in enumerate(centroids):
        for local, c in sorted(communities.items()):
            id_ = local_ids[level, local]
            parent = local_ids[level + 1, c.parent] if c.parent is not None else None
            label = labels[f"{level}:{local}"]
            yield sidecar_record(
                generation, "representative", id_, community_id=id_,
                parent_id=parent, level=level, member_count=len(c.members),
                centroid=[float(x) for x in c.vector], embedding_model_id=source.embedding_model_id,
                label=label["label"], label_status=label["label_status"],
                centroid_method="normalized-mean-of-unit-members")
            for chunk in sorted(c.members):
                yield sidecar_record(generation, "membership", f"{id_}:{chunk}",
                                     community_id=id_, level=level, chunk_id=chunk)
    communities_by_chunk: dict[str, list[str]] = {row["chunk_id"]: [] for row in snapshot.rows}
    for (_level, _local), id_ in local_ids.items():
        for chunk in centroids[_level][_local].members:
            communities_by_chunk[chunk].append(id_)
    for row, vector in zip(snapshot.rows, snapshot.vectors, strict=True):
        chunk = row["chunk_id"]
        yield sidecar_record(generation, "evidence", chunk,
                             chunk_id=chunk, source_id=row["source"], text=row["text"],
                             chunk_vector=[float(x) for x in vector],
                             community_ids=sorted(communities_by_chunk[chunk]))


def manifest_payload(*, generation: str, index: str, source: SourceIdentity, documents: list[dict[str, Any]],
                     snapshot: Snapshot, hierarchy: str, labels: dict[str, Any], graph_edges: int,
                     levels: int, staging_bytes: int, visibility_basis: str = "per-document",
                     partial_coverage: dict[str, Any] | None = None) -> dict[str, Any]:
    counts = Counter(d["kind"] for d in documents)
    payload = {
        "schema_version": SIDECAR_VERSION, "generation_id": generation,
        "physical_index": index, "source_service": source.service, "source_index": source.index,
        "embedding_model_id": source.embedding_model_id, "dimension": source.dimension,
        "visibility": "public", "source_visibility": "public", "acl_mode": "public-only",
        "visibility_basis": visibility_basis,
        "health": "verified", "counts": {k: counts[k] for k in ("representative", "membership", "evidence")},
        "documents_digest": documents_digest(documents), "snapshot_digest": snapshot.digest,
        "hierarchy_centroid_digest": hierarchy, "label_output_digest": digest(labels),
        "algorithm_revision": ALGORITHM_REVISION,
        "pinned_dependencies": PINNED_DEPENDENCIES, "graph_edges": graph_edges,
        "levels": levels, "normalization": "case-sensitive-utf8-v1",
        "member_ranking": "chunk-vector-v1",
        "estimated_staging_bytes": staging_bytes,
        "label_stage": "post-clustering-enrichment",
        "labels_from_native_binary": False,
    }
    if partial_coverage:
        payload["partial_coverage"] = partial_coverage
        for key in ("source_document_count", "observed_node_count", "assigned_node_count",
                    "unassigned_source_document_count", "node_coverage", "isolated_node_count"):
            if key in partial_coverage:
                payload[key] = partial_coverage[key]
    return payload
