"""Name validation for grounding indexes, resource groups and Search services."""

from __future__ import annotations

import re

from .errors import GroundingError

DEFAULT_PREFIX = "grounding-"
INDEX_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,60}$")
SERVICE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,58}[a-z0-9]$")
RG_NAME_RE = re.compile(r"^[A-Za-z0-9_().-]{1,90}$")


def validate_index_name(name: str, prefix: str = DEFAULT_PREFIX) -> str:
    if not isinstance(name, str) or not INDEX_NAME_RE.match(name):
        raise GroundingError("NAME_INVALID", f"index name {name!r} must match {INDEX_NAME_RE.pattern}",
                             "Use lowercase letters, digits and dashes, starting with a letter.")
    if name.endswith("-") or "--" in name:
        raise GroundingError("NAME_INVALID", f"index name {name!r} must not end with or repeat dashes")
    if prefix and not name.startswith(prefix):
        raise GroundingError("NAME_PREFIX", f"index name {name!r} must start with {prefix!r}",
                             f"Rename it, for example {prefix}{name}.")
    return name


def validate_service_name(name: str) -> str:
    if not isinstance(name, str) or not SERVICE_NAME_RE.match(name) or "--" in name:
        raise GroundingError("SERVICE_NAME_INVALID",
                             f"Search service name {name!r} must be 2-60 lowercase letters, digits or single dashes")
    return name


def validate_resource_group_name(name: str) -> str:
    if not isinstance(name, str) or not RG_NAME_RE.match(name) or name.endswith("."):
        raise GroundingError("RESOURCE_GROUP_INVALID", f"resource group name {name!r} is invalid")
    return name


def default_index_name(seed: str) -> str:
    """Derive a valid default index name from free text."""
    slug = re.sub(r"[^a-z0-9]+", "-", seed.lower()).strip("-") or "edges"
    return (DEFAULT_PREFIX + slug)[:60].rstrip("-")
