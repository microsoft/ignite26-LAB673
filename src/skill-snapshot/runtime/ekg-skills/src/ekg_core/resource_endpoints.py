"""Canonical ARM endpoint selection shared by Connect and Build inspection."""

import re
from typing import Any

_HTTPS_DNS_ROOT = re.compile(
    r"https://([A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)*)/?"
)


def canonical_resource_endpoint(endpoint: str | None) -> str | None:
    """Normalize only DNS host case and an optional single HTTPS root slash."""
    match = _HTTPS_DNS_ROOT.fullmatch(endpoint) if endpoint is not None else None
    return f"https://{match[1].lower()}" if match else endpoint


def cognitive_account_endpoint(properties: dict[str, Any]) -> str:
    """Prefer ARM endpoint; use the advertised OpenAI API only when it is absent."""
    if not isinstance(properties, dict):
        raise ValueError("Cognitive Services ARM properties must be an object")
    endpoint = properties.get("endpoint")
    if endpoint is None:
        endpoints = properties.get("endpoints")
        endpoint = (endpoints.get("OpenAI Language Model Instance API")
                    if isinstance(endpoints, dict) else None)
    match = _HTTPS_DNS_ROOT.fullmatch(endpoint) if isinstance(endpoint, str) else None
    if not match:
        raise ValueError("Cognitive Services ARM endpoint must be an HTTPS DNS root; "
                         "no valid account endpoint metadata was returned")
    return f"https://{match[1].lower()}"
