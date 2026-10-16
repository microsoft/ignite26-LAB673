import re
import subprocess
from dataclasses import dataclass
from typing import Any, Callable
from ..capacity import API_VERSION as OPENAI_API_VERSION
from ekg_core.az_identity import IdentityError, az_json
ARM = "https://management.azure.com"
DEFAULT_RUNNER: Callable[..., Any] = subprocess.run
SEARCH_DATA_API_VERSION = "2024-07-01"
_TYPES = {"search": ("Microsoft.Search/searchServices", "2025-05-01"), "storage": ("Microsoft.Storage/storageAccounts", "2023-05-01"), "openai": ("Microsoft.CognitiveServices/accounts", OPENAI_API_VERSION), "identity": ("Microsoft.ManagedIdentity/userAssignedIdentities", "2023-01-31")}
_ID = re.compile(r"/subscriptions/([^/]+)/resourceGroups/([^/]+)/providers/"
                 r"([^/]+/[^/]+)/([^/]+)", re.IGNORECASE)
ACCEPTED_ROLES = {
    "Search Service Contributor": ("Search Service Contributor", "Contributor", "Owner"),
    "Search Index Data Contributor": ("Search Index Data Contributor",),
    "Storage Blob Data Contributor": ("Storage Blob Data Contributor", "Storage Blob Data Owner"),
    "Storage Blob Data Reader": ("Storage Blob Data Reader", "Storage Blob Data Contributor",
                                 "Storage Blob Data Owner"),
}
EMBEDDING_DIMENSIONS = {"text-embedding-3-small": 1536, "text-embedding-3-large": 3072, "text-embedding-ada-002": 1536}
UNVERIFIED_ROLE = ("No direct or inherited assignment to this principal was found. Group, "
                   "PIM-eligible and conditional grants are not inferred.")
class ConnectError(RuntimeError):
    pass
@dataclass(frozen=True)
class ConnectSpec:
    tenant_id: str
    subscription_id: str
    resource_group: str | None = None
    search: str | None = None
    storage: str | None = None
    openai: str | None = None
    storage_container: str | None = None
    embedding_deployment: str | None = None
    chat_deployment: str | None = None
    search_identity_resource_id: str | None = None
    embedding_dimensions: int | None = None
    documents: int | None = None
    def __post_init__(self) -> None:
        guid = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
        for value in (self.tenant_id, self.subscription_id):
            if not isinstance(value, str) or not re.fullmatch(guid, value):
                raise ValueError("connect needs explicit tenant and subscription GUIDs")
        for key in ("embedding_dimensions", "documents"):
            value = getattr(self, key)
            if value is not None and (not isinstance(value, int) or isinstance(value, bool)
                                      or value < 1):
                raise ValueError(f"{key} must be a positive integer")
def _check(checks: list[dict[str, Any]], check_id: str, status: str, detail: str,
           **evidence: Any) -> None:
    checks.append({"id": check_id, "status": status, "detail": detail,
                   **({"evidence": evidence} if evidence else {})})
def _resource_id(spec: ConnectSpec, kind: str, value: str | None) -> str | None:
    if value is None:
        return None
    provider = _TYPES[kind][0]
    match = _ID.fullmatch(value)
    if match:
        if match.group(1).lower() != spec.subscription_id.lower():
            raise ValueError(f"{kind} resource ID is in a different subscription")
        if match.group(3).lower() != provider.lower():
            raise ValueError(f"{kind} resource ID must be a {provider}")
        return value
    if "/" in value:
        raise ValueError(f"{kind} must be a resource name or an exact ARM resource ID")
    if not spec.resource_group:
        raise ValueError(f"--resource-group is required to resolve {kind} name {value}")
    return (f"/subscriptions/{spec.subscription_id}/resourceGroups/{spec.resource_group}"
            f"/providers/{provider}/{value}")
def _region(value: Any) -> str | None:
    """ARM returns display names for some services (``East US 2``); Build uses ``eastus2``."""
    return str(value).replace(" ", "").lower() if value else None
def _canonical(resource_id: str) -> str:
    """ARM may return lowercase segment names (``resourcegroups``); Build needs one form."""
    match = _ID.fullmatch(resource_id)
    if not match:
        return resource_id
    return (f"/subscriptions/{match.group(1)}/resourceGroups/{match.group(2)}/providers/"
            f"{match.group(3)}/{match.group(4)}")
def _parts(resource_id: str) -> tuple[str, str]:
    match = _ID.fullmatch(resource_id)
    assert match is not None
    return match.group(2), match.group(4)
def _show(resource_id: str, kind: str, runner: Callable[..., Any]) -> dict[str, Any] | None:
    try:
        observed = az_json(["resource", "show", "--ids", resource_id,
                            "--api-version", _TYPES[kind][1]], runner=runner)
    except IdentityError:
        return None
    if not isinstance(observed, dict) or str(observed.get("id", "")).lower() != resource_id.lower():
        return None
    return observed
def _get(url: str, runner: Callable[..., Any], resource: str | None = None) -> Any:
    args = ["rest", "--method", "get", "--url", url]
    return az_json(args + (["--resource", resource] if resource else []), runner=runner)
def _candidates(spec: ConnectSpec, kind: str, runner: Callable[..., Any]) -> list[dict[str, Any]]:
    args = ["resource", "list", "--resource-type", _TYPES[kind][0],
            "--subscription", spec.subscription_id]
    if spec.resource_group:
        args += ["--resource-group", spec.resource_group]
    try:
        listed = az_json(args, runner=runner)
    except IdentityError:
        return []
    return [{"name": item.get("name"), "resource_id": item.get("id"),
             "location": item.get("location"), "kind": item.get("kind"),
             "sku": (item.get("sku") or {}).get("name")}
            for item in listed or [] if isinstance(item, dict)]
def _props(observed: dict[str, Any] | None) -> dict[str, Any]:
    return (observed or {}).get("properties") or {}
def _network(checks: list[dict[str, Any]], kind: str, props: dict[str, Any],
             reach: str) -> dict[str, Any]:
    acls = props.get("networkAcls") or props.get("networkRuleSet") or {}
    public = props.get("publicNetworkAccess")
    summary = {"public_network_access": public, "default_action": acls.get("defaultAction"),
               "bypass": acls.get("bypass"), "ip_rules": len(acls.get("ipRules") or []),
               "private_endpoints": len(props.get("privateEndpointConnections") or [])}
    if str(public).lower() == "disabled":
        _check(checks, f"{kind}.network", "warn",
               f"Public network access is disabled. {reach} needs private connectivity "
               "(private endpoint or shared private link); verify it separately.", **summary)
    elif str(acls.get("defaultAction", "")).lower() == "deny" or summary["ip_rules"]:
        _check(checks, f"{kind}.network", "warn",
               f"A network firewall is on. {reach} must be allowed by an IP, trusted-service "
               "or resource-instance rule; the data-plane probe checks this host only.",
               **summary)
    else:
        _check(checks, f"{kind}.network", "ok", "Public network access is enabled.", **summary)
    return summary
