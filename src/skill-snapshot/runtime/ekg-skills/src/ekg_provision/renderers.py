from __future__ import annotations

from pathlib import Path

from ekg_core.models import ProvisioningSpec
from .planner import plan


def render_bicep_parameters(spec: ProvisioningSpec) -> dict:
    from .network import validate_network
    validate_network(spec)
    reviewed = plan(spec)
    return {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
        "contentVersion": "1.0.0.0",
        "parameters": {
            "location": {"value": spec.target.location},
            "searchName": {"value": spec.search_name},
            "storageName": {"value": spec.storage_name},
            "openAiName": {"value": spec.openai_name},
            "searchSku": {"value": spec.search_sku},
            "contentUnderstandingName": {"value": spec.content_understanding_name or ""},
            "networkEnabled": {"value": spec.network is not None},
            "networkVnetName": {"value": spec.network.vnet_name if spec.network else ""},
            "networkSubnetName": {"value": spec.network.subnet_name if spec.network else ""},
            "networkVnetCidr": {"value": spec.network.vnet_cidr if spec.network else ""},
            "networkSubnetCidr": {"value": spec.network.subnet_cidr if spec.network else ""},
            "publicTestEnabled": {"value": spec.public_test is not None},
            "publicTestMode": {"value": spec.public_test.mode if spec.public_test else ""},
            "publicTestIps": {"value": list(spec.public_test.egress_ips) if spec.public_test else []},
            "publicTestExpiresAt": {"value": spec.public_test.expires_at if spec.public_test else ""},
            "publicTestTenantId": {"value": spec.public_test.tenant_id if spec.public_test else ""},
            "syntheticDataOnly": {"value": spec.public_test.synthetic_data_only if spec.public_test else False},
            **({
                "publicDataEnabled": {"value": True},
                "publicDataOnly": {"value": spec.public_data.public_data_only},
                "publicDataExpiresAt": {"value": spec.public_data.expires_at},
                "publicDataTenantId": {"value": spec.public_data.tenant_id},
            } if spec.public_data else {}),
            "expectedPlanId": {"value": reviewed.plan_id if spec.network or spec.public_endpoint else ""},
            "approvedPlanId": {"value": ""},
            "expectedSubscriptionId": {"value": spec.target.subscription_id if spec.network or spec.public_endpoint else ""},
            "expectedResourceGroup": {"value": spec.target.resource_group if spec.network or spec.public_endpoint else ""},
        },
    }


def _deployment_steps(spec: ProvisioningSpec) -> str:
    return "".join(
        f"- [ ] In `{spec.openai_name}`, deploy {item.role} model `{item.model}` version "
        f"`{item.version}` as `{item.name}`: SKU {item.sku}, capacity **{item.capacity}K TPM**, "
        "auto-upgrade off. Check regional quota first (`ekg-provision quota`).\n"
        for item in spec.model_deployments
    )


def _access_steps(spec: ProvisioningSpec) -> str:
    if spec.build_access is None:
        return ""
    from .access import plain_writes
    return "".join(
        f"- [ ] {line}.\n"
        for operation in plan(spec).operations
        if operation.resource in ("search_identity", "blob_container", "role_assignment")
        for line in plain_writes(spec, (operation,))
    )


def render_portal_checklist(spec: ProvisioningSpec) -> str:
    location = spec.target.location or "<approved-region>"
    from .network import ZONES, validate_network
    validate_network(spec)
    from .public_test import validate_public_test
    validate_public_test(spec)
    if spec.public_endpoint:
        test = spec.public_endpoint
        label = "public-data Entra" if spec.public_data else "public-test"
        policy = "publicly available corpus only; no non-public data" if spec.public_data else "synthetic data only"
        if test.mode == "entra_only":
            ingress = (
                "Internet-reachable **all public networks**: NO IP firewall; access relies "
                "on Microsoft Entra identity, least-privilege RBAC and data-plane checks."
            )
            search = "Public access **All networks**, no IP rules"
            storage = "firewall default **Allow**, no IP/VNet/resource-instance rules"
            openai = "firewall default **Allow**, no IP/VNet rules"
            client = "Do not assert that only this test account can access the services: inherited/group/PIM roles may exist."
        else:
            ingress = f"Exact VPN egress IPv4 address(es) `{', '.join(test.egress_ips)}`"
            search = f"Public access **Selected IP addresses** (`{', '.join(test.egress_ips)}`)"
            storage = f"firewall default **Deny**, IP rules **Allow only** `{', '.join(test.egress_ips)}`"
            openai = f"firewall default **Deny**, IP rules **only** `{', '.join(test.egress_ips)}`"
            client = "Verify from the approved VPN client; reject other public IPs."
        return f"""# Temporary {label} Portal checklist (review only)

- [ ] Confirm the explicitly selected tenant `{test.tenant_id}` and subscription `{spec.target.subscription_id}`.
- [ ] Confirm isolated `{spec.target.location}` resource group `{spec.target.resource_group}` is absent and separately approved for creation.
- [ ] Confirm **{test.mode}** mode: {ingress} Expiry `{test.expires_at}` UTC; **{policy}**.
- [ ] Search `{spec.search_name}` Basic, system identity: {search}; trusted services **off** (`networkRuleSet.bypass=None`); disable API-key/local authentication.
- [ ] Storage `{spec.storage_name}` Standard_LRS StorageV2: public endpoint **Enabled**, {storage}, trusted services **None**; disable public blob, Shared Key, local users and SFTP; prefer OAuth in Portal, require HTTPS/TLS 1.2. Account/service SAS are blocked by `allowSharedKeyAccess=false`; **Entra-backed user-delegation Blob SAS remains possible**. Do not mint or use SAS.
- [ ] OpenAI `{spec.openai_name}` S0: public endpoint **Enabled**, {openai}, trusted services **None**; disable local-key authentication.
{_deployment_steps(spec)}{_access_steps(spec)}- [ ] Verify effective ARM settings and authenticated Search/Storage data-plane reads before data writes; use the approved scoped Entra RBAC. {client}
- [ ] Manually remove test resources before `{test.expires_at}` UTC under separate cleanup review; expiry does not disable/delete anything automatically.

**Review only:** Bicep public deployment deliberately fails closed; use only the gated SDK CLI after a separate exact-plan approval. This checklist creates nothing.
"""
    network_steps = ""
    if spec.network:
        network = spec.network
        network_steps = (
            f"- [ ] Create VNet `{network.vnet_name}` with approved CIDR `{network.vnet_cidr}` "
            f"and subnet `{network.subnet_name}` with approved CIDR `{network.subnet_cidr}`; "
            "set private endpoint network policies Disabled.\n"
        )
        for key, (group, zone, service) in ZONES.items():
            if key == "content" and not spec.content_understanding_name:
                continue
            name = {
                "search_service": spec.search_name,
                "storage_account": spec.storage_name,
                "openai_resource": spec.openai_name,
                "content_understanding": spec.content_understanding_name,
            }[service]
            network_steps += (
                f"- [ ] Create private DNS zone `{zone}`; link to `{network.vnet_name}` "
                f"with auto-registration disabled. Create private endpoint "
                f"`{network.vnet_name}-{key}-pe` for `{name}` (subresource `{group}`) "
                f"in `{network.subnet_name}`; create default DNS zone group for `{zone}`. "
                "Verify connection Approved, DNS records and private resolution from a network client.\n"
            )
    return f"""# Portal provisioning checklist

- [ ] Select resource group `{spec.target.resource_group or '<resource-group>'}`.
- [ ] Select region `{location}`.
- [ ] Create Azure AI Search `{spec.search_name}` with SKU `{spec.search_sku}` and public network access **Disabled**.
- [ ] Create StorageV2 account `{spec.storage_name}` with public network access **Disabled** and public blob access disabled.
- [ ] Create Azure OpenAI resource `{spec.openai_name}` with public network access **Disabled**.
{_deployment_steps(spec)}{f"- [ ] Create Content Understanding `{spec.content_understanding_name}` with public network access **Disabled**." if spec.content_understanding_name else ""}
{network_steps}
- [ ] Apply the approved managed identity and RBAC assignments.
- [ ] Complete API-only Search preview resources using the direct backend.
- [ ] Run `ekg.provision.verify`.

This checklist creates nothing automatically. Without separately approved private networking and a client path, data-plane access remains unavailable.
"""


def write_artifacts(spec: ProvisioningSpec, output: str | Path) -> tuple[Path, Path]:
    rendered = render_bicep_parameters(spec)
    checklist = render_portal_checklist(spec)
    root = Path(output)
    root.mkdir(parents=True, exist_ok=True)
    parameters = root / "parameters.json"
    portal = root / "portal.md"
    import json

    parameters.write_text(json.dumps(rendered, indent=2) + "\n", encoding="utf-8")
    portal.write_text(checklist, encoding="utf-8")
    return parameters, portal
