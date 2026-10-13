"""Plan IDs, storage estimates and approval text. Pure functions."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from . import SCHEMA_VERSION
from .errors import ApprovalError
from .normalize import to_document

PLAN_PREFIX = "pln-"
STORAGE_OVERHEAD = 2.0  # serialized JSON bytes -> rough index storage; an estimate, not a guarantee


def _digest(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_plan_id(content_hash: str, endpoint: str, index_name: str, graph_name: str = "") -> str:
    """hash(normalized edges, target service, index name, schema version)."""
    return PLAN_PREFIX + _digest({"kind": "build", "content": content_hash, "endpoint": endpoint.lower(),
                                  "index": index_name, "graph": graph_name,
                                  "schema_version": SCHEMA_VERSION})[:16]


def provision_plan_id(tenant: str, subscription: str, resource_group: str, service: str, location: str,
                      sku: str) -> str:
    return PLAN_PREFIX + _digest({"kind": "provision", "tenant": tenant.lower(), "subscription": subscription.lower(),
                                  "rg": resource_group.lower(), "service": service.lower(),
                                  "location": location.lower(), "sku": sku.lower()})[:16]


def estimate_storage_bytes(edges: list[dict[str, Any]]) -> int:
    total = 0
    for e in edges[:2000]:
        total += len(json.dumps(to_document(e), ensure_ascii=False))
    if len(edges) > 2000:
        total = int(total / 2000 * len(edges))
    return int(total * STORAGE_OVERHEAD)


def require_plan_id(supplied: str | None, expected: str) -> None:
    if not supplied:
        raise ApprovalError("PLAN_ID_REQUIRED", "apply needs the exact plan ID that was displayed and approved",
                            f"Re-run with --plan-id {expected} after the human approves.")
    if supplied != expected:
        raise ApprovalError("PLAN_ID_MISMATCH", f"--plan-id {supplied} does not equal the plan {expected}",
                            "Re-run plan and approve the plan ID it shows.")


def approval_card(plan_id: str, what: str, changes: list[str], cost: str, notices: list[str]) -> str:
    lines = [f"Proposed: {what}", f"Plan ID: {plan_id}", "Changes:"] + [f"  - {c}" for c in changes]
    lines.append(f"Cost and quota: {cost}")
    lines += [f"Notice: {n}" for n in notices]
    lines.append(f'Nothing is written until the exact plan ID is supplied. Reply "approved {plan_id}" to proceed.')
    return "\n".join(lines)
