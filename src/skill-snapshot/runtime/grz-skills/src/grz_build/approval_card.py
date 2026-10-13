"""One approval card format for every grz-build write gate: apply, publish and retire.

The card is display-only. It is attached to command output after the plan is saved, so it never feeds a plan digest.
"""

from __future__ import annotations

import math
from typing import Any

from grz_core.cli_output import mb

# Measured live: apply took about 4 min for 7,296 chunks; each naming call took about 2.4 s.
_MIN_PER_1K_CHUNKS = (0.3, 0.7)
_NAMING_SECONDS_PER_CALL = 2.4


def _minutes(low: float, high: float) -> tuple[int, int]:
    lo = max(1, math.floor(low))
    return lo, max(lo + 1, math.ceil(high))


def build(*, what: str, account: dict[str, Any], plan_id: str, changes: list[str],
          minutes: tuple[int, int], one_time_usd: float = 0.0, ongoing: str = "none") -> dict[str, Any]:
    tenant_id = account.get("tenant_id") or ""
    tenant = f"{account.get('tenant_name') or 'name unavailable'} ({tenant_id[:8]}…)"
    subscription = account.get("subscription_name") or f"{(account.get('subscription_id') or '')[:8]}…"
    group = f"{account.get('resource_group')} (existing)"
    lines = [f"APPROVAL: {what}",
             f"Tenant: {tenant} · Subscription: {subscription} · Resource group: {group}",
             f"Plan ID: {plan_id}",
             f"Changes ({len(changes)}):",
             *(f"  {n}. {change}" for n, change in enumerate(changes, 1)),
             f"Time: about {minutes[0]}–{minutes[1]} min",
             f"Cost: about ${one_time_usd:.2f} one-time; ongoing: {ongoing}",
             "No automatic retry or cleanup.",
             f'Reply "approved {plan_id}" to proceed.']
    return {"what": what, "tenant": tenant, "subscription": subscription, "resource_group": group,
            "plan_id": plan_id, "changes": changes, "minutes": list(minutes),
            "one_time_usd": round(one_time_usd, 2), "ongoing": ongoing,
            "reply": f"approved {plan_id}", "text": "\n".join(lines)}


def for_apply(plan: dict[str, Any], account: dict[str, Any]) -> dict[str, Any]:
    source = plan["source"]
    changes = [f"Create a new search index {plan['target_index']} on {plan['search_service']}.",
               f"Upload up to {plan['estimated_documents']:,} community documents to it, within a budget of {mb(plan['estimated_bytes'])} "
               "(apply stops before writing if they come out larger)."]
    budget = plan.get("naming_budget")
    one_time = 0.0
    naming_minutes = (0.0, 0.0)
    if budget:
        one_time = float(budget["max_spend"])
        changes.append(f"Call your model deployment up to {budget['max_calls']} times to name communities "
                       f"(at most {budget['max_tokens']:,} tokens, ${one_time:.2f}).")
        naming_minutes = (budget["max_calls"] * _NAMING_SECONDS_PER_CALL / 120, budget["max_calls"] * _NAMING_SECONDS_PER_CALL / 60)
    readers = plan.get("reader_grants")
    if readers and readers.get("grant"):
        changes.append(f"Grant read access to {len(readers['grant'])} identit{'y' if len(readers['grant']) == 1 else 'ies'} on the new index.")
    attested = plan.get("source_visibility")
    if attested:
        changes.append(f"{attested['approval']}. The index has no per-document visibility field to check.")
    chunks = source["expected_count"] / 1000
    minutes = _minutes(chunks * _MIN_PER_1K_CHUNKS[0] + naming_minutes[0], chunks * _MIN_PER_1K_CHUNKS[1] + naming_minutes[1] + 1)
    return build(what=f"build GRZ communities from {source['index']} (nothing goes live until you publish)",
                 account=account, plan_id=plan["plan_id"], changes=changes, minutes=minutes, one_time_usd=one_time)


def for_publish(generation_id: str, physical_index: str, alias: str, account: dict[str, Any]) -> dict[str, Any]:
    changes = [f"Point the alias {alias} at {physical_index}; everyone browsing {alias} sees the new communities.",
               "Make this build the default for grz-consume and the MCP tools on this machine."]
    return build(what=f"publish the new communities to {alias}", account=account, plan_id=generation_id,
                 changes=changes, minutes=(1, 2))


def for_retire(plan: dict[str, Any], account: dict[str, Any]) -> dict[str, Any]:
    changes = [f"Delete the search index {plan['index']} ({plan['document_count']:,} docs, {mb(plan['storage_bytes'])}). "
               "The published generation and the source index are untouched."]
    readers = plan.get("reader_grants") or []
    if readers:
        changes.append(f"Remove {len(readers)} reader grant(s) on that index.")
    return build(what=f"retire the superseded generation {plan['index']}", account=account, plan_id=plan["plan_id"],
                 changes=changes, minutes=(1, 2))
