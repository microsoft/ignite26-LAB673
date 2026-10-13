from __future__ import annotations

from dataclasses import asdict

from ekg_core.models import Operation, Plan, ProvisioningSpec, stable_id
from .access import PERMISSIONS as ACCESS_PERMISSIONS, operations as access_operations
from .network import network_operations
from .public_test import validate_public_test


def plan(spec: ProvisioningSpec, *, require_active: bool = True) -> Plan:
    validate_public_test(spec, require_active=require_active)
    operations: list[Operation] = []
    network = network_operations(spec)
    if spec.build_access is not None and spec.public_test is None:
        raise ValueError("build access (identity, container, roles) needs a public-test plan")
    before_search, after_models = access_operations(spec)
    if spec.create_resource_group:
        operations.append(Operation(
            id="create-resource-group", plane="provision", action="create",
            resource="resource_group", name=spec.target.resource_group or "",
            risk="billable_remote_change", reversible=False, requires_approval=True,
            evidence=("resource_id", "location"),
        ))
    operations.extend(before_search)
    for resource, name in (
        ("search_service", spec.search_name),
        ("storage_account", spec.storage_name),
        ("openai_resource", spec.openai_name),
    ):
        operations.append(Operation(
            id=f"create-{resource}", plane="provision", action="ensure",
            resource=resource, name=name, risk="billable_remote_change",
            reversible=False, requires_approval=True,
            evidence=("resource_id", "endpoint", "provisioning_state", "public_network_access"),
            depends_on=(("create-search-identity",)
                        if resource == "search_service" and before_search else ()),
        ))
    if spec.content_understanding_name:
        operations.append(Operation(
            id="create-content-understanding", plane="provision", action="ensure",
            resource="content_understanding", name=spec.content_understanding_name,
            risk="billable_remote_change", reversible=False, requires_approval=True,
            evidence=("resource_id", "endpoint", "provisioning_state", "public_network_access"),
        ))
    for deployment in spec.model_deployments:
        operations.append(Operation(
            id=f"create-{deployment.role}-deployment", plane="provision", action="ensure",
            resource="model_deployment", name=deployment.name,
            risk="billable_remote_change", reversible=False, requires_approval=True,
            evidence=("resource_id", "sku", "capacity", "model", "provisioning_state",
                      "quota_preflight"),
            depends_on=("create-openai_resource",),
        ))
    operations.extend(after_models)
    operations.extend(network)
    old_spec = asdict(spec)
    if spec.build_access is None:
        old_spec.pop("build_access")
    if not spec.model_deployments:
        old_spec.pop("model_deployments")
    if spec.network is None:
        old_spec.pop("network")
    if spec.public_test is None:
        old_spec.pop("public_test")
    network_permissions = (
        "Microsoft.Network/virtualNetworks/read",
        "Microsoft.Network/virtualNetworks/write",
        "Microsoft.Network/virtualNetworks/subnets/read",
        "Microsoft.Network/virtualNetworks/subnets/write",
        "Microsoft.Network/privateDnsZones/read",
        "Microsoft.Network/privateDnsZones/write",
        "Microsoft.Network/privateDnsZones/virtualNetworkLinks/read",
        "Microsoft.Network/privateDnsZones/virtualNetworkLinks/write",
        "Microsoft.Network/privateEndpoints/read",
        "Microsoft.Network/privateEndpoints/write",
        "Microsoft.Network/privateEndpoints/privateDnsZoneGroups/read",
        "Microsoft.Network/privateEndpoints/privateDnsZoneGroups/write",
    ) if network else ()
    return Plan(
        plan_id=stable_id("provision-plan", old_spec),
        operations=tuple(operations),
        warnings=((
            "the resource group must already exist or be included in a separately "
            "approved plan before networking can be executed",
        ) if network and not spec.create_resource_group else ()) + ((
            "TEMPORARY PUBLIC TEST: synthetic data only; "
            + ("internet-reachable, Entra-authenticated endpoints (no IP firewall); "
               "user-delegation Blob SAS remains possible under Entra authority; "
               if spec.public_test.mode == "entra_only" else
               "restrict access to the exact approved VPN egress IPs; ")
            + "manually remove resources before the stated expiry. "
            "Expiry is an apply gate, not automatic shutdown or cleanup.",
            ("SETUP ONLY: this plan does not ingest documents or build a graph. "
             "Role assignments can take up to 15 minutes to take effect; Build "
             "is a separately approved step."
             if spec.build_access else
             "PROVISIONING ONLY: This plan does not create data-plane RBAC"
             + ("" if spec.model_deployments else ", deploy models")
             + ", ingest a graph, or grant Search managed graphExtraction preview "
             "access. It cannot prove end-to-end EKG retrieval. A separately approved, "
             "separately approved exact-service guarded Build and verified Consume are "
             "required; Search indexer service-to-service access remains untested. "
             "Synthetic client-side push/query smoke needs separate data-plane "
             "approval and Entra roles.")
            + (" Run the IP-mode smoke from a client on the allowlist."
               if spec.public_test.mode == "ip_allowlist" else ""),
        ) if spec.public_test else ()),
        required_permissions=(
            "Microsoft.Resources/subscriptions/resourceGroups/read",
            *(
                ("Microsoft.Resources/subscriptions/resourceGroups/write",)
                if spec.create_resource_group else ()
            ),
            "Microsoft.Search/searchServices/read",
            "Microsoft.Search/searchServices/write",
            "Microsoft.Storage/storageAccounts/read",
            "Microsoft.Storage/storageAccounts/write",
            "Microsoft.CognitiveServices/accounts/read",
            "Microsoft.CognitiveServices/accounts/write",
            *((
                "Microsoft.CognitiveServices/accounts/deployments/read",
                "Microsoft.CognitiveServices/accounts/deployments/write",
                "Microsoft.CognitiveServices/locations/usages/read",
                "Microsoft.CognitiveServices/locations/models/read",
            ) if spec.model_deployments else ()),
            *(ACCESS_PERMISSIONS if spec.build_access else ()),
            *network_permissions,
        ),
    )
