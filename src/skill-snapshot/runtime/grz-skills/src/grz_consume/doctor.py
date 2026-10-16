"""grz-consume doctor: read-only checks of the machine, sign-in, descriptor and sidecar."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Callable

from grz_core import doctor as d

from .config import ConsumeConfig, build_service

CLI = "grz-consume"


def check_sidecar(config: ConsumeConfig, signed_in: bool, descriptor_ok: bool = True) -> d.Check:
    if config.descriptor is None or not descriptor_ok:
        return d.skip("sidecar", "needs a readable descriptor")
    if not config.endpoint:
        return d.skip("sidecar", "no --endpoint (or GRZ_SEARCH_ENDPOINT)")
    if config.endpoint and config.auth == "entra" and not signed_in:
        return d.skip("sidecar", "--auth entra needs a signed-in --tenant-id")
    status = build_service(config).status()
    counts = status.get("communities_per_level") or {}
    if status.get("build_health") != "verified":
        return d.fail("sidecar", "SIDECAR_INTEGRITY_FAILED",
                      f"{status['physical_index']}: manifest health is {status.get('build_health')}, not verified")
    return d.ok("sidecar", f"{status['physical_index']}: health verified, counts match, "
                           f"{sum(counts.values())} communities over {len(counts)} levels")


def run_doctor(config: ConsumeConfig, *, which: Callable[[str], str | None] = shutil.which,
               run: d.Runner = d._run) -> dict[str, Any]:
    seen: dict[str, d.Check] = {}

    def remember(name: str, check: Callable[[], d.Check]) -> Callable[[], d.Check]:
        def wrapped() -> d.Check:
            try:
                seen[name] = check()
            except Exception:
                seen[name] = {"status": d.FAIL}
                raise
            return seen[name]
        return wrapped

    def passed(name: str) -> bool:
        return seen.get(name, {}).get("status") == d.OK

    account = d.read_account(which, run)
    result = d.run_checks([
        ("cli_version", lambda: d.check_cli_version(CLI)),
        ("python", d.check_python),
        ("uv", lambda: d.check_uv(which)),
        ("azure_signin", remember("azure_signin", lambda: d.check_azure_signin(config.tenant_id, which=which, run=run,
                                                                           account=account))),
        ("descriptor", remember("descriptor", lambda: d.check_descriptor(config.descriptor))),
        ("source_reader", lambda: d.skip("source_reader", "consume reads only the sidecar")),
        ("sidecar", lambda: check_sidecar(config, passed("azure_signin"),
                                                config.descriptor is None or passed("descriptor"))),
    ], ok_next_step=f"run {CLI} status with the same connection flags.")
    return d.report(result, account=d.account_or_none(account), current=current_of(config))


def current_of(config: ConsumeConfig) -> dict[str, str] | None:
    """The build doctor would browse: an explicit descriptor, or the one current.json points at."""
    if config.descriptor is None:
        return None
    if config.from_current:
        return d.current_build()
    try:
        generation = json.loads(Path(config.descriptor).read_text(encoding="utf-8")).get("generation_id")
    except (OSError, ValueError, AttributeError):
        generation = None
    return {"kind": "descriptor", "path": str(config.descriptor), "id": str(generation or "")}
