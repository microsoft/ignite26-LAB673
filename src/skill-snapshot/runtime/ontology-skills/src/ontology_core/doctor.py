"""`doctor` checks.

Output is one line per check (`ok`/`FAIL`/`skip`, name, detail), then `Next step: ...`. All checks
run; the first FAIL sets `status:"blocked"` and `error_code:"DOCTOR_<CHECK>"` in `result()`, which blocks
`connect`. The `doctor` verb itself always exits 0 and, with `--json`, prints `report()`, the shape every
plugin shares. A skip never blocks. Doctor never sends a completion.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote, urlparse

from ontology_core import errors
from ontology_core.errors import Blocked
from ontology_core.model import Config

CheckStatus = Literal["ok", "FAIL", "skip"]

CHECKS: tuple[str, ...] = (
    "cli_version", "python", "uv", "azure_signin", "state_dir", "journal", "grz_descriptor",
    "sidecar_reader", "grz_manifest", "model_data_plane", "model_deployment",
)
"""`ontology-build doctor` checks, in output order. Each FAIL maps to error code `DOCTOR_<NAME.upper()>`."""

CONSUME_CHECKS: tuple[str, ...] = ("cli_version", "python", "uv", "state_dir", "journal")
"""`ontology-consume doctor` checks (no Azure)."""

MIN_PYTHON = (3, 12)
PACKAGE = "ontology-skills"
PLUGIN_INSTALL = "copilot plugin install ontology-skills@ontology-skills"
COGNITIVE_ARM_API_VERSION = "2024-10-01"
ARM = "https://management.azure.com"


def code_for(check: str) -> str:
    """`DOCTOR_<CHECK>` for a name in `CHECKS`."""
    return f"DOCTOR_{check.upper()}"


@dataclass
class Check:
    name: str
    status: CheckStatus
    detail: str = ""
    next_step: str | None = None
    """Rendered `next_step` for a FAIL (defaults to the `DOCTOR_<CHECK>` template)."""
    data: dict[str, Any] = field(default_factory=dict)
    """Structured facts, e.g. `{"model_name": ..., "model_version": ...}` from `model_deployment`."""

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {"name": self.name, "status": self.status, "detail": self.detail}
        if self.status == "FAIL":
            body["error_code"] = code_for(self.name)
            body["next_step"] = self.next_step or errors.render_next_step(code_for(self.name))
        if self.data:
            body["data"] = self.data
        return body


@dataclass
class DoctorContext:
    """Inputs resolved from flags first, then `config.json`. Any may be None (the check is skipped)."""

    state_dir: Path
    config: Config | None = None
    tenant_id: str | None = None
    tenant_name: str | None = None
    grz_descriptor: Path | None = None
    model_endpoint: str | None = None
    model_deployment: str | None = None
    subscription_id: str | None = None
    model_resource_group: str | None = None
    plugin_root: Path | None = None
    """From `--plugin-root` or `$ONTOLOGY_PLUGIN_ROOT`; else `cli_version` looks for the Copilot CLI install."""
    cache: dict[str, Any] = field(default_factory=dict, repr=False)
    """Objects shared between checks within one run (descriptor, reader, signed-in account)."""


CheckFn = Callable[[DoctorContext, dict[str, Check]], Check]
"""A check receives the context and earlier results (for dependent skips, e.g. grz_manifest on sidecar_reader)."""


def _ok(name: str, detail: str, **data: Any) -> Check:
    return Check(name, "ok", detail, data={k: v for k, v in data.items() if v is not None})


def _skip(name: str, detail: str) -> Check:
    return Check(name, "skip", detail)


def _passed(earlier: dict[str, Check], name: str) -> bool:
    return name in earlier and earlier[name].status == "ok"


def _tenant_label(ctx: DoctorContext) -> str:
    return f"tenant {ctx.tenant_id}" + (f" ({ctx.tenant_name})" if ctx.tenant_name else "")


# --------------------------------------------------------------------------- machine


def installed_version() -> str | None:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version(PACKAGE)
    except PackageNotFoundError:
        return None


def check_cli_version(ctx: DoctorContext, earlier: dict[str, Check]) -> Check:
    from ontology_core import __version__

    installed = installed_version() or __version__
    root = ctx.plugin_root or installed_plugin_root()
    if root is None:
        return _skip("cli_version", f"ontology-skills {installed}; no Copilot plugin install found")
    manifest = Path(root) / "plugin.json"
    try:
        plugin = json.loads(manifest.read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError) as exc:
        raise Blocked("DOCTOR_CLI_VERSION", f"cannot read {manifest}: {exc}") from exc
    if plugin != installed:
        raise Blocked("DOCTOR_CLI_VERSION", f"CLI {installed} does not match plugin {plugin} ({manifest})",
                      next_step=f"{errors.CODES['DOCTOR_CLI_VERSION']}; then `{PLUGIN_INSTALL}`")
    return _ok("cli_version", f"ontology-skills {installed} (plugin {plugin})", version=installed)


def check_python(ctx: DoctorContext, earlier: dict[str, Check], *,
                 version: tuple[int, ...] | None = None) -> Check:
    current = tuple(version or sys.version_info[:3])
    shown = ".".join(map(str, current))
    if current[:2] < MIN_PYTHON:
        raise Blocked("DOCTOR_PYTHON", f"Python {shown} is older than 3.12")
    return _ok("python", f"Python {shown}")


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)


def check_uv(ctx: DoctorContext, earlier: dict[str, Check]) -> Check:
    path = shutil.which("uv")
    if path is None:
        raise Blocked("DOCTOR_UV", "uv is not on PATH")
    result = _run([path, "--version"])
    if result.returncode != 0:
        raise Blocked("DOCTOR_UV", f"`uv --version` exited {result.returncode}")
    return _ok("uv", result.stdout.strip() or path)


# --------------------------------------------------------------------------- Azure sign-in


def check_azure_signin(ctx: DoctorContext, earlier: dict[str, Check]) -> Check:
    """Reads `az account show` through azure_auth; never signs in. The tenant is named first."""
    if not ctx.tenant_id:
        return _skip("azure_signin", "no tenant yet (--tenant-id); Azure checks skipped")
    from ontology_core import azure_auth

    try:
        account = azure_auth.require_tenant(ctx.tenant_id, ctx.tenant_name)
    except Blocked as exc:
        raise Blocked("DOCTOR_AZURE_SIGNIN", f"{_tenant_label(ctx)}: {exc.error}", next_step=exc.next_step,
                      details={"cause": exc.code}) from exc
    ctx.cache["account"] = account
    if not ctx.tenant_name and account.tenant_name:
        ctx.tenant_name = account.tenant_name
    who = f" as {account.user}" if account.user else ""
    return _ok("azure_signin", f"{_tenant_label(ctx)}: signed in{who}", tenant_id=ctx.tenant_id,
               tenant_name=ctx.tenant_name, account=account.user or None)


# --------------------------------------------------------------------------- state


def check_state_dir(ctx: DoctorContext, earlier: dict[str, Check]) -> Check:
    """Exists or can be created, writable, user-only. Never creates anything."""
    from ontology_core import state

    root = Path(ctx.state_dir)
    existing = root
    while not existing.exists() and existing.parent != existing:
        existing = existing.parent
    if not existing.is_dir():
        raise Blocked("DOCTOR_STATE_DIR", f"{existing} is not a directory")
    try:
        with tempfile.TemporaryFile(dir=existing):
            pass
    except OSError as exc:
        raise Blocked("DOCTOR_STATE_DIR", f"{existing} is not writable: {exc.strerror or exc}") from exc
    if existing != root:
        return _ok("state_dir", f"{root} will be created (user-only)")
    if not state.is_user_only(root):
        raise Blocked("DOCTOR_STATE_DIR", f"{root} is readable by other users")
    paths = state.paths_for(root)
    if paths.config.is_file():
        try:
            state.load_config(paths)
        except Blocked as exc:
            raise Blocked("DOCTOR_STATE_DIR", f"config.json: {exc.error}", next_step=exc.next_step) from exc
    return _ok("state_dir", f"{root} writable, user-only")


def check_journal(ctx: DoctorContext, earlier: dict[str, Check]) -> Check:
    from ontology_build import reconcile
    from ontology_core import journal as journal_mod
    from ontology_core import state

    paths = state.paths_for(ctx.state_dir)
    if not paths.journal.is_file():
        return _skip("journal", "no journal yet")
    try:
        entries = journal_mod.Journal(paths).read()
    except Blocked as exc:
        raise Blocked("DOCTOR_JOURNAL", exc.error) from exc
    lock = journal_mod.read_lock(paths)
    if lock is not None:
        stale = lock.host != journal_mod.this_host() or not journal_mod.pid_alive(lock.pid)
        if stale:
            raise Blocked("DOCTOR_JOURNAL", f"stale lock from {lock.verb} (pid {lock.pid} on {lock.host})")
    report = reconcile.check(paths)
    if report.drift:
        raise Blocked("DOCTOR_JOURNAL", f"{len(report.drift)} file(s) differ from the journal: "
                      + ", ".join(report.drift[:3]))
    detail = f"{len(entries)} entries, no drift"
    if lock is not None:
        detail += f"; {lock.verb} is running (pid {lock.pid})"
    if report.open_runs:
        detail += f"; {len(report.open_runs)} unfinished run(s), rerun propose to resume"
    return _ok("journal", detail)


# --------------------------------------------------------------------------- GRZ


def _descriptor(ctx: DoctorContext) -> Any:
    return ctx.cache.get("descriptor")


def check_grz_descriptor(ctx: DoctorContext, earlier: dict[str, Check]) -> Check:
    if ctx.grz_descriptor is None:
        return _skip("grz_descriptor", "no descriptor yet (--grz-descriptor)")
    from ontology_build import grz_reader

    try:
        descriptor = grz_reader.load_descriptor(Path(ctx.grz_descriptor))
    except Blocked as exc:
        raise Blocked("DOCTOR_GRZ_DESCRIPTOR", exc.error, details={"cause": exc.code}) from exc
    ctx.cache["descriptor"] = descriptor
    return _ok("grz_descriptor", f"generation {descriptor.generation_id}, index {descriptor.physical_index}, "
               f"{descriptor.visibility}", generation_id=descriptor.generation_id)


def _you(ctx: DoctorContext) -> str:
    account = ctx.cache.get("account")
    return getattr(account, "user", None) or "<your sign-in>"


def check_sidecar_reader(ctx: DoctorContext, earlier: dict[str, Check]) -> Check:
    if not _passed(earlier, "grz_descriptor"):
        return _skip("sidecar_reader", "needs a valid descriptor")
    if not _passed(earlier, "azure_signin"):
        return _skip("sidecar_reader", "needs a signed-in tenant")
    from ontology_build import grz_reader
    from ontology_core.http import EgressPolicy

    descriptor = _descriptor(ctx)
    policy = EgressPolicy(search_endpoint=descriptor.search_endpoint, physical_index=descriptor.physical_index)
    try:
        search = grz_reader.live_search(descriptor, str(ctx.tenant_id), policy)
        reader = grz_reader.GrzReader(descriptor, search)
        manifest = reader.manifest()
    except Blocked as exc:
        if exc.code == "GRZ_SIDECAR_ACCESS_DENIED":
            scope = f"<search service resource ID>/indexes/{descriptor.physical_index}"
            raise Blocked("DOCTOR_SIDECAR_READER", f"{descriptor.physical_index}: access denied",
                          you=_you(ctx), index_scope=scope) from exc
        if exc.code == "GRZ_SIDECAR_NOT_FOUND":
            raise Blocked("DOCTOR_SIDECAR_READER", f"{descriptor.physical_index}: {exc.error}",
                          next_step=f"the GRZ generation's search service ({descriptor.search_endpoint}) or sidecar "
                                    "is unreachable; republish the GRZ generation, or rerun doctor with "
                                    "`--grz-descriptor` pointing at a current descriptor",
                          details={"cause": exc.code}) from exc
        raise Blocked("DOCTOR_SIDECAR_READER", f"{descriptor.physical_index}: {exc.error}",
                      next_step=exc.next_step, details={"cause": exc.code}) from exc
    ctx.cache["reader"] = reader
    ctx.cache["manifest"] = manifest
    return _ok("sidecar_reader", f"{descriptor.physical_index}: manifest readable")


def check_grz_manifest(ctx: DoctorContext, earlier: dict[str, Check]) -> Check:
    if not _passed(earlier, "sidecar_reader"):
        return _skip("grz_manifest", "needs a readable sidecar")
    from ontology_build import grz_reader

    reader, manifest = ctx.cache["reader"], ctx.cache["manifest"]
    try:
        representatives = reader.representatives()
        members = reader.members(None)
        grz_reader.check_manifest(manifest, representatives, members)
    except Blocked as exc:
        raise Blocked("DOCTOR_GRZ_MANIFEST", exc.error, details={"cause": exc.code}) from exc
    return _ok("grz_manifest", f"health {manifest.health}, {len(representatives)} communities, "
               f"{len(members)} memberships", manifest_digest=manifest.digest)


# --------------------------------------------------------------------------- model (metadata only)


def account_name(endpoint: str) -> str:
    return (urlparse(endpoint).hostname or "").split(".", 1)[0]


def check_model_data_plane(ctx: DoctorContext, earlier: dict[str, Check]) -> Check:
    """Lists the resource's models with the caller's Entra token. Never sends a completion."""
    if not ctx.model_endpoint:
        return _skip("model_data_plane", "no model endpoint yet (--model-endpoint)")
    if not _passed(earlier, "azure_signin"):
        return _skip("model_data_plane", "needs a signed-in tenant")
    from ontology_build.model_client import ModelClient
    from ontology_core.http import EgressPolicy

    endpoint = ctx.model_endpoint.rstrip("/")
    policy = EgressPolicy(model_endpoint=endpoint, model_deployment=ctx.model_deployment)
    client = ModelClient(endpoint=endpoint, deployment=ctx.model_deployment or "", tenant_id=str(ctx.tenant_id),
                         policy=policy)
    status = client.list_models()
    if status == 200:
        return _ok("model_data_plane", f"{endpoint}: models readable (metadata only, no completion)")
    if status in (401, 403):
        raise Blocked("DOCTOR_MODEL_DATA_PLANE", f"{endpoint}: HTTP {status}", you=_you(ctx),
                      account=f"<resource ID of {account_name(endpoint)}>")
    raise Blocked("DOCTOR_MODEL_DATA_PLANE", f"{endpoint}: HTTP {status}",
                  next_step="fix `--model-endpoint` (https://<account>.openai.azure.com) and rerun doctor")


def check_model_deployment(ctx: DoctorContext, earlier: dict[str, Check]) -> Check:
    """Read-only ARM GET of Microsoft.CognitiveServices/accounts/deployments; records model name and version."""
    if not (ctx.model_endpoint and ctx.model_deployment):
        return _skip("model_deployment", "no model endpoint and deployment yet")
    if not (ctx.subscription_id and ctx.model_resource_group):
        return _skip("model_deployment", "no --subscription-id and --model-resource-group")
    if not _passed(earlier, "azure_signin"):
        return _skip("model_deployment", "needs a signed-in tenant")
    from ontology_core import azure_auth, http

    account = account_name(ctx.model_endpoint)
    url = (f"{ARM}/subscriptions/{quote(ctx.subscription_id, safe='')}/resourceGroups/"
           f"{quote(ctx.model_resource_group, safe='')}/providers/Microsoft.CognitiveServices/accounts/"
           f"{quote(account, safe='')}/deployments/{quote(ctx.model_deployment, safe='')}"
           f"?api-version={COGNITIVE_ARM_API_VERSION}")
    policy = http.EgressPolicy(model_endpoint=ctx.model_endpoint.rstrip("/"), model_deployment=ctx.model_deployment,
                               subscription_id=ctx.subscription_id, resource_group=ctx.model_resource_group,
                               account_name=account)
    headers = {"Authorization": "Bearer " + azure_auth.token(str(ctx.tenant_id), "arm")}
    response = http.request(policy, "GET", url, headers=headers)
    where = f"{account}/{ctx.model_deployment}"
    if response.status == 200:
        try:
            props = json.loads(response.body or b"{}").get("properties") or {}
        except ValueError:
            props = {}
        model = props.get("model") or {}
        name, version = model.get("name"), model.get("version")
        state = props.get("provisioningState")
        if state and state != "Succeeded":
            raise Blocked("DOCTOR_MODEL_DEPLOYMENT", f"{where}: provisioningState {state}",
                          next_step="wait for the deployment to finish provisioning, then rerun doctor")
        detail = f"{where}: {name or '?'} {version or ''}".rstrip()
        return _ok("model_deployment", detail, model_name=name, model_version=version)
    if response.status == 404:
        raise Blocked("DOCTOR_MODEL_DEPLOYMENT", f"{where}: not found (HTTP 404)")
    if response.status in (401, 403):
        raise Blocked("DOCTOR_MODEL_DEPLOYMENT", f"{where}: HTTP {response.status} reading the deployment",
                      next_step="ask an owner for Reader on the model resource group, or drop "
                                "`--subscription-id/--model-resource-group` to skip this check")
    raise Blocked("DOCTOR_MODEL_DEPLOYMENT", f"{where}: HTTP {response.status}")


CHECK_FUNCTIONS: dict[str, CheckFn] = {
    "cli_version": check_cli_version,
    "python": check_python,
    "uv": check_uv,
    "azure_signin": check_azure_signin,
    "state_dir": check_state_dir,
    "journal": check_journal,
    "grz_descriptor": check_grz_descriptor,
    "sidecar_reader": check_sidecar_reader,
    "grz_manifest": check_grz_manifest,
    "model_data_plane": check_model_data_plane,
    "model_deployment": check_model_deployment,
}


def run(ctx: DoctorContext, *, checks: tuple[str, ...] = CHECKS) -> list[Check]:
    """Run every named check in order, catching `Blocked` inside each check into a FAIL. Never raises."""
    results: dict[str, Check] = {}
    for name in checks:
        try:
            check = CHECK_FUNCTIONS[name](ctx, dict(results))
        except Blocked as exc:
            data = dict(exc.details) if exc.details else {}
            check = Check(name, "FAIL", exc.error, next_step=exc.next_step, data=data)
        except Exception as exc:  # a broken probe must not hide the other checks
            hint = errors.render_next_step(code_for(name), tenant_id=ctx.tenant_id,
                                           tenant_name=ctx.tenant_name or "the tenant that owns the GRZ index")
            check = Check(name, "FAIL", f"{type(exc).__name__}: {exc}", next_step=hint)
        results[name] = check
    return list(results.values())


def result(checks: list[Check], *, next_step_if_ok: str) -> dict[str, Any]:
    """The verb result: `{status:"ok", checks:[...], next_step}` or the blocked envelope of the first FAIL
    (`error_code` `DOCTOR_<CHECK>`) plus `checks`."""
    rows = [c.to_dict() for c in checks]
    first = next((c for c in checks if c.status == "FAIL"), None)
    if first is None:
        return {"status": "ok", "checks": rows, "next_step": next_step_if_ok}
    failed = first.to_dict()
    body = errors.envelope(failed["error_code"], f"{first.name}: {first.detail}", failed["next_step"])
    body["checks"] = rows
    return body


_REPORT_STATUS = {"ok": "pass", "skip": "warn", "FAIL": "fail"}


def report(result_body: dict[str, Any]) -> dict[str, Any]:
    """The cross-plugin `doctor --json` shape, built from `result()`:
    `{plugin, version, ready, signed_in:{tenant_id, account}, current:{kind, path, id}|null,
    checks:[{name, status: pass|warn|fail, detail}], next_step}`. Read-only."""
    from ontology_core import current as current_mod

    rows = result_body.get("checks", [])
    signin = next((r.get("data", {}) for r in rows if r["name"] == "azure_signin" and r["status"] == "ok"), {})
    checks = [{"name": r["name"], "status": _REPORT_STATUS.get(r["status"], "warn"), "detail": r.get("detail", "")}
              for r in rows]
    pointer_ref = None
    try:
        pointer = current_mod.load(required=False)
    except Blocked as exc:
        checks.append({"name": "current", "status": "warn", "detail": exc.error})
    else:
        if pointer is None:
            checks.append({"name": "current", "status": "warn", "detail": "no approved ontology recorded yet"})
        else:
            pointer_ref = {"kind": current_mod.KIND, "path": pointer["path"], "id": pointer["schema_id"]}
            checks.append({"name": "current", "status": "pass",
                           "detail": f"v{pointer['version']} {pointer['schema_id']} at {pointer['path']}"})
    return {
        "plugin": PACKAGE,
        "version": installed_version() or "unknown",
        "ready": result_body.get("status") == "ok",
        "signed_in": {"tenant_id": signin.get("tenant_id"), "account": signin.get("account")},
        "current": pointer_ref,
        "checks": checks,
        "next_step": str(result_body.get("next_step") or ""),
    }


def render(checks: list[Check], next_step: str) -> str:
    """Summary text: `ok    name  detail` lines, then `Next step: ...`."""
    width = max((len(c.name) for c in checks), default=0)
    lines = [f"{c.status:<4}  {c.name:<{width}}  {c.detail}".rstrip() for c in checks]
    lines.append(f"Next step: {next_step}")
    return "\n".join(lines)


def plugin_root_from(flag: str | None) -> Path | None:
    value = flag or os.environ.get("ONTOLOGY_PLUGIN_ROOT")
    return Path(value).expanduser() if value else None


def copilot_home() -> Path:
    """Copilot CLI's config directory: `$COPILOT_HOME`, else `~/.copilot`."""
    value = os.environ.get("COPILOT_HOME")
    return Path(value).expanduser() if value else Path.home() / ".copilot"


def installed_plugin_root() -> Path | None:
    """The Copilot CLI install of this plugin, `<copilot home>/installed-plugins/<marketplace>/ontology-skills`,
    preferring the `ontology-skills` marketplace when several marketplaces installed it."""
    base = copilot_home() / "installed-plugins"
    found = sorted(p.parent for p in base.glob(f"*/{PACKAGE}/plugin.json"))
    if not found:
        return None
    return next((p for p in found if p.parent.name == PACKAGE), found[0])
