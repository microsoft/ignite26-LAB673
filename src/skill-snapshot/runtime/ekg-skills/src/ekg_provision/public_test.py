from __future__ import annotations

import ipaddress
import re
from datetime import datetime, timedelta, timezone

from ekg_core.models import ProvisioningSpec, PublicDataSpec, PublicTestSpec


MAX_DURATION = timedelta(hours=72)


def validate_public_test(spec: ProvisioningSpec, *, require_active: bool = True) -> None:
    test = spec.public_endpoint
    if test is None:
        return
    if spec.public_data is not None:
        if not isinstance(test, PublicDataSpec):
            raise ValueError("public_data must be a PublicDataSpec")
        if test.public_data_only is not True:
            raise ValueError("public-data requires independent public-data-only acknowledgement")
        if test.mode != "entra_only" or test.egress_ips:
            raise ValueError("public-data requires entra_only with no IP rules")
        if spec.build_access is None or {item.role for item in spec.model_deployments} != {
            "embedding", "chat"
        }:
            raise ValueError("public-data requires identity, private container, six roles and both models")
    elif not isinstance(test, PublicTestSpec):
        raise ValueError("public_test must be a PublicTestSpec")
    if spec.network is not None or spec.content_understanding_name is not None:
        raise ValueError("public test cannot use private networking or Content Understanding")
    if not spec.create_resource_group:
        raise ValueError("public test requires an isolated new resource group")
    guid = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
    for name, value, pattern in (
        ("tenant_id", test.tenant_id, guid),
        ("subscription_id", spec.target.subscription_id, guid),
        ("resource_group", spec.target.resource_group, r"[a-zA-Z0-9_.()\-]{1,90}"),
        ("location", spec.target.location, r"[a-z][a-z0-9]+"),
        ("search_name", spec.search_name, r"[a-z0-9][a-z0-9-]{0,58}[a-z0-9]"),
        ("storage_name", spec.storage_name, r"[a-z0-9]{3,24}"),
        ("openai_name", spec.openai_name, r"[a-zA-Z0-9][a-zA-Z0-9_-]{1,63}"),
    ):
        if not isinstance(value, str) or not re.fullmatch(pattern, value):
            raise ValueError(f"public test requires a valid explicit {name}")
    if spec.target.resource_group.endswith("."):
        raise ValueError("public test resource group cannot end in a period")
    if spec.search_sku != "basic":
        raise ValueError("public test requires Search Basic for firewall support")
    if isinstance(test, PublicTestSpec) and test.synthetic_data_only is not True:
        raise ValueError("public test requires synthetic-data-only acknowledgement")
    if test.mode not in ("ip_allowlist", "entra_only"):
        raise ValueError("public test requires an explicit supported ingress mode")
    if not isinstance(test.egress_ips, tuple):
        raise ValueError("public test egress IPs must be a tuple")
    if test.mode == "entra_only" and test.egress_ips:
        raise ValueError("entra_only must not include IP rules; select one explicit mode")
    if test.mode == "ip_allowlist" and not 1 <= len(test.egress_ips) <= 4:
        raise ValueError("ip_allowlist requires 1-4 exact VPN egress IPv4 addresses")
    if any(not isinstance(address, str) for address in test.egress_ips):
        raise ValueError("public test requires exact public IPv4 addresses")
    if len(set(test.egress_ips)) != len(test.egress_ips):
        raise ValueError("public test egress IPs must be unique")
    for address in test.egress_ips:
        try:
            parsed = ipaddress.IPv4Address(address)
        except ValueError as error:
            raise ValueError("public test requires exact public IPv4 addresses") from error
        if not parsed.is_global or str(parsed) != address:
            raise ValueError("public test requires canonical globally routable IPv4 addresses")
    if not isinstance(test.expires_at, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", test.expires_at
    ):
        raise ValueError("public test expiry must be UTC YYYY-MM-DDTHH:MM:SSZ")
    try:
        expiry = datetime.strptime(test.expires_at, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as error:
        raise ValueError("invalid public test expiry") from error
    remaining = expiry - datetime.now(timezone.utc)
    if require_active and not timedelta(0) < remaining <= MAX_DURATION:
        raise ValueError("public test expiry must be in the next 72 hours")
