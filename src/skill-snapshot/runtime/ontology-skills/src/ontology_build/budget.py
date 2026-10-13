"""Spend reservation and ledger. Pure functions; no I/O except reading journal entries."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from ontology_core.errors import Blocked

CHARS_PER_TOKEN = 3
OVERHEAD_TOKENS = 200


@dataclass(frozen=True)
class Prices:
    input_per_1m: float
    output_per_1m: float


@dataclass(frozen=True)
class Reservation:
    call: str
    """`shard-<k>` or `audit`."""
    reserve_tokens: int
    reserve_usd: float


def reserve(call: str, *, input_chars: int, max_output_tokens: int, prices: Prices) -> Reservation:
    """`reserve_tokens = ceil(input_chars / 3) + 200 + max_output_tokens`;
    `reserve_usd = reserve_tokens * max(in, out) / 1e6`."""
    tokens = math.ceil(input_chars / CHARS_PER_TOKEN) + OVERHEAD_TOKENS + max_output_tokens
    usd = tokens * max(prices.input_per_1m, prices.output_per_1m) / 1e6
    return Reservation(call=call, reserve_tokens=tokens, reserve_usd=usd)


def actual_usd(prompt_tokens: int, completion_tokens: int, prices: Prices) -> float:
    """`(prompt * in + completion * out) / 1e6`."""
    return (prompt_tokens * prices.input_per_1m + completion_tokens * prices.output_per_1m) / 1e6


@dataclass
class Ledger:
    plan_id: str
    spent_usd: float = 0.0
    spent_tokens: int = 0
    completed: frozenset[str] = frozenset()
    unknown: frozenset[str] = frozenset()

    @classmethod
    def from_journal(cls, entries: list[dict[str, Any]], plan_id: str) -> Ledger:
        """`spent = sum(call_completed.usd) + sum(call_unknown.reserve_usd)` for `plan_id`; a completed call
        that was earlier unknown counts once, at its actual cost."""
        charged: list[tuple[float, int]] = []
        completed: set[str] = set()
        unknown: dict[str, tuple[float, int]] = {}
        requested_tokens: dict[str, int] = {}
        for entry in entries:
            if entry.get("plan_id") != plan_id:
                continue
            event, call = entry["event"], entry.get("call")
            if event == "call_requested":
                requested_tokens[call] = entry["reserve_tokens"]
            elif event == "call_completed":
                prompt, completion = entry["prompt_tokens"], entry["completion_tokens"]
                tokens = requested_tokens.get(call, 0) if prompt is None or completion is None else prompt + completion
                charged.append((entry["usd"], tokens))
                completed.add(call)
                unknown.pop(call, None)
            elif event == "call_unknown":
                unknown[call] = (entry["reserve_usd"], requested_tokens.get(call, 0))
        charged.extend(unknown.values())
        return cls(plan_id=plan_id, spent_usd=sum(usd for usd, _ in charged),
                   spent_tokens=sum(tokens for _, tokens in charged),
                   completed=frozenset(completed), unknown=frozenset(unknown))

    def check(self, reservation: Reservation, *, approved_budget_usd: float, max_tokens: int | None) -> None:
        """Raises:
            Blocked("BUDGET_EXHAUSTED"): `spent + reserve_usd > approved_budget_usd`, or the token cap would be
            exceeded.
        """
        if self.spent_usd + reservation.reserve_usd > approved_budget_usd + 1e-12:
            raise Blocked("BUDGET_EXHAUSTED",
                          f"{reservation.call} needs up to ${reservation.reserve_usd:.4f}; ${self.spent_usd:.4f} of "
                          f"${approved_budget_usd:.2f} is already spent or reserved",
                          details={"call": reservation.call, "spent_usd": round(self.spent_usd, 6),
                                   "reserve_usd": round(reservation.reserve_usd, 6),
                                   "approved_budget_usd": approved_budget_usd})
        if max_tokens is not None and self.spent_tokens + reservation.reserve_tokens > max_tokens:
            raise Blocked("BUDGET_EXHAUSTED",
                          f"{reservation.call} needs up to {reservation.reserve_tokens} tokens; {self.spent_tokens} "
                          f"of the {max_tokens}-token cap are already used",
                          details={"call": reservation.call, "spent_tokens": self.spent_tokens,
                                   "reserve_tokens": reservation.reserve_tokens, "max_tokens": max_tokens})


def check_approval(*, approved_budget_usd: float, max_spend_usd: float, estimate_usd: float) -> None:
    """Raises:
        Blocked("BUDGET_ABOVE_PLAN_CAP", cap=...): approved > plan cap.
        Blocked("BUDGET_BELOW_ESTIMATE", estimate=...): approved < plan estimate.
    """
    if approved_budget_usd > max_spend_usd:
        raise Blocked("BUDGET_ABOVE_PLAN_CAP",
                      f"approved ${approved_budget_usd:.2f} is above the plan cap ${max_spend_usd:.2f}",
                      cap=f"{max_spend_usd:.2f}")
    if approved_budget_usd < estimate_usd:
        raise Blocked("BUDGET_BELOW_ESTIMATE",
                      f"approved ${approved_budget_usd:.2f} is below the plan estimate ${estimate_usd:.4f}",
                      estimate=f"{math.ceil(estimate_usd * 100) / 100:.2f}")
