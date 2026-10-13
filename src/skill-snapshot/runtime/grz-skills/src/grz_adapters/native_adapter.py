"""Orchestration adapter around the GRZBuildPoc native binary.

Replaces the simulated Python clustering path (graspologic-native / FAISS)
with the native CLI binary, ingesting `grz-cli-v1` artifacts:
  - `node-keys.json`: chunk / document keys by node index
  - `hierarchy.json`: coarse-first community assignments (level 0 coarsest)
  - `representatives.json` + `representatives.f32`: leaf centroid metadata & vectors
  - `receipt.json`: run metrics and partial coverage statistics
  - `progress.json`: phase progress tracking

Converts the coarse-first native hierarchy into the sidecar hierarchy convention
(level 0 finest/leaf, parent at level + 1), preserves partial coverage facts
(assigned vs unassigned counts), and guarantees that unassigned chunks are not labeled.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from grz_build.centroids import Centroid
from grz_core.contracts import ContractError, digest

from .native_runner import NativeCliResult, NativeRunner, validate_native_config

Hierarchy = list[dict[str, Centroid]]


@dataclass(frozen=True)
class PartialCoverage:
    """Explicit metrics capturing assigned vs unassigned chunks from clustering."""

    source_document_count: int
    observed_node_count: int
    assigned_node_count: int
    unassigned_source_document_count: int
    node_coverage: float
    isolated_node_count: int = 0
    hierarchy_depth: int = 0
    representative_count: int = 0

    @classmethod
    def from_receipt(cls, receipt: dict[str, Any]) -> PartialCoverage:
        src_count = int(receipt.get("SourceDocumentCount", 0))
        obs_count = int(receipt.get("ObservedNodeCount", 0))
        assigned = int(receipt.get("AssignedNodeCount", 0))
        unassigned = int(receipt.get("UnassignedSourceDocumentCount", max(0, src_count - assigned)))
        coverage = float(receipt.get("NodeCoverage", (assigned / src_count) if src_count > 0 else 0.0))
        isolated = int(receipt.get("IsolatedNodeCount", 0))
        depth = int(receipt.get("HierarchyDepth", 0))
        rep_count = int(receipt.get("RepresentativeCount", 0))
        return cls(
            source_document_count=src_count,
            observed_node_count=obs_count,
            assigned_node_count=assigned,
            unassigned_source_document_count=unassigned,
            node_coverage=coverage,
            isolated_node_count=isolated,
            hierarchy_depth=depth,
            representative_count=rep_count,
        )


@dataclass
class NativeArtifacts:
    """Artifacts loaded from the output directory of GRZBuildPoc.exe execute."""

    node_keys: list[str]
    hierarchy_records: list[dict[str, Any]]
    representative_records: list[dict[str, Any]]
    representative_vectors: np.ndarray  # float32 shape (num_reps, dimension)
    receipt: dict[str, Any]
    progress: dict[str, Any] | None = None
    support_log_path: Path | None = None
    coverage: PartialCoverage = field(init=False)

    def __post_init__(self) -> None:
        self.coverage = PartialCoverage.from_receipt(self.receipt)


def load_native_artifacts(
    output_dir: Path, dimension: int | None = None
) -> NativeArtifacts:
    """Load and validate output artifacts produced by GRZBuildPoc.exe execute."""
    output_dir = Path(output_dir)
    if not output_dir.is_dir():
        raise ContractError(
            "NATIVE_ARTIFACTS_MISSING",
            f"Native output directory does not exist: {output_dir}",
        )

    receipt_file = output_dir / "receipt.json"
    if not receipt_file.is_file():
        raise ContractError(
            "NATIVE_ARTIFACTS_MISSING",
            f"Missing required native artifact receipt.json in {output_dir}",
        )
    with open(receipt_file, "r", encoding="utf-8") as f:
        receipt = json.load(f)

    node_keys_file = output_dir / "node-keys.json"
    if not node_keys_file.is_file():
        raise ContractError(
            "NATIVE_ARTIFACTS_MISSING",
            f"Missing required native artifact node-keys.json in {output_dir}",
        )
    with open(node_keys_file, "r", encoding="utf-8") as f:
        node_keys = json.load(f)
    if not isinstance(node_keys, list):
        raise ContractError("NATIVE_ARTIFACTS_INVALID", "node-keys.json must be a JSON array")

    hierarchy_file = output_dir / "hierarchy.json"
    if not hierarchy_file.is_file():
        raise ContractError(
            "NATIVE_ARTIFACTS_MISSING",
            f"Missing required native artifact hierarchy.json in {output_dir}",
        )
    with open(hierarchy_file, "r", encoding="utf-8") as f:
        hierarchy_records = json.load(f)
    if not isinstance(hierarchy_records, list):
        raise ContractError("NATIVE_ARTIFACTS_INVALID", "hierarchy.json must be a JSON array")

    reps_file = output_dir / "representatives.json"
    if not reps_file.is_file():
        raise ContractError(
            "NATIVE_ARTIFACTS_MISSING",
            f"Missing required native artifact representatives.json in {output_dir}",
        )
    with open(reps_file, "r", encoding="utf-8") as f:
        representative_records = json.load(f)
    if not isinstance(representative_records, list):
        raise ContractError("NATIVE_ARTIFACTS_INVALID", "representatives.json must be a JSON array")

    f32_file = output_dir / "representatives.f32"
    if not f32_file.is_file():
        raise ContractError(
            "NATIVE_ARTIFACTS_MISSING",
            f"Missing required native artifact representatives.f32 in {output_dir}",
        )

    num_reps = len(representative_records)
    raw_bytes = f32_file.read_bytes()
    expected_dim = dimension
    if expected_dim is None:
        if num_reps > 0 and len(raw_bytes) % (num_reps * 4) == 0:
            expected_dim = len(raw_bytes) // (num_reps * 4)
        else:
            expected_dim = 1536  # default text-embedding-3-large dimension

    expected_bytes = num_reps * expected_dim * 4
    if len(raw_bytes) != expected_bytes and num_reps > 0:
        raise ContractError(
            "NATIVE_ARTIFACTS_INVALID",
            f"representatives.f32 byte length {len(raw_bytes)} does not match {num_reps} x {expected_dim} floats ({expected_bytes} bytes)",
        )

    if num_reps > 0:
        vectors = np.frombuffer(raw_bytes, dtype=np.float32).reshape(num_reps, expected_dim)
    else:
        vectors = np.empty((0, expected_dim or 0), dtype=np.float32)

    progress_file = output_dir / "progress.json"
    progress = None
    if progress_file.is_file():
        try:
            with open(progress_file, "r", encoding="utf-8") as f:
                progress = json.load(f)
        except Exception:
            pass

    logs = sorted(output_dir.glob("grz-operation-*.log"))
    support_log = logs[-1] if logs else None

    return NativeArtifacts(
        node_keys=node_keys,
        hierarchy_records=hierarchy_records,
        representative_records=representative_records,
        representative_vectors=vectors,
        receipt=receipt,
        progress=progress,
        support_log_path=support_log,
    )


def native_artifacts_to_hierarchy(
    artifacts: NativeArtifacts, dimension: int
) -> tuple[Hierarchy, PartialCoverage]:
    """Convert native coarse-first hierarchy into sidecar Hierarchy (level 0 finest).

    Native hierarchy records:
      - `node`: 0-based integer index into `artifacts.node_keys`
      - `level`: 0 is coarsest (root level), depth is finest (leaf level)
      - `communityId`: cluster identifier
      - `parentCommunityId`: parent cluster identifier at level - 1 (null at level 0)

    Sidecar hierarchy:
      - `level 0` is finest leaf level
      - `parent` points to community at `level + 1`
      - `Centroid` with normalized unit vector and members list
    """
    node_keys = artifacts.node_keys
    records = artifacts.hierarchy_records

    if not records:
        return [], artifacts.coverage

    # Map native level to records
    def _lvl(r: dict[str, Any]) -> int:
        return int(r["Level"] if "Level" in r else r["level"])

    def _cid(r: dict[str, Any]) -> str:
        return str(r["CommunityId"] if "CommunityId" in r else r["communityId"])

    def _node(r: dict[str, Any]) -> int:
        return int(r["Node"] if "Node" in r else r["node"])

    def _parent_cid(r: dict[str, Any]) -> str | None:
        val = r.get("ParentCommunityId") if "ParentCommunityId" in r else r.get("parentCommunityId")
        return str(val) if val is not None else None

    native_levels = sorted({_lvl(r) for r in records})
    native_depth = max(native_levels) if native_levels else 0

    # Build representative lookup: communityId -> centroid vector
    rep_vectors: dict[str, np.ndarray] = {}
    for idx, rep in enumerate(artifacts.representative_records):
        cid = str(rep["CommunityId"] if "CommunityId" in rep else rep.get("communityId", ""))
        if cid and idx < len(artifacts.representative_vectors):
            rep_vectors[cid] = artifacts.representative_vectors[idx]

    # Group by native level: native_level -> communityId -> list of node indices
    # Also track parent pointers: native_level -> communityId -> parentCommunityId
    community_members: dict[int, dict[str, list[int]]] = {}
    parent_map: dict[int, dict[str, str | None]] = {}

    for r in records:
        n_lvl = _lvl(r)
        cid = _cid(r)
        node_idx = _node(r)
        parent_cid = _parent_cid(r)

        community_members.setdefault(n_lvl, {}).setdefault(cid, []).append(node_idx)
        parent_map.setdefault(n_lvl, {})[cid] = parent_cid

    # Convert to sidecar levels: sidecar_level = native_depth - native_level
    # level 0 in sidecar is finest (native_depth)
    sidecar_levels = native_depth + 1
    hierarchy: Hierarchy = [{} for _ in range(sidecar_levels)]

    for native_lvl in range(native_depth + 1):
        sidecar_lvl = native_depth - native_lvl
        communities = community_members.get(native_lvl, {})
        parents = parent_map.get(native_lvl, {})

        for cid, nodes in communities.items():
            members = tuple(sorted(node_keys[n] for n in set(nodes) if n < len(node_keys)))
            parent_cid = parents.get(cid)

            # Determine centroid: use representative vector if available, or compute mean
            if cid in rep_vectors:
                vec = rep_vectors[cid].copy()
                norm = np.linalg.norm(vec)
                if norm > 0:
                    vec = vec / norm
            else:
                # Placeholder unit vector if not present in representatives
                vec = np.zeros(dimension, dtype=np.float32)
                vec[0] = 1.0

            hierarchy[sidecar_lvl][cid] = Centroid(
                level=sidecar_lvl,
                community_id=cid,
                members=members,
                parent=parent_cid,
                vector=vec,
            )

    return hierarchy, artifacts.coverage


def build_native_config(
    *,
    endpoint: str,
    source_index: str,
    vector_field: str,
    output_directory: str | Path,
    auth_mode: str = "defaultAzureCredential",
    tenant_id: str | None = None,
    api_key_env_var: str = "AZURE_SEARCH_API_KEY",
    read_only: bool = True,
    sample_percent: int = 5,
    max_leaf_size: int = 100,
    concurrency: int = 8,
    extra_execution_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Construct a validated configuration dictionary for GRZBuildPoc.exe."""
    config: dict[str, Any] = {
        "search": {
            "endpoint": endpoint,
            "apiVersion": "2025-09-01",
            "sourceIndex": source_index,
            "vectorField": vector_field,
        },
        "authentication": {
            "mode": auth_mode,
        },
        "credentials": {
            "searchApiKeyEnvironmentVariable": api_key_env_var,
        },
        "execution": {
            "samplePercent": sample_percent,
            "maxLeafSize": max_leaf_size,
            "concurrency": concurrency,
            "readOnly": read_only,
            **(extra_execution_options or {}),
        },
        "outputDirectory": str(output_directory),
    }

    if tenant_id and auth_mode == "defaultAzureCredential":
        config["authentication"]["tenantId"] = tenant_id

    validate_native_config(config)
    return config


class NativeBuildAdapter:
    """Adapter orchestrating GRZBuildPoc CLI execution and output artifact conversion."""

    def __init__(
        self,
        runner: NativeRunner | None = None,
        scratch_root: Path | None = None,
    ):
        self.runner = runner or NativeRunner()
        self.scratch_root = Path(scratch_root) if scratch_root else Path(".grz-native-scratch")

    def build_from_config(
        self, config: dict[str, Any] | Path, dimension: int, timeout: float = 600.0
    ) -> tuple[Hierarchy, PartialCoverage, NativeCliResult]:
        """Run execute command with config and return hierarchy and coverage."""
        if isinstance(config, dict):
            self.scratch_root.mkdir(parents=True, exist_ok=True)
            cfg_path = self.scratch_root / "config.json"
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
            out_dir = Path(config["outputDirectory"])
        else:
            cfg_path = Path(config)
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg_data = json.load(f)
            out_dir = Path(cfg_data["outputDirectory"])
            if not out_dir.is_absolute():
                out_dir = cfg_path.parent / out_dir

        out_dir.mkdir(parents=True, exist_ok=True)
        result = self.runner.execute(cfg_path, yes=True, timeout=timeout)

        if not result.succeeded:
            raise ContractError(
                result.error_code or "NATIVE_EXECUTION_FAILED",
                f"GRZBuildPoc execution failed: {result.error or result.stderr}",
            )

        artifacts = load_native_artifacts(out_dir, dimension=dimension)
        artifacts.support_log_path = result.support_log_path or artifacts.support_log_path
        hierarchy, coverage = native_artifacts_to_hierarchy(artifacts, dimension)
        return hierarchy, coverage, result
