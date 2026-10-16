from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from ekg_core.execution import ApplyResult, ApprovalRequired, apply_plan
from ekg_core.models import ModelDeploymentSpec, Operation, Plan, ProvisioningSpec, stable_id
from ekg_core.telemetry import TelemetryRecorder
from .capacity import quota_preflight, read_regional_quota
from ekg_core.az_identity import IdentityError, active_az_identity, az_json, claims
from . import access
from .journal import ProvisioningJournal, journal_spec
from .network import NETWORK_API, network_desired, network_evidence, network_id, validate_network
from .planner import plan
from .public_test import validate_public_test


class ProvisioningError(RuntimeError):
    """The observed Azure state cannot safely satisfy the requested spec."""



_API_VERSIONS = {
    "search_service": "2025-05-01",
    "storage_account": "2023-05-01",
    "openai_resource": "2023-05-01",
    "content_understanding": "2023-05-01",
    "model_deployment": "2024-10-01",
    "search_identity": access.IDENTITY_API,
    "blob_container": access.CONTAINER_API,
    "role_assignment": access.ROLE_API,
}
_ACCESS = ("search_identity", "blob_container", "role_assignment")
# Cognitive Services 2023-05-01 GET omits networkAcls.bypass even when a
# 2024-10-01 GET explicitly reports None. Never treat an omitted bypass as safe.
_READ_API_VERSIONS = {**_API_VERSIONS, "openai_resource": "2024-10-01"}
_PROVIDERS = {
    "search_service": "Microsoft.Search/searchServices",
    "storage_account": "Microsoft.Storage/storageAccounts",
    "openai_resource": "Microsoft.CognitiveServices/accounts",
    "content_understanding": "Microsoft.CognitiveServices/accounts",
}


def _field(value: Any, key: str, default: Any = None) -> Any:
    # Newer ARM SDK models are Mappings keyed by REST names; their attributes
    # use snake_case names and enum types, so read them by key like a dict.
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _same_location(observed: Any, requested: str) -> bool:
    if not isinstance(observed, str):
        return False
    # ARM providers may return the region's display name instead of its canonical name.
    return observed.replace(" ", "").casefold() == requested.casefold()


def _validate(spec: ProvisioningSpec, *, require_active: bool = True) -> None:
    target = spec.target
    fields = {
        "subscription_id": (target.subscription_id, r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"),
        "resource_group": (target.resource_group, r"[a-zA-Z0-9_.()\-]{1,90}"),
        "location": (target.location, r"[a-zA-Z0-9-]+"),
        "search_name": (spec.search_name, r"[a-z0-9][a-z0-9-]{0,58}[a-z0-9]"),
        "storage_name": (spec.storage_name, r"[a-z0-9]{3,24}"),
        "openai_name": (spec.openai_name, r"[a-zA-Z0-9][a-zA-Z0-9_-]{1,63}"),
        "search_sku": (spec.search_sku, r"[a-zA-Z0-9_]+"),
    }
    if spec.content_understanding_name is not None:
        fields["content_understanding_name"] = (
            spec.content_understanding_name, r"[a-zA-Z0-9][a-zA-Z0-9_-]{1,63}"
        )
    for name, (value, pattern) in fields.items():
        if not isinstance(value, str) or not re.fullmatch(pattern, value):
            raise ValueError(f"invalid or missing {name}")
    if target.resource_group.endswith("."):
        raise ValueError("resource_group cannot end in a period")
    if spec.content_understanding_name == spec.openai_name:
        raise ValueError("Cognitive Services resource names must be distinct")
    validate_network(spec)
    validate_public_test(spec, require_active=require_active)


def _public_tags(spec: ProvisioningSpec) -> dict[str, str]:
    assert spec.public_endpoint is not None
    return {
        "ekg-plan-id": plan(spec, require_active=False).plan_id,
        ("ekg-public-data-expires-at" if spec.public_data
         else "ekg-public-test-expires-at"): spec.public_endpoint.expires_at,
    }


def _resource_id(spec: ProvisioningSpec, operation: Operation) -> str:
    base = f"/subscriptions/{spec.target.subscription_id}/resourceGroups/{spec.target.resource_group}"
    if operation.resource == "resource_group":
        return base
    if operation.resource in NETWORK_API:
        return network_id(spec, operation)
    if operation.resource == "search_identity":
        return access.identity_id(spec)
    if operation.resource == "blob_container":
        return access.container_id(spec)
    if operation.resource == "role_assignment":
        return access.role_assignment_id(spec, operation.id)
    if operation.resource == "model_deployment":
        return (f"{base}/providers/{_PROVIDERS['openai_resource']}/{spec.openai_name}"
                f"/deployments/{operation.name}")
    return f"{base}/providers/{_PROVIDERS[operation.resource]}/{operation.name}"


def _deployment(spec: ProvisioningSpec, operation: Operation) -> ModelDeploymentSpec:
    return next(item for item in spec.model_deployments if item.name == operation.name)


def _desired(spec: ProvisioningSpec, operation: Operation, *,
             identity_principal: str | None = None) -> dict:
    resource = operation.resource
    if resource in NETWORK_API:
        return network_desired(spec, operation)
    if resource in _ACCESS:
        return access.desired(
            spec, operation,
            principal_id=(access.principal_for(spec, operation.id, identity_principal)
                          if resource == "role_assignment" else None),
            tags=_public_tags(spec) if spec.public_endpoint else None,
        )
    if resource == "model_deployment":
        deployment = _deployment(spec, operation)
        return {
            "sku": {"name": deployment.sku, "capacity": deployment.capacity},
            "properties": {
                "model": {"format": "OpenAI", "name": deployment.model,
                          "version": deployment.version},
                "versionUpgradeOption": "NoAutoUpgrade",
            },
        }
    payload: dict[str, Any] = {"location": spec.target.location}
    if spec.public_endpoint:
        payload["tags"] = _public_tags(spec)
    entra_only = spec.public_endpoint is not None and spec.public_endpoint.mode == "entra_only"
    if resource == "search_service":
        payload.update(
            sku={"name": spec.search_sku},
            identity=({"type": "SystemAssigned, UserAssigned",
                       "userAssignedIdentities": {access.identity_id(spec): {}}}
                      if spec.build_access else {"type": "SystemAssigned"}),
            properties={
                "replicaCount": 1, "partitionCount": 1, "hostingMode": "default",
                "publicNetworkAccess": "Disabled",
            },
        )
        if spec.public_endpoint:
            payload["properties"].update(
                publicNetworkAccess="Enabled", disableLocalAuth=True,
                networkRuleSet={
                    "bypass": "None",
                    "ipRules": [{"value": ip} for ip in spec.public_endpoint.egress_ips],
                },
            )
    elif resource == "storage_account":
        payload.update(
            sku={"name": "Standard_LRS"}, kind="StorageV2",
            properties={
                "allowBlobPublicAccess": False,
                "minimumTlsVersion": "TLS1_2",
                "supportsHttpsTrafficOnly": True,
                "publicNetworkAccess": "Disabled",
            },
        )
        if spec.public_endpoint:
            payload["properties"].update(
                publicNetworkAccess="Enabled", allowSharedKeyAccess=False,
                defaultToOAuthAuthentication=True, isLocalUserEnabled=False,
                isSftpEnabled=False,
                networkAcls={
                    "defaultAction": "Allow" if entra_only else "Deny", "bypass": "None",
                    "ipRules": [
                        {"value": ip, "action": "Allow"} for ip in spec.public_endpoint.egress_ips
                    ],
                    "virtualNetworkRules": [], "resourceAccessRules": [],
                },
            )
    elif resource in ("openai_resource", "content_understanding"):
        payload.update(
            kind="OpenAI" if resource == "openai_resource" else "AIServices",
            sku={"name": "S0"},
            properties={
                "customSubDomainName": operation.name,
                "publicNetworkAccess": "Disabled",
            },
        )
        if spec.public_endpoint:
            payload["properties"].update(
                publicNetworkAccess="Enabled", disableLocalAuth=True,
                networkAcls={
                    "defaultAction": "Allow" if entra_only else "Deny", "bypass": "None",
                    "ipRules": [{"value": ip} for ip in spec.public_endpoint.egress_ips],
                    "virtualNetworkRules": [],
                },
            )
    return payload


def _verify_public_acl(resource: str, actual: Any, expected: dict) -> None:
    if _field(actual, "bypass") != "None":
        raise ProvisioningError(f"{resource}: firewall bypass must be None")
    if "defaultAction" in expected and _field(actual, "defaultAction") != expected["defaultAction"]:
        raise ProvisioningError(f"{resource}: firewall defaultAction differs")
    rules = _field(actual, "ipRules")
    if not isinstance(rules, list) or len(rules) != len(expected["ipRules"]):
        raise ProvisioningError(f"{resource}: firewall ipRules differ")
    if sorted(rules, key=lambda rule: _field(rule, "value", "")) != sorted(
        expected["ipRules"], key=lambda rule: rule["value"]
    ):
        raise ProvisioningError(f"{resource}: firewall ipRules differ")
    for key in ("virtualNetworkRules", "resourceAccessRules"):
        if key in expected and _field(actual, key, []) != []:
            raise ProvisioningError(f"{resource}: unexpected {key} bypass")


class _TenantBoundCredential:
    def __init__(self, credential: Any, tenant_id: str,
                 principal_object_id: str | None = None) -> None:
        self.credential = credential
        self.tenant_id = tenant_id
        self.principal_object_id = principal_object_id

    def get_token(self, *scopes: str, **kwargs: Any) -> Any:
        if kwargs.get("tenant_id") not in (None, self.tenant_id):
            raise ProvisioningError("Azure SDK requested a different tenant")
        token = self.credential.get_token(*scopes, **{**kwargs, "tenant_id": self.tenant_id})
        try:
            parsed = claims(token.token)
        except IdentityError as error:
            raise ProvisioningError("cannot validate Azure credential tenant") from error
        if str(parsed.get("tid", "")).lower() != self.tenant_id.lower():
            raise ProvisioningError("Azure credential is not from the approved tenant")
        if self.principal_object_id and str(parsed.get("oid", "")).lower() != (
            self.principal_object_id.lower()
        ):
            raise ProvisioningError("Azure SDK principal differs from the active az identity")
        return token


def _access_evidence(spec: ProvisioningSpec, operation: Operation, observed: Any,
                     actual_id: str, identity_principal: str | None) -> dict:
    properties = _field(observed, "properties", {}) or {}
    if operation.resource == "blob_container":
        if _field(properties, "publicAccess", "None") not in ("None", None):
            raise ProvisioningError(f"{operation.id}: container allows public access")
        return {"resource_id": actual_id, "public_access": "None"}
    if operation.resource == "search_identity":
        if not _same_location(_field(observed, "location"), spec.target.location):
            raise ProvisioningError(f"{operation.id}: location differs from requested location")
        principal = _field(properties, "principalId")
        if not isinstance(principal, str) or not principal:
            raise ProvisioningError(f"{operation.id}: managed identity has no principal ID")
        return {"resource_id": actual_id, "location": _field(observed, "location"),
                "principal_id": principal, "client_id": _field(properties, "clientId")}
    _, role, kind = access.grant(operation.id)
    expected_principal = access.principal_for(spec, operation.id, identity_principal)
    role_definition = str(_field(properties, "roleDefinitionId", ""))
    if not role_definition.lower().endswith(access.ROLE_IDS[role]):
        raise ProvisioningError(f"{operation.id}: role assignment has a different role")
    if str(_field(properties, "scope", "")).lower() != access.scope(spec, kind).lower():
        raise ProvisioningError(f"{operation.id}: role assignment has a different scope")
    principal = _field(properties, "principalId")
    if expected_principal and str(principal).lower() != expected_principal.lower():
        raise ProvisioningError(f"{operation.id}: role assignment has a different principal")
    return {"resource_id": actual_id, "role": role, "principal_id": principal,
            "scope": access.scope(spec, kind)}


def _search_identity_ok(spec: ProvisioningSpec, identity: Any) -> bool:
    kind = str(_field(identity, "type", ""))
    if not spec.build_access:
        return kind == "SystemAssigned"
    attached = {str(key).lower() for key in (_field(identity, "userAssignedIdentities") or {})}
    return (kind.replace(" ", "").lower() == "systemassigned,userassigned"
            and access.identity_id(spec).lower() in attached)


def _evidence(spec: ProvisioningSpec, operation: Operation, observed: Any, *,
              identity_principal: str | None = None) -> dict:
    resource = operation.resource
    if resource in NETWORK_API:
        return network_evidence(spec, operation, observed)
    resource_id = _resource_id(spec, operation)
    actual_id = _field(observed, "id")
    if not isinstance(actual_id, str) or actual_id.lower() != resource_id.lower():
        raise ProvisioningError(f"{operation.id}: Azure returned an unexpected resource ID")
    if resource == "model_deployment":
        return _deployment_evidence(spec, operation, observed, actual_id)
    if resource in _ACCESS:
        return _access_evidence(spec, operation, observed, actual_id, identity_principal)
    location = _field(observed, "location")
    if not _same_location(location, spec.target.location):
        raise ProvisioningError(f"{operation.id}: location differs from requested location")
    evidence = {"resource_id": actual_id, "location": location}
    if spec.public_endpoint:
        tags = _field(observed, "tags", {})
        if any(_field(tags, key) != value for key, value in _public_tags(spec).items()):
            raise ProvisioningError(f"{operation.id}: public endpoint plan/expiry tags differ")
    if resource == "resource_group":
        return evidence
    desired = _desired(spec, operation)
    actual_sku = _field(_field(observed, "sku"), "name")
    if str(actual_sku).lower() != desired["sku"]["name"].lower():
        raise ProvisioningError(f"{operation.id}: SKU differs from requested SKU")
    if "kind" in desired and str(_field(observed, "kind")).lower() != desired["kind"].lower():
        raise ProvisioningError(f"{operation.id}: resource kind differs from requested kind")
    properties = _field(observed, "properties", {})
    if resource == "storage_account":
        for key, expected in desired["properties"].items():
            if key == "networkAcls":
                _verify_public_acl(operation.id, _field(properties, key), expected)
                continue
            if _field(properties, key) != expected:
                raise ProvisioningError(f"{operation.id}: {key} differs from requested setting")
        endpoint = _field(_field(properties, "primaryEndpoints", {}), "blob")
    elif resource == "search_service":
        if not _search_identity_ok(spec, _field(observed, "identity")):
            raise ProvisioningError(
                f"{operation.id}: system-assigned identity"
                + (" and the attached Search identity are" if spec.build_access else " is")
                + " required")
        for key, expected in desired["properties"].items():
            if key == "networkRuleSet":
                _verify_public_acl(operation.id, _field(properties, key), expected)
                continue
            if _field(properties, key) != expected:
                raise ProvisioningError(f"{operation.id}: {key} differs from requested setting")
        endpoint = f"https://{operation.name}.search.windows.net"
    else:
        for key, expected in desired["properties"].items():
            if key == "networkAcls":
                _verify_public_acl(operation.id, _field(properties, key), expected)
                continue
            if _field(properties, key) != expected:
                raise ProvisioningError(f"{operation.id}: {key} differs from requested setting")
        endpoint = _field(properties, "endpoint")
    state = _field(properties, "provisioningState")
    if not isinstance(state, str) or state.lower() != "succeeded":
        raise ProvisioningError(f"{operation.id}: provisioning state is {state!r}, not Succeeded")
    if not isinstance(endpoint, str) or not endpoint.startswith("https://"):
        raise ProvisioningError(f"{operation.id}: HTTPS endpoint is unavailable")
    evidence.update(
        endpoint=endpoint, provisioning_state=state,
        public_network_access=_field(properties, "publicNetworkAccess"),
    )
    if resource == "search_service":
        evidence["sku"] = actual_sku
    if spec.public_endpoint:
        evidence["auth_posture"] = spec.public_endpoint.mode
        if spec.public_data:
            evidence["data_policy"] = "public_data_only"
    return evidence


def _deployment_evidence(spec: ProvisioningSpec, operation: Operation, observed: Any,
                         actual_id: str) -> dict:
    desired = _deployment(spec, operation)
    sku = _field(observed, "sku")
    properties = _field(observed, "properties", {})
    model = _field(properties, "model", {})
    if str(_field(sku, "name")).lower() != desired.sku.lower():
        raise ProvisioningError(f"{operation.id}: SKU differs from requested SKU")
    if _field(sku, "capacity") != desired.capacity:
        raise ProvisioningError(
            f"{operation.id}: capacity is {_field(sku, 'capacity')}K TPM, not "
            f"{desired.capacity}K; review with `ekg-provision plan-capacity` instead of re-provisioning"
        )
    if (_field(model, "name"), str(_field(model, "version"))) != (desired.model, desired.version):
        raise ProvisioningError(f"{operation.id}: model or version differs from requested")
    state = _field(properties, "provisioningState")
    if not isinstance(state, str) or state.lower() != "succeeded":
        raise ProvisioningError(f"{operation.id}: provisioning state is {state!r}, not Succeeded")
    return {"resource_id": actual_id, "sku": desired.sku, "capacity": desired.capacity,
            "model": f"{desired.model}@{desired.version}", "provisioning_state": state}


def read_subscription_permissions(spec: ProvisioningSpec) -> dict:
    """Read-only: the signed-in identity's effective actions on the subscription."""
    return az_json(["rest", "--method", "get", "--url",
                    f"https://management.azure.com/subscriptions/{spec.target.subscription_id}"
                    "/providers/Microsoft.Authorization/permissions?api-version=2022-04-01"])


class AzureSdkBackend:
    """ARM resource-group and generic-resource client; never updates existing resources."""

    def __init__(
        self, credential: Any = None, *, client: Any = None,
        journal_root: str | Path | None = None, expected_tenant_id: str | None = None,
        quota_reader: Callable[[ProvisioningSpec], dict] | None = None,
        permission_reader: Callable[[ProvisioningSpec], dict] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.credential = credential
        self.quota_reader = quota_reader or read_regional_quota
        self.permission_reader = permission_reader or read_subscription_permissions
        self._sleep = sleep
        self._principal_object_id: str | None = None
        self._principal_type: str | None = None
        self._quota: dict[str, Any] = {}
        self.expected_tenant_id = expected_tenant_id
        self._injected_client = client
        self._sdk_client: Any = None
        self._sdk_credential: Any = None
        self._client_subscription: str | None = None
        self._client_tenant: str | None = None
        self._client_public_data: bool | None = None
        self.journal = ProvisioningJournal(
            journal_root if journal_root is not None else Path.cwd() / ".ekg" / "provision-runs"
        )
        self.last_run_id: str | None = None

    def _client(self, spec: ProvisioningSpec) -> Any:
        if self._injected_client is not None:
            return self._injected_client
        tenant = spec.public_endpoint.tenant_id if spec.public_endpoint else self.expected_tenant_id
        if not tenant or (self.expected_tenant_id and self.expected_tenant_id != tenant):
            raise ProvisioningError("an explicit matching tenant ID is required for live Azure access")
        public_data = spec.public_data is not None
        if (self._client_subscription != spec.target.subscription_id
                or self._client_tenant != tenant or self._client_public_data != public_data):
            try:
                from azure.identity import AzureCliCredential
                try:
                    from azure.mgmt.resource.resources import ResourceManagementClient
                except ImportError:
                    from azure.mgmt.resource import ResourceManagementClient
            except ImportError as error:
                raise RuntimeError(
                    "Azure SDK backend requires the optional provision dependencies"
                ) from error
            identity = active_az_identity(tenant, spec.target.subscription_id)
            self._principal_object_id = identity["principal_object_id"]
            self._principal_type = identity["principal_type"]
            credential = self.credential if self.credential is not None else AzureCliCredential(
                tenant_id=tenant
            )
            credential = _TenantBoundCredential(
                credential, tenant, identity["principal_object_id"]
            )
            credential.get_token("https://management.azure.com/.default")
            self._sdk_credential = credential
            self._sdk_client = ResourceManagementClient(
                credential, spec.target.subscription_id,
                **({"retry_total": 0} if spec.public_data else {}),
            )
            self._client_subscription = spec.target.subscription_id
            self._client_tenant = tenant
            self._client_public_data = public_data
        return self._sdk_client

    def _get(self, client: Any, spec: ProvisioningSpec, operation: Operation) -> Any | None:
        try:
            if operation.resource == "resource_group":
                return client.resource_groups.get(operation.name)
            return client.resources.get_by_id(
                _resource_id(spec, operation),
                api_version=(NETWORK_API if operation.resource in NETWORK_API
                             else _READ_API_VERSIONS)[operation.resource],
            )
        except Exception as error:
            if getattr(error, "status_code", None) == 404:
                return None
            raise

    def inspect(self, spec: ProvisioningSpec) -> dict:
        _validate(spec, require_active=False)
        client = self._client(spec)
        resource_group = Operation(
            "create-resource-group", "provision", "ensure", "resource_group",
            spec.target.resource_group or "",
        )
        operations = (resource_group, *(
            operation for operation in plan(spec, require_active=False).operations
            if operation.resource != "resource_group"
        ))
        group = self._get(client, spec, resource_group)
        resources = {}
        identity_principal = None
        for operation in operations:
            observed = group if operation.resource == "resource_group" else (
                self._get(client, spec, operation) if group is not None else None
            )
            if observed is not None:
                evidence = _evidence(spec, operation, observed,
                                     identity_principal=identity_principal)
                if operation.resource == "search_identity":
                    identity_principal = evidence["principal_id"]
            resources[operation.id] = (
                {"status": "present", **evidence}
                if observed is not None else
                {"status": "missing", "resource_id": _resource_id(spec, operation)}
            )
        result = {"plan_id": plan(spec, require_active=False).plan_id, "resources": resources}
        tenant = self._client_tenant or (
            spec.public_endpoint.tenant_id if spec.public_endpoint else self.expected_tenant_id
        )
        if tenant:
            result["tenant_id"] = tenant
        return result

    def verify(self, spec: ProvisioningSpec) -> dict:
        result = self.inspect(spec)
        missing = [key for key, value in result["resources"].items() if value["status"] == "missing"]
        if missing:
            raise ProvisioningError(f"verification failed; missing: {', '.join(missing)}")
        return {"status": "verified", **result}

    def apply(self, spec: ProvisioningSpec, *, approved_plan_id: str,
              confirmed_public_test: bool = False, confirmed_public_data: bool = False) -> ApplyResult:
        if spec.public_endpoint is None:
            raise ProvisioningError(
                "live provisioning apply is disabled pending a separately approved deployment decision"
            )
        if not (confirmed_public_data if spec.public_data else confirmed_public_test):
            raise ApprovalRequired("public provisioning requires explicit billable deployment confirmation")
        _validate(spec)
        desired_plan = plan(spec)
        if not approved_plan_id or approved_plan_id != desired_plan.plan_id:
            raise ApprovalRequired(f"explicit approval of plan {desired_plan.plan_id} is required")
        if self._injected_client is None:
            self._client(spec)
            self._sdk_credential.get_token("https://management.azure.com/.default")
            access_spec = spec.build_access
            if spec.public_data and access_spec and (
                (self._principal_object_id or "").lower() != access_spec.operator_object_id.lower()
                or self._principal_type != access_spec.operator_principal_type
            ):
                raise ProvisioningError("public-data operator must match the active Azure CLI principal and type")
            if (access_spec and access_spec.operator_principal_type == "User"
                    and (self._principal_object_id or "").lower()
                    != access_spec.operator_object_id.lower()):
                raise ProvisioningError(
                    "the operator object ID is not the signed-in Azure CLI user; "
                    "use `az ad signed-in-user show --query id -o tsv`")
        return self._apply_approved(spec, approved_plan_id=approved_plan_id,
                                    allow_live=True)

    def _resume_state(
        self, spec: ProvisioningSpec, source_run_id: str,
        *, created: tuple[str, ...] = (),
    ) -> tuple[dict[str, Any], dict[str, Any], str]:
        _validate(spec)
        if spec.public_test is None or spec.network is not None:
            raise ProvisioningError("resume requires the original active public-test spec")
        source_path = self.journal.path(source_run_id)
        source_bytes = source_path.read_bytes()
        source = json.loads(source_bytes)
        original = plan(spec)
        operations = {operation.id: operation for operation in original.operations}
        if (source.get("version") != 1 or source.get("run_id") != source_run_id
            or source.get("plan_id") != original.plan_id
            or source.get("spec") != json.loads(json.dumps(journal_spec(spec)))
            or source.get("completed") is not False
            or set(source.get("operations", {})) != set(operations)):
            raise ProvisioningError("original journal is not the exact incomplete public-test run")
        expected_status = {
            "create-resource-group": "create_response_verified",
            "create-search_service": "uncertain",
            "create-storage_account": "pending",
            "create-openai_resource": "pending",
        }
        if any(
            source["operations"][key].get("status") != status
            or source["operations"][key].get("preflight") != "missing"
            or source["operations"][key].get("resource_id") != _resource_id(spec, operations[key])
            for key, status in expected_status.items()
        ):
            raise ProvisioningError("original journal has a different operation outcome")
        client = self._client(spec)
        inspection = self.inspect(spec)
        expected_present = {"create-resource-group", "create-search_service", *created}
        if any(
            value["status"] != ("present" if key in expected_present else "missing")
            for key, value in inspection["resources"].items()
        ):
            raise ProvisioningError("resume requires exactly the expected present and missing services")
        group = self._get(client, spec, operations["create-resource-group"])
        search = self._get(client, spec, operations["create-search_service"])
        if group is None or search is None:
            raise ProvisioningError("resume source resources disappeared")
        for key, observed in (("create-resource-group", group), ("create-search_service", search)):
            _evidence(spec, operations[key], observed)

        def raw(value: Any) -> Any:
            return value if isinstance(value, dict) else value.as_dict()

        identity = raw(_field(search, "identity"))
        if (not isinstance(_field(identity, "principalId"), str)
            or not _field(identity, "principalId")
            or str(_field(identity, "tenantId", "")).lower() != spec.public_test.tenant_id.lower()):
            raise ProvisioningError("Search system identity lacks the expected tenant and principal")
        allowed_ids = {
            _resource_id(spec, operations[key]).lower()
            for key in expected_present if key != "create-resource-group"
        }
        actual_ids = [
            _field(item, "id", "").lower()
            for item in client.resources.list_by_resource_group(spec.target.resource_group)
        ]
        if len(actual_ids) != len(allowed_ids) or set(actual_ids) != allowed_ids:
            raise ProvisioningError("resource group contains unexpected or missing resources")

        snapshot = {
            "source_journal_sha256": hashlib.sha256(source_bytes).hexdigest(),
            "resource_ids": [_resource_id(
                spec, operations["create-search_service"]
            ).lower()],
            "resource_group": raw(group),
            "search_service": raw(search),
        }
        snapshot_hash = hashlib.sha256(json.dumps(
            snapshot, sort_keys=True, separators=(",", ":"), default=str,
        ).encode("utf-8")).hexdigest()
        return inspection, source, snapshot_hash

    def resume_plan(self, spec: ProvisioningSpec, source_run_id: str) -> dict[str, Any]:
        inspection, source, snapshot_hash = self._resume_state(spec, source_run_id)
        original = plan(spec)
        operations = tuple(operation for operation in original.operations if operation.id in (
            "create-storage_account", "create-openai_resource",
        ))
        resume_id = stable_id("public-resume-plan", {
            "source_run_id": source_run_id,
            "source_plan_id": source["plan_id"],
            "snapshot_sha256": snapshot_hash,
            "operations": operations,
        })
        return {
            "plan_id": resume_id, "source_run_id": source_run_id,
            "source_plan_id": source["plan_id"],
            "snapshot_sha256": snapshot_hash,
            "source_resource_ids": [
                inspection["resources"][key]["resource_id"]
                for key in ("create-resource-group", "create-search_service")
            ],
            "operations": [asdict(operation) for operation in operations],
            "warnings": [
                "New approval required: create only Storage and OpenAI; never recreate RG/Search.",
                "The original journal remains uncertain and immutable; cleanup remains manual-only.",
            ],
        }

    def resume_apply(
        self, spec: ProvisioningSpec, source_run_id: str, *,
        approved_plan_id: str, confirmed_public_test: bool,
    ) -> ApplyResult:
        if not confirmed_public_test:
            raise ApprovalRequired("resume requires explicit billable deployment confirmation")
        review = self.resume_plan(spec, source_run_id)
        if not approved_plan_id or approved_plan_id != review["plan_id"]:
            raise ApprovalRequired(f"explicit approval of resume plan {review['plan_id']} is required")
        inspection, _, fresh_hash = self._resume_state(spec, source_run_id)
        if fresh_hash != review["snapshot_sha256"]:
            raise ProvisioningError("resume snapshot changed; a new plan and approval are required")
        desired = Plan(
            plan_id=review["plan_id"],
            operations=tuple(operation for operation in plan(spec).operations if operation.id in (
                "create-storage_account", "create-openai_resource",
            )),
        )
        run_id = self.journal.begin(spec, desired, inspection, resume_from={
            "source_run_id": source_run_id,
            "source_plan_id": review["source_plan_id"],
            "snapshot_sha256": review["snapshot_sha256"],
        })
        self.last_run_id = run_id
        created: list[str] = []

        def execute(operation: Operation) -> dict:
            _, _, current_hash = self._resume_state(spec, source_run_id, created=tuple(created))
            if current_hash != review["snapshot_sha256"]:
                raise ProvisioningError("resume source snapshot changed before write")
            evidence = self._execute_operation(
                spec, operation, run_id, desired.plan_id, require_missing=True,
            )
            created.append(operation.id)
            _, _, current_hash = self._resume_state(spec, source_run_id, created=tuple(created))
            if current_hash != review["snapshot_sha256"]:
                raise ProvisioningError("resume source snapshot changed after write")
            return evidence

        result = apply_plan(desired, approved=True, executor=execute)
        self.journal.finish(run_id, result.completed)
        return result

    def _execute_operation(
        self, spec: ProvisioningSpec, operation: Operation, run_id: str, plan_id: str,
        *, require_missing: bool = False,
    ) -> dict[str, Any]:
        recorder = TelemetryRecorder("provision")
        outcome: dict[str, Any] = {}
        try:
            with recorder.span(operation.id, resource=operation.resource):
                outcome = self._execute_operation_untimed(
                    spec, operation, run_id, plan_id, require_missing=require_missing,
                )
        finally:
            event = recorder.events[-1] if recorder.events else None
            if event is not None:
                event["counts"] = {"created": int(outcome.get("change") == "created")}
                try:
                    self.journal.record_telemetry(run_id, event)
                except (OSError, ValueError):
                    pass
        return outcome

    def _execute_operation_untimed(
        self, spec: ProvisioningSpec, operation: Operation, run_id: str, plan_id: str,
        *, require_missing: bool = False,
    ) -> dict[str, Any]:
        client = self._client(spec)
        attempted = False
        try:
            _validate(spec)
            observed = self._get(client, spec, operation)
            if require_missing and observed is not None:
                raise ProvisioningError(
                    f"{operation.id}: resource appeared after "
                    + ("preflight" if spec.public_data else "resume preflight")
                    + "; no update permitted"
                )
            created = observed is None
            if created and operation.resource == "model_deployment":
                self._quota_gate(spec, (_deployment(spec, operation),))
            identity_principal = self._identity_principal(client, spec, operation)
            if created:
                self.journal.update(run_id, operation.id, "uncertain",
                                    reason="create attempted; outcome not confirmed")
                attempted = True
                if operation.resource == "resource_group":
                    payload = {"location": spec.target.location}
                    if spec.public_endpoint:
                        payload["tags"] = _public_tags(spec)
                    if spec.network:
                        payload["tags"] = {"ekg-run-id": run_id, "ekg-plan-id": plan_id}
                    observed = client.resource_groups.create_or_update(
                        operation.name, payload,
                        headers={"If-None-Match": "*"},
                    )
                else:
                    payload = (
                        network_desired(spec, operation, run_id=run_id,
                                        plan_id=plan_id)
                        if operation.resource in NETWORK_API else
                        _desired(spec, operation, identity_principal=identity_principal)
                    )
                    observed = client.resources.begin_create_or_update_by_id(
                        _resource_id(spec, operation),
                        payload,
                        api_version=(NETWORK_API if operation.resource in NETWORK_API
                                     else _API_VERSIONS)[operation.resource],
                        # Role assignments reject If-None-Match; their name is deterministic.
                        **({} if operation.resource == "role_assignment"
                           else {"headers": {"If-None-Match": "*"}}),
                        # Identity, container and role PUTs complete synchronously. SDK
                        # polling after the identity's 201 sent a request without
                        # api-version; the reread below is the authoritative check.
                        **({"polling": False} if operation.resource in _ACCESS else {}),
                    ).result()
            # Cognitive Services' create API can omit networkAcls.bypass even
            # though the authoritative read API returns the persisted value.
            # Validate newly created accounts from the required post-create
            # reread instead of treating that incomplete create response as drift.
            if not (created and operation.resource == "openai_resource"):
                _evidence(spec, operation, observed, identity_principal=identity_principal)
            verified = self._get(client, spec, operation)
            for _ in range(6 if operation.resource == "role_assignment" else 0):
                if verified is not None:
                    break
                # New role assignments can take a few seconds to become readable.
                self._sleep(5)
                verified = self._get(client, spec, operation)
            if verified is None:
                raise ProvisioningError(f"{operation.id}: resource missing after apply")
            evidence = _evidence(spec, operation, verified, identity_principal=identity_principal)
            if created and spec.network and (
                operation.resource in ("resource_group", "vnet", "zone", "zone_link", "endpoint")
            ):
                expected_tags = {"ekg-run-id": run_id, "ekg-plan-id": plan_id}
                if any(_field(_field(verified, "tags", {}), key) != value
                       for key, value in expected_tags.items()):
                    raise ProvisioningError(f"{operation.id}: run/plan tags missing after create")
            etag = _field(verified, "etag")
            if isinstance(etag, str):
                evidence["etag"] = etag
            if operation.resource == "model_deployment" and operation.name in self._quota:
                evidence["quota_preflight"] = self._quota[operation.name]
            self.journal.update(
                run_id, operation.id,
                "create_response_verified" if created else "existing",
                evidence=evidence,
            )
            return {**evidence, "change": "created" if created else "existing"}
        except Exception as error:
            try:
                self.journal.update(
                    run_id, operation.id, "uncertain" if attempted else "failed",
                    reason=f"{type(error).__name__}: {error}",
                )
            except Exception as journal_error:
                raise ProvisioningError(
                    f"{operation.id}: {error}; journal update failed: {journal_error}"
                ) from journal_error
            raise

    def _identity_principal(self, client: Any, spec: ProvisioningSpec,
                            operation: Operation) -> str | None:
        if operation.resource != "role_assignment":
            return None
        if access.grant(operation.id)[0] != "search_identity":
            return None
        identity = self._get(client, spec, Operation(
            "create-search-identity", "provision", "ensure", "search_identity",
            spec.build_access.search_identity_name if spec.build_access else "",
        ))
        principal = _field(_field(identity, "properties", {}) or {}, "principalId")
        if not isinstance(principal, str) or not principal:
            raise ProvisioningError(f"{operation.id}: the Search identity has no principal ID yet")
        return principal

    def _permission_gate(self, spec: ProvisioningSpec) -> None:
        try:
            permissions = self.permission_reader(spec)
        except Exception as error:
            raise ProvisioningError(f"role permission check failed: {error}") from error
        if not access.can_assign_roles(permissions):
            raise ProvisioningError(
                "you can't assign roles in this subscription, so setup would stop halfway. "
                "Next step: ask for Owner or Role Based Access Control Administrator on the "
                "subscription, then rerun apply with the same plan.")

    def _quota_gate(self, spec: ProvisioningSpec,
                    deployments: tuple[ModelDeploymentSpec, ...]) -> None:
        try:
            quota = self.quota_reader(spec)
        except Exception as error:
            raise ProvisioningError(f"quota preflight failed: {error}") from error
        report = quota_preflight(spec, quota, deployments=deployments)
        for row in report["deployments"]:
            self._quota[row["deployment"]] = {
                key: row[key] for key in ("quota_name", "quota_current_k_tpm",
                                          "quota_limit_k_tpm", "requested_capacity_k_tpm")
            }
        if report["blocked"]:
            raise ProvisioningError("quota preflight blocked: " + "; ".join(
                blocker for row in report["deployments"] for blocker in row["blockers"]
            ))

    def _apply_approved(self, spec: ProvisioningSpec, *, approved_plan_id: str,
                        allow_live: bool = False) -> ApplyResult:
        """Guarded execution path; only bounded public modes may use live clients."""
        if self._injected_client is None and not (allow_live and spec.public_endpoint):
            raise ProvisioningError("the internal execution path requires an injected test client")
        _validate(spec)
        desired_plan = plan(spec)
        if not approved_plan_id or approved_plan_id != desired_plan.plan_id:
            raise ApprovalRequired(
                f"explicit approval of plan {desired_plan.plan_id} is required"
            )
        inspection = self.inspect(spec)
        if spec.public_endpoint and inspection["resources"]["create-resource-group"]["status"] != "missing":
            raise ProvisioningError("public test/public-data requires an absent isolated resource group")
        if inspection["resources"]["create-resource-group"]["status"] == "missing" and not spec.create_resource_group:
            raise ProvisioningError("resource group is missing; approve a plan with create_resource_group")
        missing_deployments = tuple(
            deployment for deployment in spec.model_deployments
            if inspection["resources"][f"create-{deployment.role}-deployment"]["status"] == "missing"
        )
        if missing_deployments:
            # Read-only quota gate before any write in this run.
            self._quota_gate(spec, missing_deployments)
        if spec.build_access is not None:
            # Read-only role-write check before any write in this run.
            self._permission_gate(spec)
        run_id = self.journal.begin(spec, desired_plan, inspection)
        self.last_run_id = run_id

        def execute(operation: Operation) -> dict:
            return self._execute_operation(
                spec, operation, run_id, desired_plan.plan_id,
                require_missing=spec.public_data is not None,
            )

        result = apply_plan(desired_plan, approved=True, executor=execute)
        self.journal.finish(run_id, result.completed)
        return result
