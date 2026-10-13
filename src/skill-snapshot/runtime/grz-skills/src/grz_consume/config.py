"""One connection config for grz-consume and grz-mcp: flags first, then GRZ_* environment variables."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, replace
from pathlib import Path

from grz_core.contracts import ContractError, Descriptor
from grz_core.current import read_current

from .service import ConsumeService

AUTH_MODES = ("query-key", "entra")


@dataclass(frozen=True)
class ConsumeConfig:
    descriptor: Path | None = None
    endpoint: str | None = None
    auth: str = "query-key"
    tenant_id: str | None = None
    query_key: str | None = None
    from_current: bool = False

    def with_descriptor(self, path: str | Path | None) -> "ConsumeConfig":
        return self if path is None else replace(self, descriptor=Path(path))


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name)
    return Path(value) if value else None


def add_connection_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--descriptor", type=Path, help="Published physical-index descriptor JSON (or GRZ_DESCRIPTOR)")
    parser.add_argument("--endpoint", help="HTTPS Azure Search endpoint (or GRZ_SEARCH_ENDPOINT)")
    parser.add_argument("--auth", choices=AUTH_MODES, help="Azure auth mode (or GRZ_SEARCH_AUTH); query-key reads GRZ_SEARCH_QUERY_KEY")
    parser.add_argument("--tenant-id", help="Tenant ID for --auth entra (or GRZ_TENANT_ID)")


def resolve_config(args: argparse.Namespace) -> ConsumeConfig:
    """Flags, then GRZ_* variables, then the build the user last published. Missing pieces are reported later."""
    auth = getattr(args, "auth", None) or os.environ.get("GRZ_SEARCH_AUTH")
    config = ConsumeConfig(
        descriptor=getattr(args, "descriptor", None) or _env_path("GRZ_DESCRIPTOR"),
        endpoint=getattr(args, "endpoint", None) or os.environ.get("GRZ_SEARCH_ENDPOINT"),
        auth=auth or "query-key",
        tenant_id=getattr(args, "tenant_id", None) or os.environ.get("GRZ_TENANT_ID"),
        query_key=getattr(args, "query_key", None),
    )
    if config.descriptor is None:
        current = read_current()
        if current is not None:
            config = replace(config, descriptor=Path(current["descriptor"]), from_current=True,
                             endpoint=config.endpoint or current["endpoint"], auth=auth or current["auth"],
                             tenant_id=config.tenant_id or current["tenant_id"])
    if config.auth not in AUTH_MODES:
        raise ContractError("AUTH_UNSUPPORTED", f"Auth mode {config.auth!r} is not query-key or entra")
    return config


def load_descriptor(config: ConsumeConfig) -> Descriptor:
    if config.descriptor is None:
        raise ContractError("DESCRIPTOR_REQUIRED", "No build to browse: nothing published from this account, "
                                                   "and no --descriptor or GRZ_DESCRIPTOR")
    try:
        data = json.loads(config.descriptor.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ContractError("DESCRIPTOR_INVALID", f"Cannot read {config.descriptor}: {exc.strerror or exc}") from exc
    except json.JSONDecodeError as exc:
        raise ContractError("DESCRIPTOR_INVALID", f"{config.descriptor} is not JSON") from exc
    if not isinstance(data, dict):
        raise ContractError("DESCRIPTOR_INVALID", f"{config.descriptor} is not a descriptor object")
    try:
        descriptor = Descriptor(**data)
    except TypeError as exc:
        raise ContractError("DESCRIPTOR_INVALID", f"{config.descriptor} has unknown or missing fields") from exc
    descriptor.validate()
    return descriptor


def build_service(config: ConsumeConfig) -> ConsumeService:
    descriptor = load_descriptor(config)
    if not config.endpoint:
        raise ContractError("SOURCE_REQUIRED", "Pass --endpoint (or GRZ_SEARCH_ENDPOINT)")
    from .connect import build_store

    store = build_store(descriptor, config.endpoint, config.auth, config.tenant_id,
                        query_key=config.query_key)
    return ConsumeService(store, descriptor)
