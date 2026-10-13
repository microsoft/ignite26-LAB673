"""The standard approval card for every gate.

    APPROVAL: <what, one line>
    Tenant: <name> (<id prefix>…) · Subscription: <name> · Resource group: <rg> (new|existing)
    Plan ID: <id>
    Changes (<n>): numbered, plain language
    Time: about X–Y min
    Cost: about $X, at most $Y (cap $Z); ongoing: none
    No automatic retry or cleanup.
    Reply "approved <plan-id>" to proceed.

This plugin never creates Azure resources, so the resource group is always the model's existing one (or
n/a) and ongoing cost is always none.
"""

from __future__ import annotations

import math
from typing import Any

from ontology_core import state
from ontology_core.state import StatePaths

SECONDS_PER_CALL = (20, 90)
"""Rough wall-clock range per model call, for the Time line."""


def _usd(value: Any) -> str:
    try:
        return f"${float(value):.2f}"
    except (TypeError, ValueError):
        return "$?"


def _usd_up(value: Any) -> str:
    """Rounded up to the cent, so "at most" is never below the budget the user is asked to approve."""
    try:
        return f"${math.ceil(round(float(value) * 100, 6)) / 100:.2f}"
    except (TypeError, ValueError):
        return "$?"


def _scope(paths: StatePaths) -> str:
    if not paths.config.is_file():
        return "Tenant: n/a · Subscription: n/a · Resource group: n/a"
    config = state.load_config(paths)
    tenant = f"{config.tenant_name or 'tenant'} ({config.tenant_id[:8]}…)"
    sub = f"{config.model.subscription_id[:8]}…" if config.model.subscription_id else "n/a"
    rg = f"{config.model.resource_group} (existing)" if config.model.resource_group else "n/a"
    return f"Tenant: {tenant} · Subscription: {sub} · Resource group: {rg}"


def _minutes(calls: int) -> str:
    low, high = (max(1, math.ceil(calls * s / 60)) for s in SECONDS_PER_CALL)
    return f"Time: about {low}–{max(high, low + 1)} min"


def card(paths: StatePaths, *, what: str, plan_id: str, changes: list[str], time: str, cost: str) -> list[str]:
    return [f"APPROVAL: {what}", _scope(paths), f"Plan ID: {plan_id}", f"Changes ({len(changes)}):",
            *[f"  {i}. {c}" for i, c in enumerate(changes, 1)], time, cost,
            "No automatic retry or cleanup.", f'Reply "approved {plan_id}" to proceed.']


def for_plan(paths: StatePaths, result: dict[str, Any]) -> list[str]:
    """The card for a saved `plan` (propose, critique or refine): approving it allows the model spend."""
    est, caps = result.get("estimate") or {}, result.get("caps") or {}
    calls = int(result.get("calls") or est.get("calls") or 0)
    kind = result.get("kind") or "propose"
    samples = int(result.get("judge_samples") or 1)
    judge = (f"{samples} judge samples per version, scored by the median" if samples > 1
             else "1 judge sample per version")
    deployment = f" on deployment {result['judge_deployment']}" if result.get("judge_deployment") else ""
    if kind == "critique":
        what = f"critique v{result.get('version')} with the model judge"
        changes = [f"Send v{result.get('version')} and its evidence to the model{deployment}: {calls} judge "
                   f"call(s) ({judge})",
                   "Write one critique record in the state dir (no new ontology version)"]
    elif kind == "refine":
        what = f"refine v{result.get('version')} for up to {result.get('rounds')} rounds"
        changes = [f"Send up to {calls} judge call(s) to the model{deployment} ({result.get('rounds')} rounds at "
                   f"most, {judge})",
                   "Write one new, unapproved ontology version per round that changes something"]
    else:
        what = "propose an ontology from the GRZ generation"
        changes = [f"Read {result.get('passages')} passages from the GRZ sidecar at level {result.get('level')} "
                   "(read-only)",
                   f"Send {calls} model call(s) to the connected deployment",
                   "Write one new, unapproved ontology version in the state dir"]
    expected = est.get("expected_usd", est.get("usd"))
    cost = (f"Cost: about {_usd(expected)}, at most {_usd_up(est.get('usd'))} "
            f"(cap {_usd(caps.get('max_spend_usd'))}); ongoing: none")
    return card(paths, what=what, plan_id=str(result["plan_id"]), changes=changes, time=_minutes(calls), cost=cost)


def for_review(paths: StatePaths, result: dict[str, Any]) -> list[str]:
    """The card for approving a reviewed version; the Plan ID is its schema ID."""
    n = result["version"]
    changes = [f"Mark v{n} ({result['classes']['count']} classes, {result['properties']['count']} properties) "
               "as approved in the state dir",
               "Record it as your current approved ontology (per-user pointer)"]
    return card(paths, what=f"approve ontology v{n}", plan_id=str(result["schema_id"]), changes=changes,
                time="Time: about 0–1 min", cost="Cost: about $0.00, at most $0.00 (cap n/a); ongoing: none")
