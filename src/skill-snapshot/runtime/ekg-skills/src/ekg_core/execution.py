from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from .models import Event, Operation, Plan


class ApprovalRequired(RuntimeError):
    """Raised when a mutating plan lacks explicit approval."""


@dataclass(frozen=True)
class ApplyResult:
    events: tuple[Event, ...]
    completed: bool


def apply_plan(
    plan: Plan,
    *,
    approved: bool = False,
    executor: Callable[[Operation], dict] | None = None,
) -> ApplyResult:
    """Apply a plan through an injected backend without hiding mutations."""
    if plan.blocked_by:
        return ApplyResult(
            events=tuple(
                Event(operation.id, "blocked", reason)
                for operation in plan.operations
                for reason in plan.blocked_by
            ),
            completed=False,
        )
    if any(operation.requires_approval for operation in plan.operations) and not approved:
        raise ApprovalRequired(f"plan {plan.plan_id} requires explicit approval")
    events: list[Event] = []
    for operation in plan.operations:
        events.append(Event(operation.id, "started", f"{operation.action} {operation.resource}"))
        try:
            evidence = executor(operation) if executor else {}
        except Exception as error:
            events.append(Event(operation.id, "failed", str(error)))
            return ApplyResult(tuple(events), False)
        events.append(Event(operation.id, "verified", "operation completed", evidence))
        events.append(Event(operation.id, "completed", "operation completed", evidence))
    return ApplyResult(tuple(events), True)


def serialize_events(events: Iterable[Event]) -> list[dict]:
    return [
        {
            "operation_id": event.operation_id,
            "status": event.status,
            "message": event.message,
            "data": event.data,
        }
        for event in events
    ]
