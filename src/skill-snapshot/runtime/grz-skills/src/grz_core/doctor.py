"""Read-only operator environment checks shared by grz-build, grz-consume and grz-mcp.

Every check is a read: no Azure writes, no model completions, no spend. A check
that lacks its input reports `skip`, so doctor works before any config exists.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Iterable

from grz_core.cli_output import next_step as table_next_step
from grz_core.contracts import ContractError

OK, FAIL, SKIP = "ok", "FAIL", "skip"
MIN_PYTHON = (3, 12)
PACKAGE = "grz-skills"
SEARCH_API_VERSION = "2026-04-01"
OPENAI_METADATA_API_VERSION = "2024-10-21"
COGNITIVE_ARM_API_VERSION = "2024-10-01"
COGNITIVE_SCOPE = "https://cognitiveservices.azure.com/.default"

Check = dict[str, Any]


def ok(name: str, detail: str, **extra: Any) -> Check:
    return {"name": name, "status": OK, "detail": detail, **extra}


def skip(name: str, detail: str) -> Check:
    return {"name": name, "status": SKIP, "detail": detail}


def fail(name: str, code: str, detail: str, step: str | None = None) -> Check:
    return {"name": name, "status": FAIL, "error_code": code, "detail": detail,
            "next_step": step or table_next_step(code)}


def run_checks(checks: Iterable[tuple[str, Callable[[], Check]]], ok_next_step: str) -> dict[str, Any]:
    results: list[Check] = []
    for name, check in checks:
        try:
            results.append(check())
        except ContractError as exc:
            detail = str(exc)[len(exc.code) + 2:] if str(exc).startswith(f"{exc.code}: ") else str(exc)
            results.append(fail(name, exc.code, detail))
        except Exception as exc:  # a broken check must not hide the others
            results.append(fail(name, "CLI_ERROR", f"{type(exc).__name__}: {exc}"))
    first = next((r for r in results if r["status"] == FAIL), None)
    return {"status": "blocked" if first else "ok", "checks": results,
            "next_step": first["next_step"] if first else ok_next_step}


PLUGIN = "grz-skills"
_STATUS = {OK: "pass", FAIL: "fail", SKIP: "warn"}


def _public_check(check: Check) -> Check:
    detail = check["detail"]
    if check["status"] == SKIP:
        detail = f"not checked: {detail}"
    elif check.get("warning"):
        detail = f"{detail}; warning: {check['warning']}"
    status = "warn" if check["status"] == OK and check.get("warning") else _STATUS[check["status"]]
    return {"name": check["name"], "status": status, "detail": detail}


def report(result: dict[str, Any], *, account: dict[str, Any] | None,
           current: dict[str, str] | None) -> dict[str, Any]:
    """The one doctor shape every GRZ surface prints: ready, who is signed in, which build is current, checks."""
    account = account or {}
    user = account.get("user") if isinstance(account.get("user"), dict) else {}
    return {
        "plugin": PLUGIN,
        "version": installed_version() or "unknown",
        "ready": result["status"] == "ok",
        "signed_in": {"tenant_id": account.get("tenantId") or None, "account": user.get("name") or None},
        "current": current,
        "checks": [_public_check(check) for check in result["checks"]],
        "next_step": result["next_step"],
    }


def summarize(result: dict[str, Any]) -> str:
    width = max(len(r["name"]) for r in result["checks"])
    lines = [f"{'ready' if result['ready'] else 'not ready'}: {result['plugin']} {result['version']}"]
    lines += [f"{r['status']:<4}  {r['name']:<{width}}  {r['detail']}" for r in result["checks"]]
    lines.append(f"Next step: {result['next_step']}")
    return "\n".join(lines)


def emit_doctor(result: dict[str, Any], as_json: bool, cli: str) -> int:
    """Doctor only reads and reports, so it exits 0 even when the machine isn't ready."""
    del cli
    if as_json:
        print(json.dumps(result, sort_keys=True, ensure_ascii=False))
    else:
        print(summarize(result))
    return 0


# ---- machine ---------------------------------------------------------------------------------

def installed_version() -> str | None:
    from importlib.metadata import PackageNotFoundError, version
    try:
        return version(PACKAGE)
    except PackageNotFoundError:
        return None


def _plugin_manifest() -> Path | None:
    roots = [os.environ.get("PLUGIN_ROOT"), os.environ.get("CLAUDE_PLUGIN_ROOT"),
             str(Path(__file__).resolve().parents[2])]
    for root in filter(None, roots):
        path = Path(root) / "plugin.json"
        if path.is_file():
            return path
    return None


def _version_tuple(value: str) -> tuple[int, ...]:
    parts = []
    for part in value.split("."):
        digits = "".join(c for c in part if c.isdigit())
        parts.append(int(digits or 0))
    return tuple(parts)


def check_cli_version(cli: str, *, manifest: Path | None = None) -> Check:
    installed = installed_version()
    if installed is None:
        return fail("cli_version", "DEPENDENCY_UNAVAILABLE", f"{PACKAGE} is not installed")
    manifest = manifest or _plugin_manifest()
    if manifest is None:
        return ok("cli_version", f"{cli} {installed} (plugin version unknown)")
    try:
        plugin = json.loads(manifest.read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError):
        plugin = None
    if not plugin:
        return ok("cli_version", f"{cli} {installed} (plugin version unknown)")
    if _version_tuple(installed) < _version_tuple(plugin):
        return ok("cli_version", f"{cli} {installed}", plugin_version=plugin,
                  warning=f"CLI {installed} is older than plugin {plugin}; reinstall with uv tool install --force")
    return ok("cli_version", f"{cli} {installed} (plugin {plugin})", plugin_version=plugin)


def check_python(version: tuple[int, ...] | None = None) -> Check:
    current = tuple(version or sys.version_info[:3])
    shown = ".".join(map(str, current))
    if current[:2] < MIN_PYTHON:
        return fail("python", "PYTHON_TOO_OLD", f"Python {shown} is older than 3.12")
    return ok("python", f"Python {shown}")


def check_uv(which: Callable[[str], str | None] = shutil.which) -> Check:
    path = which("uv")
    return ok("uv", f"uv at {path}") if path else fail("uv", "UV_MISSING", "uv is not on PATH")


# ---- Azure sign-in ---------------------------------------------------------------------------

Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


def _run(command: list[str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)


def read_account(which: Callable[[str], str | None] = shutil.which, run: Runner = _run) -> dict[str, Any] | str:
    """`az account show`, read once per doctor run: the account, or "missing" (no az) or "signed_out"."""
    az = which("az")
    if az is None:
        return "missing"
    result = run([az, "account", "show", "--output", "json"])
    if result.returncode != 0:
        return "signed_out"
    try:
        account = json.loads(result.stdout)
    except ValueError:
        return "signed_out"
    return account if isinstance(account, dict) else "signed_out"


def check_azure_signin(tenant_id: str | None, *, which: Callable[[str], str | None] = shutil.which,
                       run: Runner = _run, account: dict[str, Any] | str | None = None) -> Check:
    """Read `az account show`; never signs in. The tenant is printed first."""
    if not tenant_id:
        return skip("azure_signin", "no --tenant-id; live checks skipped")
    if account is None:
        account = read_account(which, run)
    if account == "missing":
        return fail("azure_signin", "AZ_CLI_MISSING", f"tenant {tenant_id}: Azure CLI (az) is not on PATH")
    if not isinstance(account, dict):
        return fail("azure_signin", "AZ_SIGNIN_REQUIRED", f"tenant {tenant_id}: not signed in to the Azure CLI",
                    f"sign in to tenant {tenant_id} (az login --tenant {tenant_id}), then run doctor again.")
    signed_in = account.get("tenantId")
    if signed_in != tenant_id:
        return fail("azure_signin", "TENANT_MISMATCH", f"tenant {tenant_id}: az is signed in to tenant {signed_in}",
                    f"sign in to tenant {tenant_id} (az login --tenant {tenant_id}), then run doctor again.")
    return ok("azure_signin", f"tenant {tenant_id}: signed in")


def account_or_none(account: dict[str, Any] | str) -> dict[str, Any] | None:
    return account if isinstance(account, dict) else None


def current_build() -> dict[str, str] | None:
    """The build this account published last, from current.json; None when there isn't one or it's unreadable."""
    from grz_core.current import current_path, read_current

    try:
        pointer = read_current()
    except ContractError:
        return None
    if pointer is None:
        return None
    return {"kind": "current", "path": str(current_path()), "id": str(pointer.get("generation_id") or "")}


def signed_in(checks: list[Check]) -> bool:
    return any(c["name"] == "azure_signin" and c["status"] == OK for c in checks)


# ---- state directory and journal -------------------------------------------------------------

def check_state_dir(state_dir: Path | None) -> Check:
    """Writable and lock free, without creating anything that isn't there."""
    if state_dir is None:
        return skip("state_dir", "no --state-dir")
    state_dir = Path(state_dir)
    existing = state_dir
    while not existing.exists() and existing.parent != existing:
        existing = existing.parent
    if not existing.is_dir():
        return fail("state_dir", "STATE_DIR_NOT_WRITABLE", f"{state_dir} is not a directory")
    try:
        with tempfile.TemporaryFile(dir=existing):
            pass
    except OSError as exc:
        return fail("state_dir", "STATE_DIR_NOT_WRITABLE", f"{existing} is not writable: {exc.strerror or exc}")
    lock = state_dir / "operations" / "publisher.lock"
    if lock.exists():
        return fail("state_dir", "PUBLISHER_BUSY", f"{lock} is held by another operation")
    where = "writable, lock free" if state_dir.exists() else f"will be created under {existing}"
    return ok("state_dir", f"{state_dir} {where}")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def journal_drift(state_dir: Path) -> dict[str, dict[str, Any]]:
    """Plans whose latest write outcome is unknown (failed, ambiguous, or a lone intent) with no reconcile since."""
    writes = _read_jsonl(Path(state_dir) / "operations" / "writes.jsonl")
    drift: dict[str, dict[str, Any]] = {}
    for plan_id in dict.fromkeys(str(w.get("plan_id")) for w in writes):
        events = [w for w in writes if str(w.get("plan_id")) == plan_id]
        last_reconcile = max((i for i, w in enumerate(events) if w.get("status") == "reconciled"), default=-1)
        latest: dict[tuple[Any, ...], dict[str, Any]] = {}
        for w in events[last_reconcile + 1:]:
            latest[(w.get("operation"), w.get("phase"), w.get("target"), w.get("key_digest"))] = w
        unknown = [w for w in latest.values() if w.get("status") in {"failed", "ambiguous", "intent"}]
        if unknown:
            drift[plan_id] = {"writes": len(unknown), "operations": sorted({str(w.get("operation")) for w in unknown})}
    return drift


def check_journal(state_dir: Path | None, cli: str) -> Check:
    if state_dir is None:
        return skip("journal", "no --state-dir")
    if not (Path(state_dir) / "operations").is_dir():
        return skip("journal", "no journal yet")
    try:
        drift = journal_drift(Path(state_dir))
    except (OSError, ValueError) as exc:
        return fail("journal", "STATE_INVALID", f"cannot read the write journal: {exc}")
    if not drift:
        return ok("journal", "no unknown-outcome writes")
    plan_id, first = next(iter(drift.items()))
    detail = (f"{sum(d['writes'] for d in drift.values())} unknown-outcome write(s) in {len(drift)} plan(s); "
              f"first plan {plan_id[:12]} ({', '.join(first['operations'])})")
    if first["operations"] == ["delete"]:
        return fail("journal", "RETIRE_DELETE_FAILED", detail,
                    f"run {cli} generations to see where the index stands; never repeat an unknown-outcome delete.")
    return fail("journal", "RECONCILE_REQUIRED", detail,
                f"run {cli} reconcile --plan-id {plan_id} with the same flags, review it, then apply with "
                "--resume-after-reconcile; never retry an unknown-outcome write.")


# ---- descriptor -------------------------------------------------------------------------------

def check_descriptor(path: Path | None) -> Check:
    if path is None:
        return skip("descriptor", "no --descriptor, GRZ_DESCRIPTOR or published build")
    from grz_consume.config import ConsumeConfig, load_descriptor

    descriptor = load_descriptor(ConsumeConfig(descriptor=Path(path)))
    basis = " (whole-index attestation)" if descriptor.visibility_basis == "public-attested" else ""
    return ok("descriptor", f"{descriptor.version}, {descriptor.visibility}{basis}, index {descriptor.physical_index}")


# ---- data-plane probes (GET only) ------------------------------------------------------------

HttpGet = Callable[[str, dict[str, str]], tuple[int, str]]


def http_get(url: str, headers: dict[str, str]) -> tuple[int, str]:
    import requests

    response = requests.get(url, headers=headers, timeout=30)
    return response.status_code, response.text


def bearer(credential: Any, scope: str, tenant_id: str) -> dict[str, str]:
    from grz_core.azure_auth import get_token

    return {"Authorization": "Bearer " + get_token(credential, scope, tenant_id)}


def check_search_reader(name: str, endpoint: str, index: str, headers: dict[str, str], *,
                        get: HttpGet = http_get, missing_ok: bool = False) -> Check:
    from urllib.parse import quote

    url = f"{endpoint.rstrip('/')}/indexes/{quote(index, safe='')}/docs/$count?api-version={SEARCH_API_VERSION}"
    status, body = get(url, {**headers, "Accept": "text/plain"})
    if status == 200:
        return ok(name, f"{index}: {body.strip().lstrip(chr(0xfeff))} documents readable")
    if status == 404 and missing_ok:
        return skip(name, f"{index} does not exist yet")
    if status == 404:
        return fail(name, "INDEX_MISSING", f"{index} not found on {endpoint}")
    if status in (401, 403):
        return fail(name, "READ_ACCESS_DENIED", f"{index}: HTTP {status}",
                    f"ask for Search Index Data Reader on {index}, then run doctor again.")
    return fail(name, "SEARCH_REQUEST_FAILED", f"{index}: HTTP {status}")


def _naming_input(name: str, endpoint: str | None, deployment: str | None) -> Check | None:
    if not deployment:
        return skip(name, "naming not configured")
    if not endpoint:
        return fail(name, "NAMING_ARGS_REQUIRED", "--naming-deployment needs --naming-endpoint")
    if not endpoint.startswith("https://"):
        return fail(name, "NAMING_ENDPOINT_INVALID", f"{endpoint} is not https")
    return None


def check_naming_data_plane(endpoint: str | None, deployment: str | None,
                            headers: Callable[[], dict[str, str]] | None, *, get: HttpGet = http_get) -> Check:
    """Data plane, caller's Entra token: list the resource's models. Never sends a completion."""
    name = "naming_data_plane"
    if (early := _naming_input(name, endpoint, deployment)) is not None:
        return early
    if headers is None:
        return skip(name, "needs a signed-in --tenant-id")
    status, _ = get(f"{endpoint.rstrip('/')}/openai/models?api-version={OPENAI_METADATA_API_VERSION}", headers())
    if status == 200:
        return ok(name, f"{endpoint} models readable with this identity (metadata only)")
    if status in (401, 403):
        return fail(name, "NAMING_ACCESS_DENIED", f"{endpoint}: HTTP {status}")
    return fail(name, "NAMING_DEPLOYMENT_UNREACHABLE", f"{endpoint}: HTTP {status}")


def naming_account(endpoint: str) -> str:
    from urllib.parse import urlparse

    return (urlparse(endpoint).hostname or "").split(".", 1)[0]


def check_naming_deployment(endpoint: str | None, deployment: str | None, subscription_id: str | None,
                            resource_group: str | None, headers: Callable[[], dict[str, str]] | None, *,
                            get: HttpGet = http_get) -> Check:
    """Read-only ARM GET of Microsoft.CognitiveServices/accounts/deployments. Confirms the deployment name."""
    from urllib.parse import quote

    name = "naming_deployment"
    if (early := _naming_input(name, endpoint, deployment)) is not None:
        return early
    if not (subscription_id and resource_group):
        return skip(name, "no --subscription-id and --naming-resource-group (or --resource-group)")
    if headers is None:
        return skip(name, "needs a signed-in --tenant-id")
    account = naming_account(endpoint)
    url = (f"https://management.azure.com/subscriptions/{quote(subscription_id, safe='')}/resourceGroups/"
           f"{quote(resource_group, safe='')}/providers/Microsoft.CognitiveServices/accounts/"
           f"{quote(account, safe='')}/deployments/{quote(deployment, safe='')}"
           f"?api-version={COGNITIVE_ARM_API_VERSION}")
    status, body = get(url, headers())
    if status == 200:
        try:
            props = json.loads(body).get("properties") or {}
        except ValueError:
            props = {}
        model = props.get("model") or {}
        detail = f"{account}/{deployment}: {model.get('name', '?')} {model.get('version', '')}".rstrip()
        state = props.get("provisioningState")
        if state and state != "Succeeded":
            return fail(name, "NAMING_DEPLOYMENT_NOT_READY", f"{detail}, provisioningState {state}")
        return ok(name, detail, model_name=model.get("name"), model_version=model.get("version"))
    if status in (401, 403):
        return fail(name, "NAMING_ARM_ACCESS_DENIED", f"{account}/{deployment}: HTTP {status}")
    if status == 404:
        try:
            code = (json.loads(body).get("error") or {}).get("code", "")
        except ValueError:
            code = ""
        if code in ("ResourceGroupNotFound", "SubscriptionNotFound", "ParentResourceNotFound"):
            return fail(name, "NAMING_ACCOUNT_NOT_FOUND", f"{account} in {resource_group}: {code or 'HTTP 404'}")
        return fail(name, "NAMING_DEPLOYMENT_NOT_FOUND", f"{deployment} not found on {account}")
    return fail(name, "ARM_REQUEST_FAILED", f"{account}/{deployment}: HTTP {status}")


MODEL_CURRENT = ("GenerallyAvailable", "Preview")
MODEL_AGING = ("Deprecating", "Legacy")


def model_entries(payload: Any) -> list[dict[str, Any]]:
    """Flatten ARM model lists: the account list is flat, the location list nests each entry under `model`."""
    rows = payload.get("value") if isinstance(payload, dict) else None
    entries = []
    for row in rows if isinstance(rows, list) else []:
        entry = row.get("model") if isinstance(row, dict) and isinstance(row.get("model"), dict) else row
        if isinstance(entry, dict) and entry.get("name"):
            entries.append(entry)
    return entries


def find_model(entries: list[dict[str, Any]], name: str | None, version: str | None,
               label: str | None = None) -> dict[str, Any] | None:
    """Match the deployment's name and version; otherwise read --naming-model as `<name>-<version>` or `<name>`."""
    if name and version:
        return next((e for e in entries if e.get("name") == name and e.get("version") == version), None)
    if label:
        exact = next((e for e in entries if f"{e.get('name')}-{e.get('version')}" == label), None)
        return exact or next((e for e in entries if e.get("name") == label and e.get("isDefaultVersion")), None)
    return None


def classify_model(entry: dict[str, Any], *, now: str | None = None) -> Check:
    """GA/Preview pass; Deprecating/Legacy warn (Azure refuses new deployments); Deprecated or past retirement fail."""
    from datetime import datetime, timezone

    name = "naming_model_lifecycle"
    status = entry.get("lifecycleStatus") or "unknown"
    retires = (entry.get("deprecation") or {}).get("inference")
    label = f"{entry.get('name')} {entry.get('version')}: {status}"
    detail = f"{label}, inference retires {retires[:10]}" if isinstance(retires, str) else label
    today = now or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if status in ("Deprecated", "Retired") or (isinstance(retires, str) and retires[:10] <= today):
        return fail(name, "NAMING_MODEL_RETIRED", detail)
    if status in MODEL_CURRENT:
        return ok(name, detail)
    if status in MODEL_AGING:
        return ok(name, detail, warning=f"{status} models can't be newly deployed; choose a GenerallyAvailable model")
    return ok(name, detail, warning=f"unrecognized lifecycle status {status}")


def check_naming_model_lifecycle(endpoint: str | None, deployment: str | None, subscription_id: str | None,
                                 resource_group: str | None, headers: Callable[[], dict[str, str]] | None, *,
                                 model: tuple[str | None, str | None] = (None, None), label: str | None = None,
                                 get: HttpGet = http_get, now: str | None = None) -> Check:
    """Read-only ARM GET of the account's model list, next to the quota check: is the naming model still deployable?"""
    from urllib.parse import quote

    name = "naming_model_lifecycle"
    if (early := _naming_input(name, endpoint, deployment)) is not None:
        return early
    if not (subscription_id and resource_group):
        return skip(name, "no --subscription-id and --naming-resource-group (or --resource-group)")
    if headers is None:
        return skip(name, "needs a signed-in --tenant-id")
    if not (all(model) or label):
        return skip(name, "model unknown: the deployment didn't resolve and there's no --naming-model")
    account = naming_account(endpoint)
    url = (f"https://management.azure.com/subscriptions/{quote(subscription_id, safe='')}/resourceGroups/"
           f"{quote(resource_group, safe='')}/providers/Microsoft.CognitiveServices/accounts/"
           f"{quote(account, safe='')}/models?api-version={COGNITIVE_ARM_API_VERSION}")
    status, body = get(url, headers())
    if status in (401, 403):
        return fail(name, "NAMING_ARM_ACCESS_DENIED", f"{account} models: HTTP {status}")
    if status != 200:
        return fail(name, "ARM_REQUEST_FAILED", f"{account} models: HTTP {status}")
    try:
        entries = model_entries(json.loads(body))
    except ValueError:
        entries = []
    entry = find_model(entries, *model, label=label)
    if entry is None:
        wanted = " ".join(filter(None, model)) or label
        return skip(name, f"{wanted} isn't in {account}'s model list")
    return classify_model(entry, now=now)
