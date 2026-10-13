from typing import Any, Callable
from ekg_core.models import MODEL_DEPLOYMENT_SKUS, BuildSpec, ModelDeploymentSpec, ProvisioningSpec, Target
from ..capacity import API_VERSION as OPENAI_API_VERSION, quota_preflight, read_regional_quota
from ekg_core.az_identity import IdentityError, az_json
from .spec import ARM, OPENAI_DATA_API_VERSION, SEARCH_DATA_API_VERSION, ConnectSpec, _TYPES, _canonical, _check, _get, _network, _parts, _props, _region, _show
def _search_state_checks(checks: list, props: dict[str, Any], sku: str) -> None:
    state_ok = (str(props.get("provisioningState", "")).lower() == "succeeded"
                and str(props.get("status", "running")).lower() == "running")
    _check(checks, "search.state", "ok" if state_ok else "fail",
           f"provisioningState {props.get('provisioningState')}, status {props.get('status')}")
    _check(checks, "search.sku", "fail" if sku.lower() == "free" else "ok",
           "The free tier has no managed identity; graph Build needs one." if sku.lower() == "free"
           else f"SKU {sku}", sku=sku)
    auth = props.get("authOptions") or {}
    if props.get("disableLocalAuth") is True:
        _check(checks, "search.local_auth", "ok", "API keys are disabled; Entra only.")
    elif "apiKeyOnly" in auth:
        _check(checks, "search.local_auth", "fail",
               "authOptions is apiKeyOnly; EKG authenticates with Entra ID. Enable aadOrApiKey.")
    else:
        _check(checks, "search.local_auth", "warn",
               "API keys are enabled alongside Entra ID; EKG uses Entra only.")
def _select_search_identity(spec: ConnectSpec, observed: dict[str, Any], checks: list,
                            selected: dict[str, Any], candidates: dict[str, Any]) -> None:
    identity = observed.get("identity") or {}
    attached = {key.lower(): (_canonical(key), value or {})
                for key, value in (identity.get("userAssignedIdentities") or {}).items()}
    wanted = spec.search_identity_resource_id
    if wanted:
        if wanted.lower() not in attached:
            _check(checks, "search.identity", "fail",
                   "The requested user-assigned identity is not attached to Search.")
        else:
            selected["search_identity"] = attached[wanted.lower()]
    elif len(attached) == 1:
        selected["search_identity"] = next(iter(attached.values()))
        _check(checks, "search.identity", "warn",
               "Selected the only user-assigned identity attached to Search; pass "
               "--search-identity-resource-id to pin it.")
    elif not attached:
        _check(checks, "search.identity", "fail",
               "Managed graph Build needs a user-assigned identity attached to Search. Connect "
               "does not attach one.")
    else:
        candidates["search_identity_resource_id"] = [key for key, _ in attached.values()]
    if "search_identity" in selected:
        key, value = selected["search_identity"]
        selected["search_identity"] = {"resource_id": key, "principal_id": value.get("principalId")}
        if not any(item["id"] == "search.identity" for item in checks):
            _check(checks, "search.identity", "ok", "User-assigned identity is attached.")
def _probe_search_data_plane(endpoint: str, checks: list, runner: Callable[..., Any]) -> None:
    try:
        listed = _get(f"{endpoint}/indexes?api-version={SEARCH_DATA_API_VERSION}&$select=name",
                      runner, "https://search.azure.com")
        _check(checks, "search.data_plane", "ok", "Listed indexes with Entra ID from this host.",
               indexes=len((listed or {}).get("value") or []))
    except IdentityError:
        _check(checks, "search.data_plane", "fail",
               "Could not list indexes from this host: network, role or auth mode.")
def _search(spec: ConnectSpec, search_id: str, checks: list, runner: Callable[..., Any],
            selected: dict[str, Any], candidates: dict[str, Any]) -> dict[str, Any] | None:
    observed = _show(search_id, "search", runner)
    if observed is None:
        _check(checks, "search.exists", "fail", "Search service is missing or unreadable.")
        return None
    props, sku = _props(observed), str((observed.get("sku") or {}).get("name") or "")
    _search_state_checks(checks, props, sku)
    _network(checks, "search", props, "The Build and Consume host")
    _select_search_identity(spec, observed, checks, selected, candidates)
    name = _parts(search_id)[1]
    endpoint = str(props.get("endpoint") or f"https://{name}.search.windows.net").rstrip("/")
    _probe_search_data_plane(endpoint, checks, runner)
    return {"observed": observed, "endpoint": endpoint, "sku": sku.lower(),
            "location": _region(observed.get("location"))}
def _storage(spec: ConnectSpec, storage_id: str, checks: list, runner: Callable[..., Any],
             candidates: dict[str, Any]) -> dict[str, Any] | None:
    observed = _show(storage_id, "storage", runner)
    if observed is None:
        _check(checks, "storage.exists", "fail", "Storage account is missing or unreadable.")
        return None
    props = _props(observed)
    _check(checks, "storage.state",
           "ok" if str(props.get("provisioningState", "")).lower() == "succeeded" else "fail",
           f"provisioningState {props.get('provisioningState')}, kind {observed.get('kind')}")
    if props.get("allowBlobPublicAccess") is True:
        _check(checks, "storage.public_blob_access", "warn",
               "Anonymous blob access is allowed on the account.")
    _check(checks, "storage.local_auth",
           "ok" if props.get("allowSharedKeyAccess") is False else "warn",
           "Shared key access is disabled." if props.get("allowSharedKeyAccess") is False
           else "Shared key access is enabled; EKG uses Entra only.")
    _network(checks, "storage", props, "The Search indexer and the Build host")
    name = _parts(storage_id)[1]
    endpoint = str(((props.get("primaryEndpoints") or {}).get("blob"))
                   or f"https://{name}.blob.core.windows.net/").rstrip("/")
    container = spec.storage_container
    if container is None:
        try:
            listed = _get(f"{ARM}{storage_id}/blobServices/default/containers"
                          f"?api-version={_TYPES['storage'][1]}", runner)
            candidates["storage_container"] = [
                item.get("name") for item in (listed or {}).get("value") or []
                if isinstance(item, dict)]
        except IdentityError:
            candidates["storage_container"] = []
        return {"observed": observed, "endpoint": endpoint}
    try:
        found = _get(f"{ARM}{storage_id}/blobServices/default/containers/{container}"
                     f"?api-version={_TYPES['storage'][1]}", runner)
    except IdentityError:
        found = None
    if not isinstance(found, dict):
        _check(checks, "storage.container", "missing",
               "Container is missing or unreadable; the setup plan creates it (private).")
        return {"observed": observed, "endpoint": endpoint, "missing_container": True}
    else:
        access = str((found.get("properties") or {}).get("publicAccess") or "None")
        _check(checks, "storage.container", "ok" if access == "None" else "fail",
               "Container is private." if access == "None"
               else f"Container publicAccess is {access}; EKG needs a private container.")
    try:
        az_json(["storage", "blob", "list", "--account-name", name, "--container-name",
                 container, "--auth-mode", "login", "--num-results", "1"], runner=runner)
        _check(checks, "storage.data_plane", "ok", "Listed blobs with Entra ID from this host.")
    except IdentityError:
        _check(checks, "storage.data_plane", "fail",
               "Could not list blobs from this host: network, role or auth mode.")
    return {"observed": observed, "endpoint": endpoint}
def _deployment_row(role: str, item: dict[str, Any]) -> dict[str, Any]:
    sku = item.get("sku") or {}
    model = _props(item).get("model") or {}
    return {"role": role, "name": item.get("name"), "model": model.get("name"),
            "version": model.get("version"), "sku": sku.get("name"),
            "capacity_k_tpm": sku.get("capacity"),
            "provisioning_state": _props(item).get("provisioningState")}
def _openai_account_checks(checks: list, observed: dict[str, Any],
                           props: dict[str, Any]) -> str:
    kind_ok = observed.get("kind") in ("OpenAI", "AIServices")
    _check(checks, "openai.state",
           "ok" if kind_ok and str(props.get("provisioningState", "")).lower() == "succeeded"
           else "fail", f"kind {observed.get('kind')}, provisioningState "
           f"{props.get('provisioningState')}")
    subdomain = props.get("customSubDomainName")
    _check(checks, "openai.subdomain", "ok" if subdomain else "fail",
           "Custom subdomain is set." if subdomain else
           "Entra ID auth needs a custom subdomain on the account.")
    _check(checks, "openai.local_auth", "ok" if props.get("disableLocalAuth") is True else "warn",
           "API keys are disabled; Entra only." if props.get("disableLocalAuth") is True
           else "API keys are enabled; EKG uses Entra only.")
    _network(checks, "openai", props, "The Search service (as caller) and the Build host")
    endpoints = props.get("endpoints") or {}
    return str(endpoints.get("OpenAI Language Model Instance API")
               or (f"https://{subdomain}.openai.azure.com/" if subdomain else
                   props.get("endpoint") or "")).rstrip("/")
def _probe_openai_data_plane(endpoint: str, checks: list, runner: Callable[..., Any]) -> None:
    if not endpoint:
        return
    try:
        _get(f"{endpoint}/openai/models?api-version={OPENAI_DATA_API_VERSION}", runner,
             "https://cognitiveservices.azure.com")
        _check(checks, "openai.data_plane", "ok", "Listed models with Entra ID from this host.")
    except IdentityError:
        _check(checks, "openai.data_plane", "fail",
               "Could not list models from this host: network, role or auth mode.")
def _openai_deployments(openai_id: str, checks: list,
                        runner: Callable[..., Any]) -> dict[str, Any]:
    try:
        listed = _get(f"{ARM}{openai_id}/deployments?api-version={OPENAI_API_VERSION}", runner)
        return {item["name"]: item for item in (listed or {}).get("value") or []
                if isinstance(item, dict) and isinstance(item.get("name"), str)}
    except IdentityError:
        _check(checks, "openai.deployments", "fail", "Could not list model deployments.")
        return {}
def _check_requested_deployment(role: str, name: str, deployed: dict[str, Any],
                                checks: list) -> dict[str, Any] | None:
    if name not in deployed:
        _check(checks, f"openai.{role}_deployment", "missing",
               f"Deployment {name} not found; the setup plan deploys it after a quota check.")
        return None
    row = _deployment_row(role, deployed[name])
    is_embedding = "embedding" in str(row["model"] or "")
    problems = []
    if str(row["provisioning_state"]).lower() != "succeeded":
        problems.append(f"state {row['provisioning_state']}")
    if is_embedding != (role == "embedding"):
        problems.append(f"model {row['model']} is not a {role} model")
    _check(checks, f"openai.{role}_deployment", "fail" if problems else "ok",
           "; ".join(problems) or f"{row['model']} {row['version']}, {row['sku']} "
           f"{row['capacity_k_tpm']}K TPM", **row)
    return row
def _deployment_rows(spec: ConnectSpec, deployed: dict[str, Any], checks: list,
                     candidates: dict[str, Any],
                     missing: dict[str, str]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for role, name in (("embedding", spec.embedding_deployment), ("chat", spec.chat_deployment)):
        if name is None:
            candidates[f"{role}_deployment"] = [
                _deployment_row(role, item) for item in deployed.values()
                if ("embedding" in str((_props(item).get("model") or {}).get("name", "")))
                == (role == "embedding")]
            continue
        row = _check_requested_deployment(role, name, deployed, checks)
        if row is not None:
            rows[role] = row
        elif deployed is not None and name not in deployed:
            missing[role] = name
    return rows
def _openai(spec: ConnectSpec, openai_id: str, checks: list, runner: Callable[..., Any],
            candidates: dict[str, Any]) -> dict[str, Any] | None:
    observed = _show(openai_id, "openai", runner)
    if observed is None:
        _check(checks, "openai.exists", "fail", "Azure OpenAI/Foundry account is missing or unreadable.")
        return None
    props = _props(observed)
    endpoint = _openai_account_checks(checks, observed, props)
    _probe_openai_data_plane(endpoint, checks, runner)
    deployed = _openai_deployments(openai_id, checks, runner)
    missing: dict[str, str] = {}
    listed = any(check["id"] == "openai.deployments" for check in checks)
    rows = _deployment_rows(spec, deployed, checks, candidates, {} if listed else missing)
    return {"observed": observed, "endpoint": endpoint, "location": _region(observed.get("location")),
            "deployments": rows, "missing_deployments": missing}
def _capacity(spec: ConnectSpec, openai_id: str, openai: dict[str, Any], checks: list,
              runner: Callable[..., Any]) -> dict[str, Any]:
    rows = openai["deployments"]
    token_rows = {role: row for role, row in rows.items()
                  if row["sku"] in MODEL_DEPLOYMENT_SKUS and isinstance(row["capacity_k_tpm"], int)
                  and row["capacity_k_tpm"] >= 1 and row["model"] and row["version"]}
    for role, row in rows.items():
        if role not in token_rows:
            _check(checks, f"capacity.{role}", "warn",
                   f"{row['sku']} is not a token-based SKU; capacity is not in TPM and is not "
                   "estimated.")
    report: dict[str, Any] = {"deployments": [], "extraction": None}
    if token_rows:
        group, name = _parts(openai_id)
        pspec = ProvisioningSpec(
            target=Target(subscription_id=spec.subscription_id, resource_group=group,
                          location=openai["location"]),
            search_name="unused", storage_name="unused", openai_name=name,
            model_deployments=tuple(
                ModelDeploymentSpec(role, row["name"], row["model"], str(row["version"]),
                                    row["sku"], row["capacity_k_tpm"])
                for role, row in token_rows.items()),
        )
        report["model_deployments"] = pspec.model_deployments
        try:
            quota = read_regional_quota(pspec, runner=runner)
        except (IdentityError, RuntimeError):
            quota = None
            _check(checks, "capacity.quota", "unverified", "Could not read regional quota.")
        if quota is not None:
            preflight = quota_preflight(
                pspec, quota,
                existing={row["name"]: row["capacity_k_tpm"] for row in token_rows.values()})
            for row in preflight["deployments"]:
                limit, current = row["quota_limit_k_tpm"], row["quota_current_k_tpm"]
                report["deployments"].append({
                    key: row[key] for key in ("role", "deployment", "model", "sku",
                                              "quota_name", "quota_current_k_tpm",
                                              "quota_limit_k_tpm")
                } | {"capacity_k_tpm": row["existing_capacity_k_tpm"],
                     "quota_headroom_k_tpm": None if limit is None else limit - current})
    chat = token_rows.get("chat")
    if chat is not None:
        from ekg_build.estimates import extraction_estimate
        estimate = extraction_estimate(
            BuildSpec(target=Target(), corpus_source="connect"), spec.documents or 1,
            chat_capacity_k_tpm=chat["capacity_k_tpm"])
        if spec.documents is None:
            estimate = {key: estimate.get(key) for key in (
                "origin", "reasoning_effort", "page_parallelism", "chat_capacity_k_tpm",
                "serial_tokens_per_minute", "tpm_bound", "max_page_parallelism_for_capacity",
                "assumptions", "uncertainty")}
        report["extraction"] = estimate
        throttles = [item for item in estimate.get("uncertainty") or [] if "TPM" in item]
        _check(checks, "capacity.chat_throttle", "warn" if throttles else "ok",
               " ".join(throttles) or f"{chat['capacity_k_tpm']}K TPM covers default extraction "
               "at measured rates.")
    return report
