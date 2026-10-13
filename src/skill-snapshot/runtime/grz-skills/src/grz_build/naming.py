"""Optional, bounded provider-injected naming; no provider configured by default."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from grz_core.contracts import ContractError


LABEL_STAGE = "post-clustering-enrichment"
DEFAULT_LABEL_PRODUCER = "grz-skills-naming-azure"


@dataclass(frozen=True)
class NamingBudget:
    max_calls: int
    max_tokens: int
    max_spend: float
    timeout_seconds: float

    def validate(self) -> None:
        if min(self.max_calls, self.max_tokens) < 1 or min(self.max_spend, self.timeout_seconds) <= 0:
            raise ContractError("NAMING_BUDGET_REQUIRED", "Calls, tokens, spend and timeout must all be positive")


@dataclass(frozen=True)
class NamingResult:
    label: str | None
    tokens: int
    spend: float


def name_communities(ids: list[str], provider: Callable[[str, float], NamingResult] | None,
                     budget: NamingBudget | None, *, approved: bool = False,
                     contexts: dict[str, str] | None = None, reserve_tokens: int = 0,
                     reserve_spend: float = 0.0,
                     label_producer: str = DEFAULT_LABEL_PRODUCER) -> dict[str, dict[str, Any]]:
    """Name ids in the order given. The provider gets each id's context, or the id itself.

    A call is skipped, leaving the community unnamed, once the remaining budget can't cover
    the reserve for one more call, so one response can't push usage past the budget.
    Explicitly records label provenance indicating that labels are produced by this
    post-clustering enrichment stage, not by the native binary.
    """
    if provider is None:
        return {
            id_: {
                "label": None,
                "label_status": "unnamed",
                "label_stage": LABEL_STAGE,
                "label_producer": None,
                "labels_from_native_binary": False,
            }
            for id_ in ids
        }
    if not approved or budget is None:
        raise ContractError("MODEL_APPROVAL_REQUIRED", "Explicit naming provider, complete budget and approval required")
    budget.validate()
    remaining_tokens, remaining_spend = budget.max_tokens, budget.max_spend
    output = {}
    for index, id_ in enumerate(ids):
        if (index >= budget.max_calls or remaining_tokens <= 0 or remaining_spend <= 0
                or remaining_tokens < reserve_tokens or remaining_spend < reserve_spend):
            output[id_] = {
                "label": None,
                "label_status": "unnamed",
                "label_stage": LABEL_STAGE,
                "label_producer": None,
                "labels_from_native_binary": False,
            }
            continue
        try:
            result = provider(contexts[id_] if contexts is not None else id_, budget.timeout_seconds)
            if result.tokens < 0 or result.spend < 0 or result.tokens > remaining_tokens or result.spend > remaining_spend:
                raise ContractError("NAMING_BUDGET_EXCEEDED", "Provider exceeded approved usage; stop calls")
            remaining_tokens -= result.tokens
            remaining_spend -= result.spend
            output[id_] = {
                "label": result.label if result.label else None,
                "label_status": "named" if result.label else "failed",
                "label_stage": LABEL_STAGE,
                "label_producer": label_producer if result.label else None,
                "labels_from_native_binary": False,
            }
        except ContractError:
            raise
        except (TimeoutError, ConnectionError):
            output[id_] = {
                "label": None,
                "label_status": "failed",
                "label_stage": LABEL_STAGE,
                "label_producer": None,
                "labels_from_native_binary": False,
            }
    return output


def enrich_assigned_communities(
    local_keys: list[str],
    provider: Callable[[str, float], NamingResult] | None,
    budget: NamingBudget | None,
    *,
    approved: bool = False,
    contexts: dict[str, str] | None = None,
    reserve_tokens: int = 0,
    reserve_spend: float = 0.0,
    label_producer: str = DEFAULT_LABEL_PRODUCER,
    unassigned_chunks: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Explicit post-clustering enrichment stage for naming assigned communities.

    Guarantees:
    1. Only assigned community keys in `local_keys` are passed for naming.
    2. Unassigned chunks are never labeled.
    3. Explicitly records that labels are produced by this stage, not by the native binary.
    """
    if unassigned_chunks:
        # Verify that no unassigned chunk key appears in local_keys
        for key in local_keys:
            if key in unassigned_chunks:
                raise ContractError("UNASSIGNED_CHUNK_LABELED", f"Cannot label unassigned chunk: {key}")

    return name_communities(
        local_keys,
        provider,
        budget,
        approved=approved,
        contexts=contexts,
        reserve_tokens=reserve_tokens,
        reserve_spend=reserve_spend,
        label_producer=label_producer,
    )
