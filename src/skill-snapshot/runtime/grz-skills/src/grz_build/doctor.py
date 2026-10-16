"""grz-build doctor: read-only checks of the operator's machine, sign-in, state and reader access."""

from __future__ import annotations

import argparse
import shutil
from typing import Any, Callable

from grz_core import doctor as d
from grz_core.azure_auth import MANAGEMENT_SCOPE, SEARCH_SCOPE

CLI = "grz-build"


def run_doctor(args: argparse.Namespace, *, credential: Any | None = None, get: d.HttpGet = d.http_get,
               which: Callable[[str], str | None] = shutil.which, run: d.Runner = d._run) -> dict[str, Any]:
    tenant = getattr(args, "tenant_id", None)
    signin: dict[str, Any] = {}
    auth: dict[str, Any] = {}
    account = d.read_account(which, run)

    def azure_signin() -> d.Check:
        signin["check"] = d.check_azure_signin(tenant, which=which, run=run, account=account)
        return signin["check"]

    def headers(scope: str) -> dict[str, str]:
        if "credential" not in auth:
            from grz_core.azure_auth import create_default_credential, validate_tenant

            auth["credential"] = credential or create_default_credential()
            validate_tenant(auth["credential"], tenant)
        return d.bearer(auth["credential"], scope, tenant)

    def live() -> bool:
        return signin.get("check", {}).get("status") == d.OK

    def endpoint() -> str:
        from grz_build.live import service_endpoint

        return service_endpoint(args.search_service)

    def source_reader() -> d.Check:
        if not (args.search_service and args.source_index):
            return d.skip("source_reader", "no --search-service and --source-index")
        if not live():
            return d.skip("source_reader", "needs a signed-in --tenant-id")
        return d.check_search_reader("source_reader", endpoint(), args.source_index, headers(SEARCH_SCOPE), get=get)

    def sidecar_reader() -> d.Check:
        alias = args.alias
        if not alias and args.dataset and args.vector_field:
            from grz_build.live import default_alias

            alias = default_alias(args.dataset, args.vector_field)
        if not (args.search_service and alias):
            return d.skip("sidecar_reader", "no --search-service and --alias (or --dataset and --vector-field)")
        if not live():
            return d.skip("sidecar_reader", "needs a signed-in --tenant-id")
        return d.check_search_reader("sidecar_reader", endpoint(), alias, headers(SEARCH_SCOPE), get=get,
                                     missing_ok=True)

    def naming_data_plane() -> d.Check:
        hdrs = (lambda: headers(d.COGNITIVE_SCOPE)) if live() else None
        return d.check_naming_data_plane(getattr(args, "naming_endpoint", None),
                                         getattr(args, "naming_deployment", None), hdrs, get=get)

    naming: dict[str, Any] = {}

    def naming_scope() -> tuple[Any, ...]:
        hdrs = (lambda: headers(MANAGEMENT_SCOPE)) if live() else None
        return (getattr(args, "naming_endpoint", None), getattr(args, "naming_deployment", None),
                args.subscription_id, getattr(args, "naming_resource_group", None) or args.resource_group, hdrs)

    def naming_deployment() -> d.Check:
        naming["deployment"] = d.check_naming_deployment(*naming_scope(), get=get)
        return naming["deployment"]

    def naming_model_lifecycle() -> d.Check:
        deployed = naming.get("deployment") or {}
        return d.check_naming_model_lifecycle(
            *naming_scope(), model=(deployed.get("model_name"), deployed.get("model_version")),
            label=getattr(args, "naming_model", None), get=get)

    result = d.run_checks([
        ("cli_version", lambda: d.check_cli_version(CLI)),
        ("python", d.check_python),
        ("uv", lambda: d.check_uv(which)),
        ("azure_signin", azure_signin),
        ("state_dir", lambda: d.check_state_dir(args.state_dir)),
        ("journal", lambda: d.check_journal(args.state_dir, CLI)),
        ("source_reader", source_reader),
        ("sidecar_reader", sidecar_reader),
        ("naming_data_plane", naming_data_plane),
        ("naming_deployment", naming_deployment),
        ("naming_model_lifecycle", naming_model_lifecycle),
    ], ok_next_step=f"run {CLI} inspect with your source flags, then plan.")
    return d.report(result, account=d.account_or_none(account), current=d.current_build())
