from __future__ import annotations

from typing import Any


class CapabilityError(RuntimeError):
    def __init__(self, capability: str) -> None:
        self.capability = capability
        super().__init__(f"capability not enabled: {capability}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": "CAPABILITY_NOT_ENABLED",
            "capability": self.capability,
            "message": str(self),
        }


def capabilities(descriptor: dict[str, Any]) -> dict[str, bool]:
    return dict(descriptor.get("capabilities") or {})


def require_capability(descriptor: dict[str, Any], capability: str) -> None:
    if not capabilities(descriptor).get(capability, False):
        raise CapabilityError(capability)
