from dataclasses import asdict
from typing import Any
from ekg_core.models import ProvisioningSpec, Target
from .spec import ConnectSpec, _parts
def _binding(spec: ConnectSpec, ids: dict[str, str], search: dict, storage: dict, openai: dict,
             uai: dict[str, Any], dimensions: int) -> dict[str, Any]:
    rows = openai["deployments"]
    group = _parts(ids["search"])[0]
    target = Target(
        subscription_id=spec.subscription_id, resource_group=group,
        location=search["location"], search_endpoint=search["endpoint"],
        storage_endpoint=storage["endpoint"], openai_endpoint=openai["endpoint"],
        search_resource_id=ids["search"], storage_resource_id=ids["storage"],
        openai_resource_id=ids["openai"],
    )
    binding = {
        "target": asdict(target), "tenant_id": spec.tenant_id, "search_sku": search["sku"],
        "search_identity_resource_id": uai["resource_id"],
        "storage_container": spec.storage_container,
        "embedding_deployment": rows["embedding"]["name"],
        "embedding_model": rows["embedding"]["model"], "embedding_dimensions": dimensions,
        "chat_deployment": rows["chat"]["name"], "chat_model": rows["chat"]["model"],
    }
    flags = {
        "--tenant-id": spec.tenant_id, "--subscription-id": spec.subscription_id,
        "--resource-group": group, "--location": target.location,
        "--search-sku": search["sku"], "--search-endpoint": target.search_endpoint,
        "--storage-endpoint": target.storage_endpoint,
        "--openai-endpoint": target.openai_endpoint,
        "--search-resource-id": ids["search"], "--storage-resource-id": ids["storage"],
        "--openai-resource-id": ids["openai"],
        "--search-identity-resource-id": uai["resource_id"],
        "--storage-container": spec.storage_container,
        "--embedding-deployment": binding["embedding_deployment"],
        "--embedding-model": binding["embedding_model"],
        "--embedding-dimensions": str(dimensions),
        "--chat-deployment": binding["chat_deployment"], "--chat-model": binding["chat_model"],
    }
    binding["build_args"] = [part for pair in flags.items() for part in pair]
    return binding
def connection_spec(payload: dict[str, Any]) -> ProvisioningSpec | None:
    """The Provision-shaped spec for a complete binding, for the local journal record."""
    binding = payload.get("build_binding")
    if not binding:
        return None
    target = Target(**binding["target"])
    names = {kind: _parts(payload["resources"][kind])[1] for kind in ("search", "storage", "openai")}
    return ProvisioningSpec(
        target=target, search_name=names["search"], storage_name=names["storage"],
        openai_name=names["openai"], search_sku=binding["search_sku"],
        model_deployments=tuple(payload.get("_model_deployments") or ()),
    )
def public_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if not key.startswith("_")}
