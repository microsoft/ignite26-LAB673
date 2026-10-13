"""One approval card for every write gate (provision, connect setup, build, update, retire).

The card is plain text that an agent shows verbatim; the plan ID in it is the only thing
approval binds to. Names come from a best-effort, read-only Azure CLI lookup; when a name is
unknown the card still shows the ID prefix so the target is never ambiguous.
"""
from __future__ import annotations

import functools
import os
import subprocess
from typing import Any, Iterable

from .pricing import dollar_range, dollars

NO_RETRY = "No automatic retry or cleanup."


def _minutes(low: float, high: float) -> str:
    low, high = max(1, round(low)), max(1, round(high))
    return f"about {low} min" if low >= high else f"about {low}–{high} min"


def time_text(low_minutes: float, high_minutes: float) -> str:
    return _minutes(low_minutes, high_minutes)


def cost_text(one_time: tuple[float | None, float | None] | float | None,
              daily: float | None = 0.0, *,
              unknown_reason: str = "model price not listed") -> str:
    if isinstance(one_time, tuple):
        first = dollar_range(*one_time)
    else:
        first = dollars(one_time)
    ongoing = "none" if not daily else f"about {dollars(daily)}/day"
    if first == "unknown":
        return f"unknown ({unknown_reason}) one-time; ongoing: {ongoing}"
    return f"about {first} one-time; ongoing: {ongoing}"


def card(*, what: str, plan_id: str, changes: Iterable[str], time: str, cost: str,
         tenant_id: str | None, tenant_name: str | None = None,
         subscription: str | None = None, resource_group: str | None = None,
         new_group: bool = False, notes: Iterable[str] = ()) -> str:
    changes = [str(change) for change in changes]
    prefix = f"{tenant_id[:8]}…" if tenant_id else "unknown"
    tenant = f"{tenant_name or 'tenant'} ({prefix})"
    group = f"{resource_group or 'unknown'} ({'new' if new_group else 'existing'})"
    lines = [
        f"APPROVAL: {what}",
        f"Tenant: {tenant} · Subscription: {subscription or 'unknown'} · Resource group: {group}",
        f"Plan ID: {plan_id}",
        f"Changes ({len(changes)}):",
        *(f"  {number}. {change}" for number, change in enumerate(changes, 1)),
        *(str(note) for note in notes),
        f"Time: {time}",
        f"Cost: {cost}",
        NO_RETRY,
        f'Reply "approved {plan_id}" to proceed.',
    ]
    return "\n".join(lines)


def _az(arguments: list[str]) -> Any:
    from .az_identity import az_json
    # Pass subprocess.run itself: az_json resolves the full az path only for it, and
    # Windows can't launch the bare `az` .cmd shim.
    return az_json(arguments, runner=subprocess.run)


@functools.lru_cache(maxsize=16)
def azure_context(tenant_id: str | None = None, subscription_id: str | None = None,
                  search_service: str | None = None) -> dict[str, str]:
    """Read-only name lookup for the card; empty when disabled or unavailable."""
    if os.environ.get("EKG_APPROVAL_LOOKUP", "1") == "0":
        return {}
    found: dict[str, str] = {}
    try:
        account = _az(["account", "show"] + (["--subscription", subscription_id]
                                             if subscription_id else []))
    except Exception:
        account = None
    if isinstance(account, dict):
        if not tenant_id or str(account.get("tenantId", "")).lower() == tenant_id.lower():
            if account.get("tenantDisplayName"):
                found["tenant_name"] = str(account["tenantDisplayName"])
            if account.get("name"):
                found["subscription"] = str(account["name"])
    if search_service:
        try:
            hits = _az(["resource", "list", "--name", search_service, "--resource-type",
                        "Microsoft.Search/searchServices", "--query",
                        "[0].{group:resourceGroup, id:id}"])
        except Exception:
            hits = None
        if isinstance(hits, dict) and hits.get("group"):
            found["resource_group"] = str(hits["group"])
            if "subscription" not in found:
                parts = str(hits.get("id") or "").split("/")
                if len(parts) > 2:
                    found["subscription"] = parts[2]
    return found


def search_service_name(endpoint: str | None) -> str | None:
    if not endpoint:
        return None
    host = endpoint.split("://", 1)[-1].split("/", 1)[0]
    return host.split(".", 1)[0] or None


__all__ = ["NO_RETRY", "azure_context", "card", "cost_text", "search_service_name",
           "time_text"]
