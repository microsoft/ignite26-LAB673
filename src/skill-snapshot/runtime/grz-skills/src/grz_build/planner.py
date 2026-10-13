"""Read-only plan, budget and immutable pre-export approval identity."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from grz_core.contracts import ALGORITHM_REVISION, PINNED_DEPENDENCIES, BuildProfile, ContractError, SourceIdentity, digest
from grz_build.naming import NamingBudget

# Upload bytes are canonical JSON, where a float32 component costs up to 24 bytes, not 4.
VECTOR_JSON_BYTES_PER_DIM = 24
EVIDENCE_TEXT_ALLOWANCE = 4096
DOCUMENT_FIELDS_ALLOWANCE = 1024
MEMBERSHIP_BYTES = 512
MEMBERSHIP_LEVELS = 4
CHUNKS_PER_REPRESENTATIVE = 4


def estimate_upload_bytes(chunks: int, dimension: int) -> int:
    """Conservative v2 upload bytes: evidence with chunk_vector, membership per level, representatives with centroid."""
    vector = dimension * VECTOR_JSON_BYTES_PER_DIM
    evidence = chunks * (vector + EVIDENCE_TEXT_ALLOWANCE + DOCUMENT_FIELDS_ALLOWANCE)
    membership = chunks * MEMBERSHIP_LEVELS * MEMBERSHIP_BYTES
    representatives = -(-chunks // CHUNKS_PER_REPRESENTATIVE) * (vector + DOCUMENT_FIELDS_ALLOWANCE)
    return evidence + membership + representatives


def plan(source: SourceIdentity, profile: BuildProfile, *, target_service: str,
         alias: str = "grz-active", inspected: dict[str, Any] | None = None,
         naming_budget: NamingBudget | None = None, naming_model: dict[str, Any] | None = None) -> dict[str, Any]:
    source.validate()
    profile.validate()
    if naming_budget is not None:
        naming_budget.validate()
    if naming_model is not None and naming_budget is None:
        raise ContractError("NAMING_BUDGET_REQUIRED", "A naming model needs a complete naming budget")
    if target_service != source.service:
        raise ContractError("PLACEMENT_UNSUPPORTED", "Cross-service placement requires product validation")
    n = source.expected_count
    estimate = estimate_upload_bytes(n, source.dimension)
    action = {
        "source": asdict(source),
        "source_inspection_digest": digest(inspected if inspected is not None else asdict(source)),
        "profile": asdict(profile),
        "algorithm_revision": ALGORITHM_REVISION,
        "pinned_dependencies": PINNED_DEPENDENCIES,
        "target_service": target_service,
        "alias": alias,
        "estimated_bytes": estimate,
        "estimated_documents": n * (1 + MEMBERSHIP_LEVELS) + -(-n // CHUNKS_PER_REPRESENTATIVE) + 1,
        "index_writes": ["create generation index", "upload representative/membership/evidence/manifest"],
        "publish_write": "switch serving alias only after readback verification",
        "model_calls": naming_budget.max_calls if naming_budget else 0,
        "naming_budget": asdict(naming_budget) if naming_budget else None,
        "security_mode": "public-only",
    }
    if naming_model is not None:
        action["naming_model"] = naming_model
    return {"plan_id": digest(action), **action}


def approve_plan(planned: dict[str, Any], plan_id: str, approved_budget_bytes: int) -> None:
    if planned["plan_id"] != plan_id or digest({k: v for k, v in planned.items() if k != "plan_id"}) != plan_id:
        raise ContractError("PLAN_CHANGED", "Approval must match exact immutable plan")
    if approved_budget_bytes < planned["estimated_bytes"]:
        raise ContractError("BUDGET_APPROVAL_REQUIRED",
                            f"Approve an explicit byte budget of at least {planned['estimated_bytes']}, the plan's estimate")
