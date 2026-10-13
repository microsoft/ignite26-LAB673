from __future__ import annotations

import ipaddress
import re
from typing import Any

from ekg_core.models import NetworkSpec, Operation, ProvisioningSpec


ZONES = {
    "search": ("searchService", "privatelink.search.windows.net", "search_service"),
    "blob": ("blob", "privatelink.blob.core.windows.net", "storage_account"),
    "openai": ("account", "privatelink.openai.azure.com", "openai_resource"),
    "content": ("account", "privatelink.cognitiveservices.azure.com", "content_understanding"),
}
NETWORK_API = {
    "vnet": "2024-05-01",
    "subnet": "2024-05-01",
    "endpoint": "2024-05-01",
    "zone_group": "2024-05-01",
    "zone": "2024-06-01",
    "zone_link": "2024-06-01",
}


def validate_network(spec: ProvisioningSpec) -> None:
    network = spec.network
    if network is None:
        return
    if not isinstance(network, NetworkSpec):
        raise ValueError("network must be a NetworkSpec")
    for name, value, pattern in (
        ("subscription_id", spec.target.subscription_id,
         r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"),
        ("resource_group", spec.target.resource_group, r"[a-zA-Z0-9_.()\-]{1,90}"),
        ("search_name", spec.search_name, r"[a-z0-9][a-z0-9-]{0,58}[a-z0-9]"),
        ("storage_name", spec.storage_name, r"[a-z0-9]{3,24}"),
        ("openai_name", spec.openai_name, r"[a-zA-Z0-9][a-zA-Z0-9_-]{1,63}"),
    ):
        if not isinstance(value, str) or not re.fullmatch(pattern, value):
            raise ValueError(f"invalid or missing {name} for networking plan")
    if spec.target.resource_group.endswith("."):
        raise ValueError("resource_group cannot end in a period")
    if spec.content_understanding_name is not None and (
        not isinstance(spec.content_understanding_name, str)
        or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{1,63}",
                            spec.content_understanding_name)
        or spec.content_understanding_name == spec.openai_name
    ):
        raise ValueError("invalid content_understanding_name")
    for name, value in (("vnet_name", network.vnet_name),
                        ("subnet_name", network.subnet_name)):
        if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}", value):
            raise ValueError(f"invalid {name}")
    for name, value in (("vnet_cidr", network.vnet_cidr),
                        ("subnet_cidr", network.subnet_cidr)):
        try:
            prefix = ipaddress.IPv4Network(value, strict=True)
        except (ValueError, TypeError) as error:
            raise ValueError(f"{name} must be a caller-approved canonical IPv4 CIDR") from error
        if prefix.is_multicast or prefix.is_loopback or prefix.is_link_local or prefix.is_unspecified:
            raise ValueError(f"{name} must be a routable private test-network prefix")
    vnet = ipaddress.IPv4Network(network.vnet_cidr)
    subnet = ipaddress.IPv4Network(network.subnet_cidr)
    if not subnet.subnet_of(vnet) or subnet.prefixlen < 16 or subnet.prefixlen > 27:
        raise ValueError("subnet_cidr must fit within vnet_cidr and provide usable endpoint IPs")
    private_blocks = tuple(ipaddress.IPv4Network(cidr) for cidr in (
        "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"
    ))
    if not any(vnet.subnet_of(block) for block in private_blocks):
        raise ValueError("approved network CIDRs must use RFC 1918 address space")
    if spec.target.location != "westus3":
        raise ValueError("isolated network test region must be westus3")


def network_operations(spec: ProvisioningSpec) -> tuple[Operation, ...]:
    if spec.network is None:
        return ()
    validate_network(spec)
    network = spec.network
    group = ("create-resource-group",) if spec.create_resource_group else ()

    def op(kind: str, name: str, dependencies: tuple[str, ...], suffix: str) -> Operation:
        return Operation(
            id=f"create-network-{suffix}", plane="provision", action="ensure",
            resource=kind, name=name, risk="billable_remote_change",
            requires_approval=True, evidence=("resource_id", "provisioning_state", "configuration"),
            depends_on=dependencies,
        )

    result = [
        op("vnet", network.vnet_name, group, "vnet"),
        op("subnet", network.subnet_name, ("create-network-vnet",), "subnet"),
    ]
    for key in ZONES:
        if key == "content" and not spec.content_understanding_name:
            continue
        _, zone, service = ZONES[key]
        result.append(op("zone", zone, group, f"zone-{key}"))
        result.append(op("zone_link", "ekg-vnet-link",
                         (f"create-network-zone-{key}", "create-network-vnet"),
                         f"link-{key}"))
        result.append(op("endpoint", f"{network.vnet_name}-{key}-pe",
                         ("create-network-subnet", f"create-{service}"),
                         f"endpoint-{key}"))
        result.append(op("zone_group", "default",
                         (f"create-network-endpoint-{key}", f"create-network-zone-{key}"),
                         f"dns-group-{key}"))
    return tuple(result)


def network_id(spec: ProvisioningSpec, operation: Operation) -> str:
    network = spec.network
    assert network is not None
    base = f"/subscriptions/{spec.target.subscription_id}/resourceGroups/{spec.target.resource_group}"
    kind = operation.resource
    if kind == "vnet":
        return f"{base}/providers/Microsoft.Network/virtualNetworks/{network.vnet_name}"
    if kind == "subnet":
        return f"{network_id(spec, Operation('', 'provision', '', 'vnet', network.vnet_name))}/subnets/{network.subnet_name}"
    if kind in ("zone", "zone_link"):
        key = operation.id.rsplit("-", 1)[-1]
        zone = ZONES[key][1]
        path = f"{base}/providers/Microsoft.Network/privateDnsZones/{zone}"
        return path if kind == "zone" else f"{path}/virtualNetworkLinks/{operation.name}"
    key = operation.id.rsplit("-", 1)[-1]
    endpoint = f"{base}/providers/Microsoft.Network/privateEndpoints/{network.vnet_name}-{key}-pe"
    return endpoint if kind == "endpoint" else f"{endpoint}/privateDnsZoneGroups/default"


def network_desired(
    spec: ProvisioningSpec, operation: Operation, *, run_id: str | None = None,
    plan_id: str | None = None,
) -> dict:
    network = spec.network
    assert network is not None
    kind = operation.resource
    key = operation.id.rsplit("-", 1)[-1]
    tags = {"ekg-run-id": run_id, "ekg-plan-id": plan_id} if run_id and plan_id else {}
    if kind == "vnet":
        return {"location": spec.target.location, "tags": tags,
                "properties": {"addressSpace": {"addressPrefixes": [network.vnet_cidr]}}}
    if kind == "subnet":
        return {"properties": {"addressPrefix": network.subnet_cidr,
                               "privateEndpointNetworkPolicies": "Disabled"}}
    if kind == "zone":
        return {"location": "global", "tags": tags, "properties": {}}
    if kind == "zone_link":
        return {"location": "global", "tags": tags,
                "properties": {"virtualNetwork": {"id": network_id(
                    spec, Operation('', 'provision', '', 'vnet', network.vnet_name))},
                    "registrationEnabled": False}}
    group_id, zone_name, service = ZONES[key]
    if kind == "endpoint":
        from ekg_core.models import Operation as ResourceOperation
        from .backends import _resource_id
        target_name = {
            "search_service": spec.search_name,
            "storage_account": spec.storage_name,
            "openai_resource": spec.openai_name,
            "content_understanding": spec.content_understanding_name,
        }[service]
        return {"location": spec.target.location, "tags": tags,
                "properties": {"subnet": {"id": network_id(
                    spec, Operation('', 'provision', '', 'subnet', network.subnet_name))},
                    "privateLinkServiceConnections": [{
                        "name": f"{key}-connection",
                        "properties": {"privateLinkServiceId": _resource_id(
                            spec, ResourceOperation('', 'provision', '', service, target_name or "")),
                            "groupIds": [group_id]},
                    }]}}
    return {"properties": {"privateDnsZoneConfigs": [{
        "name": key, "properties": {"privateDnsZoneId": network_id(
            spec, Operation(f"create-network-zone-{key}", 'provision', '', 'zone', zone_name))}
    }]}}


def network_evidence(spec: ProvisioningSpec, operation: Operation, observed: Any) -> dict:
    from .backends import ProvisioningError, _field

    def same_id(actual: Any, expected: str) -> bool:
        return isinstance(actual, str) and actual.lower() == expected.lower()

    expected_id = network_id(spec, operation)
    actual_id = _field(observed, "id")
    if not same_id(actual_id, expected_id):
        raise ProvisioningError(f"{operation.id}: unexpected resource ID")
    desired = network_desired(spec, operation)
    kind = operation.resource
    if "location" in desired and str(_field(observed, "location")).lower() != desired["location"]:
        raise ProvisioningError(f"{operation.id}: location differs")
    properties = _field(observed, "properties", {})
    expected_properties = desired["properties"]
    if kind == "vnet":
        actual = _field(_field(properties, "addressSpace", {}), "addressPrefixes")
        if actual != expected_properties["addressSpace"]["addressPrefixes"]:
            raise ProvisioningError(f"{operation.id}: addressPrefixes drift")
    elif kind == "subnet":
        for field in ("addressPrefix", "privateEndpointNetworkPolicies"):
            if _field(properties, field) != expected_properties[field]:
                raise ProvisioningError(f"{operation.id}: {field} drift")
    elif kind == "zone_link":
        if not same_id(
            _field(_field(properties, "virtualNetwork", {}), "id"),
            expected_properties["virtualNetwork"]["id"],
        ) or _field(properties, "registrationEnabled") is not False:
            raise ProvisioningError(f"{operation.id}: VNet link drift")
    elif kind == "endpoint":
        if not same_id(
            _field(_field(properties, "subnet", {}), "id"),
            expected_properties["subnet"]["id"],
        ):
            raise ProvisioningError(f"{operation.id}: subnet drift")
        connections = _field(properties, "privateLinkServiceConnections")
        expected = expected_properties["privateLinkServiceConnections"][0]
        if not isinstance(connections, list) or len(connections) != 1:
            raise ProvisioningError(f"{operation.id}: private link connections drift")
        actual = _field(connections[0], "properties", {})
        if (not same_id(
            _field(actual, "privateLinkServiceId"),
            expected["properties"]["privateLinkServiceId"],
        )
            or _field(actual, "groupIds") != expected["properties"]["groupIds"]):
            raise ProvisioningError(f"{operation.id}: private link target/groupIds drift")
        if _field(_field(actual, "privateLinkServiceConnectionState", {}), "status") != "Approved":
            raise ProvisioningError(f"{operation.id}: private link connection not Approved")
    elif kind == "zone_group":
        configs = _field(properties, "privateDnsZoneConfigs")
        expected = expected_properties["privateDnsZoneConfigs"][0]
        if not isinstance(configs, list) or len(configs) != 1 or (
            _field(configs[0], "name") != expected["name"]
            or not same_id(
                _field(_field(configs[0], "properties", {}), "privateDnsZoneId"),
                expected["properties"]["privateDnsZoneId"],
            )
        ):
            raise ProvisioningError(f"{operation.id}: private DNS zone group drift")
    state = _field(properties, "provisioningState")
    if not isinstance(state, str) or state.lower() != "succeeded":
        raise ProvisioningError(f"{operation.id}: provisioning state is {state!r}, not Succeeded")
    return {"resource_id": actual_id, "provisioning_state": state,
            "configuration": expected_properties,
            **({"tags": _field(observed, "tags")} if _field(observed, "tags") else {})}
