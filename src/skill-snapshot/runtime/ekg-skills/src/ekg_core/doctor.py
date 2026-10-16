"""Read-only operator-environment checks shared by every ekg-skills CLI.

``doctor`` never signs in, never writes to Azure or disk, and sends no completions or
embeddings (the model checks only list models and read deployment metadata). A check
that lacks its input reports ``skip``. ``preflight``, ``inspect`` and ``rbac-check`` check
resources; ``doctor`` checks the operator's environment.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from . import package_version
from . import grounding
from .az_identity import IdentityError, az_executable, az_json
from .az_identity import _rest_query_as_parameters as _rest_query
from .cli import next_step as _next_step
from .descriptors import descriptor_name, resolve_current

ARM = "https://management.azure.com"
SEARCH_RESOURCE = "https://search.azure.com"
SEARCH_API_VERSION = "2024-07-01"
GROUNDING_API_VERSION = "2026-08-01-preview"
OPENAI_API_VERSION = "2024-10-01"
OPENAI_RESOURCE = "https://ai.azure.com"
_AUTH_DENIED = ("401", "403", "forbidden", "unauthorized", "permissiondenied",
                "authorizationfailed")
MIN_PYTHON = (3, 12)
# Build journal states whose Azure outcome is not yet known: reconcile before anything else.
BUILD_UNSETTLED = {"attempt_requested", "staging", "indexing", "synchronizing", "failed"}

Runner = Callable[..., Any]


def _check(check_id: str, status: str, detail: str, code: str | None = None,
           **extra: Any) -> dict[str, Any]:
    item = {"id": check_id, "status": status, "detail": detail}
    if code:
        item["error_code"] = code
    item.update({key: value for key, value in extra.items() if value is not None})
    return item


def _version_tuple(value: str) -> tuple[int, ...] | None:
    parts = re.findall(r"\d+", value or "")
    return tuple(int(part) for part in parts[:3]) if parts else None


def plugin_manifest(start: Path | None = None) -> Path | None:
    roots = [os.environ.get(name) for name in ("CLAUDE_PLUGIN_ROOT", "PLUGIN_ROOT")]
    candidates = [Path(root) for root in roots if root]
    here = (start or Path(__file__)).resolve()
    candidates.extend(here.parents)
    # uv-installed CLIs live outside the plugin; Copilot CLI installs plugins here.
    if start is None:
        candidates.append(Path.home() / ".copilot" / "installed-plugins" / "ekg-skills"
                          / "ekg-skills")
    for folder in candidates:
        for path in (folder / "plugin.json", folder / ".claude-plugin" / "plugin.json"):
            if path.is_file():
                return path
    return None


def check_cli_version(manifest: Path | None = None) -> dict[str, Any]:
    installed = package_version()
    manifest = manifest or plugin_manifest()
    if manifest is None:
        return _check("cli_version", "ok", f"{installed}; the ekg-skills plugin is not "
                      "installed in Copilot CLI here, so its version was not compared",
                      version=installed)
    try:
        expected = str(json.loads(manifest.read_text(encoding="utf-8")).get("version", ""))
    except (OSError, ValueError):
        return _check("cli_version", "ok", f"{installed}; {manifest} is unreadable",
                      version=installed)
    have, want = _version_tuple(installed), _version_tuple(expected)
    warning = None
    if installed == "checkout":
        detail = f"running from a source checkout; plugin.json says {expected}"
    elif have is not None and want is not None and have < want:
        detail = f"{installed} is older than plugin.json {expected}"
        warning = (f"CLI {installed} is older than plugin {expected}; reinstall with "
                   "`uv tool install --force <plugin-root>`")
    else:
        detail = f"{installed} (plugin.json {expected})"
    return _check("cli_version", "ok", detail, version=installed, plugin_version=expected,
                  warning=warning)


def check_python(version: tuple[int, ...] | None = None) -> dict[str, Any]:
    version = tuple(version or sys.version_info[:3])
    text = ".".join(str(part) for part in version)
    if version[:2] >= MIN_PYTHON:
        return _check("python", "ok", f"Python {text}")
    return _check("python", "fail", f"Python {text} is older than 3.12", "DOCTOR_PYTHON")


def check_uv(which: Callable[[str], str | None] | None = None) -> dict[str, Any]:
    path = (which or shutil.which)("uv")
    if path:
        return _check("uv", "ok", f"uv at {path}")
    return _check("uv", "fail", "uv is not on PATH", "DOCTOR_UV")


def check_azure_signin(tenant_id: str | None, runner: Runner) -> dict[str, Any]:
    if not tenant_id:
        return _check("azure_signin", "skip", "no --tenant-id; sign-in not checked")
    try:
        account = az_json(["account", "show"], runner=runner)
    except IdentityError:
        return _check("azure_signin", "fail",
                      f"no active Azure CLI sign-in for tenant {tenant_id}",
                      "DOCTOR_AZURE_SIGNIN")
    active = str((account or {}).get("tenantId", "")) if isinstance(account, dict) else ""
    if active.lower() != tenant_id.lower():
        return _check("azure_signin", "fail",
                      f"active tenant {active or 'unknown'} is not --tenant-id {tenant_id}",
                      "DOCTOR_AZURE_SIGNIN", active_tenant=active or None)
    return _check("azure_signin", "ok", f"signed in to tenant {active}",
                  active_tenant=active, subscription=account.get("id"))


def _existing(path: Path) -> Path | None:
    for folder in (path, *path.parents):
        if folder.exists():
            return folder
    return None


def check_state_dir(state_dir: str | Path | None) -> dict[str, Any]:
    if not state_dir:
        return _check("state_dir", "skip", "no state folder or journal given")
    folder = Path(state_dir).expanduser()
    base = _existing(folder)
    if base is None or not base.is_dir() or not os.access(base, os.W_OK | os.X_OK):
        return _check("state_dir", "fail", f"{folder} is not writable", "DOCTOR_STATE_DIR")
    leftovers = sorted(p.name for p in folder.glob("*.tmp")) if folder.is_dir() else []
    if leftovers:
        return _check("state_dir", "fail",
                      f"{folder} has partial writes ({', '.join(leftovers[:3])}); another "
                      "command may be running or one was interrupted", "DOCTOR_STATE_DIR")
    where = folder if folder.exists() else f"{folder} (created on first write under {base})"
    return _check("state_dir", "ok", f"{where} is writable and no write is in progress")


def check_build_journal(journal: str | None) -> dict[str, Any]:
    if not journal:
        return _check("journal", "skip", "no --build-journal given")
    path = Path(journal).expanduser()
    problems: list[tuple[str, str]] = []
    if path.is_file():
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return _check("journal", "fail", f"{path} is not readable JSON", "DOCTOR_JOURNAL",
                          journal_verb="status")
        state = record.get("state") if isinstance(record, dict) else None
        if state in BUILD_UNSETTLED:
            problems.append((f"build journal state is {state}; the outcome is not settled",
                             "reconcile"))
    for update in sorted(path.parent.glob("update-plan-*.json")) if path.parent.is_dir() else ():
        try:
            record = json.loads(update.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        state = record.get("state")
        if state not in (None, "published"):
            verb = ("plan" if state == "inconsistent" else
                    f"update --plan-id {update.stem} --confirm-writes")
            problems.append((f"update {update.stem} stopped in state {state}", verb))
    if problems:
        detail, verb = problems[0]
        return _check("journal", "fail", detail, "DOCTOR_JOURNAL", journal_verb=verb)
    if not path.exists():
        return _check("journal", "ok", f"{path} does not exist yet; nothing unsettled")
    return _check("journal", "ok", "no unknown-outcome entries; nothing to reconcile")


def check_provision_journal(state_dir: str | Path | None) -> dict[str, Any]:
    folder = Path(state_dir or Path.cwd() / ".ekg" / "provision-runs").expanduser()
    if not folder.is_dir():
        return _check("journal", "ok", f"{folder} has no provisioning runs yet")
    for path in sorted(folder.glob("*.json")):
        if not re.fullmatch(r"[0-9a-f]{32}", path.stem):
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            operations = record["operations"]
        except (OSError, ValueError, KeyError, TypeError):
            return _check("journal", "fail", f"{path.name} is not a readable run record",
                          "DOCTOR_JOURNAL", journal_verb="inspect")
        uncertain = [key for key, item in operations.items() if item.get("status") == "uncertain"]
        interrupted = "finished_at" not in record and any(
            item.get("status") == "pending" for item in operations.values())
        if uncertain or interrupted:
            what = (f"operation {uncertain[0]} has an unknown outcome" if uncertain else
                    "the run stopped before finishing")
            return _check("journal", "fail", f"run {path.stem}: {what}", "DOCTOR_JOURNAL",
                          journal_verb="inspect", run_id=path.stem)
    return _check("journal", "ok", "no unknown-outcome operations in provisioning runs")


def read_descriptor(path: str | None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    from .validation import validate_deployment_descriptor
    if not path:
        return None, _check("descriptor", "skip", "no --descriptor given")
    file = Path(path).expanduser()
    try:
        if file.stat().st_size > 1024 * 1024:
            raise ValueError("larger than 1 MiB")
        value = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return None, _check("descriptor", "fail", f"{file} is not readable JSON ({error})",
                            "DOCTOR_DESCRIPTOR")
    errors = validate_deployment_descriptor(value)
    if errors:
        return None, _check("descriptor", "fail", f"{file}: {errors[0]}", "DOCTOR_DESCRIPTOR")
    return value, _check("descriptor", "ok", f"{file} has the known descriptor shape "
                         f"(build {value['build_id']})")


def check_search_reader(endpoint: str | None, index: str | None, signed_in: bool,
                        runner: Runner) -> dict[str, Any]:
    if not endpoint or not index:
        return _check("search_reader", "skip", "no Search endpoint and index to probe")
    if not signed_in:
        return _check("search_reader", "skip", "Azure sign-in not verified")
    url = (f"{endpoint.rstrip('/')}/indexes/{quote(index, safe='')}/docs"
           f"?api-version={SEARCH_API_VERSION}&search=*&$top=0")
    try:
        az_json(["rest", "--method", "get", "--url", url, "--resource", SEARCH_RESOURCE],
                runner=runner)
    except IdentityError:
        return _check("search_reader", "fail", f"cannot read index {index}",
                      "DOCTOR_SEARCH_READER")
    return _check("search_reader", "ok", f"can read index {index}")


def _search_get(url: str, runner: Runner) -> tuple[Any, int | None]:
    """(json, None) on success, else (None, 403/404/None) classified from stderr, not echoed."""
    arguments = _rest_query(["rest", "--method", "get", "--url", url,
                             "--resource", SEARCH_RESOURCE])
    try:
        done = runner([az_executable(runner), *arguments, "--output", "json"],
                      capture_output=True, text=True, timeout=30, check=False)
    except (IdentityError, OSError, subprocess.TimeoutExpired):
        return None, None
    if done.returncode != 0:
        error = (done.stderr or "").lower()
        if any(marker in error for marker in ("403", "forbidden", "authorizationfailed",
                                              "permissiondenied")):
            return None, 403
        return None, 404 if any(m in error for m in ("404", "notfound", "not found")) else None
    try:
        return json.loads(done.stdout), None
    except ValueError:
        return None, None


def check_grounding_index(endpoint: str | None, index: str | None, signed_in: bool,
                          runner: Runner, graph_name: str | None = None) -> dict[str, Any]:
    if not index:
        return _check("grounding_index", "skip", "no grounding index to check")
    if not endpoint:
        return _check("grounding_index", "skip", "no Search endpoint to check it on")
    if not signed_in:
        return _check("grounding_index", "skip", "Azure sign-in not verified")
    invalid = grounding.name_blocker(index)
    if invalid:
        return _check("grounding_index", "fail", invalid, "DOCTOR_GROUNDING_INDEX")
    # Path form, not indexes('x'): cmd.exe rejects unquoted parentheses when az is a .cmd shim.
    url = (f"{endpoint.rstrip('/')}/indexes/{quote(index, safe='')}"
           f"?api-version={GROUNDING_API_VERSION}")
    definition, status = _search_get(url, runner)
    if status == 403 or status == 404:
        blocker = grounding.classify(index, None, status=status)
        return _check("grounding_index", "fail", blocker,
                      "GROUNDING_INDEX_UNREADABLE" if status == 403
                      else "GROUNDING_INDEX_NOT_FOUND")
    if definition is None:
        return _check("grounding_index", "fail",
                      f"cannot read index {index}: check the Search endpoint, sign-in and "
                      "that the identity has Search Index Data Reader and Reader on the "
                      "Search service", "DOCTOR_GROUNDING_INDEX")
    blocker = grounding.classify(index, definition if isinstance(definition, dict) else None)
    if blocker:
        return _check("grounding_index", "fail", blocker, "DOCTOR_GROUNDING_INDEX")
    detail = f"index {index} has an {grounding.PROFILE_KIND} graph profile"
    try:
        rows = _grounding_rows(endpoint, index, graph_name, runner)
    except PermissionError:
        return _check("grounding_index", "fail", grounding.classify(index, None, status=403),
                      "GROUNDING_INDEX_UNREADABLE")
    if rows is None:
        return _check("grounding_index", "ok", detail,
                      warning="could not count rows; label rows and graph_name are unchecked")
    names, labels, label_names = rows
    shown = ", ".join(sorted(names)) or "none"
    if labels == 0:
        return _check("grounding_index", "fail",
                      f"{detail}, but it has no label rows (predicate rdfs:label or "
                      f"skos:altLabel with subject_id); graph_names present: {shown}",
                      "DOCTOR_GROUNDING_INDEX", graph_names=sorted(names))
    if graph_name and graph_name not in label_names:
        return _check("grounding_index", "fail",
                      f"{detail}, but no label rows have graph_name {graph_name}; label rows "
                      f"are under: {', '.join(sorted(label_names)) or 'none'}",
                      "DOCTOR_GROUNDING_INDEX", graph_names=sorted(names))
    return _check("grounding_index", "ok",
                  f"{detail}; {labels} label rows; graph_names: {shown}",
                  graph_names=sorted(names))


def _grounding_rows(endpoint: str, index: str, graph_name: str | None,
                    runner: Runner) -> tuple[dict[str, int], int, dict[str, int]] | None:
    """(graph_names, label row count, label graph_names) from read-only filtered counts."""
    base = (f"{endpoint.rstrip('/')}/indexes/{quote(index, safe='')}/docs"
            f"?api-version={GROUNDING_API_VERSION}&search=*&$top=0&$count=true"
            "&facet=graph_name,count:200")
    labels = " or ".join(f"predicate eq '{item}'" for item in grounding.LABEL_PREDICATES)

    def read(extra: str = "") -> dict[str, Any]:
        value = None
        for url in (base + extra, base.split("&facet=")[0] + extra):
            value, status = _search_get(url, runner)
            if status == 403:
                raise PermissionError("denied")
            if value is not None:
                break
        if not isinstance(value, dict):
            raise IdentityError("unexpected response")
        return value

    def facet(value: dict[str, Any]) -> dict[str, int]:
        items = (value.get("@search.facets") or {}).get("graph_name") or []
        return {item["value"]: item.get("count", 0) for item in items
                if isinstance(item, dict) and item.get("value")}

    try:
        names = facet(read())
        found = read("&$filter=" + quote(labels, safe=""))
        label_names = facet(found)
        if graph_name and not label_names and found.get("@odata.count"):
            # graph_name is not facetable in this index: ask for the exact value instead.
            exact = read("&$filter=" + quote(f"graph_name eq '{graph_name}' and ({labels})",
                                             safe=""))
            label_names = {graph_name: exact.get("@odata.count", 0)} if exact.get(
                "@odata.count") else {}
        return names, int(found.get("@odata.count") or 0), label_names
    except (IdentityError, KeyError, TypeError, ValueError):
        return None


def check_model_data_plane(endpoint: str | None, resource_id: str | None, signed_in: bool,
                            runner: Runner) -> dict[str, Any]:
    """List models on the data plane with the caller's Entra token (no completion, no spend).

    Success proves only model-list access for this caller, not inference or a named role."""
    if not endpoint:
        return _check("model_data_plane", "skip", "no --openai-endpoint or descriptor endpoint")
    if not signed_in:
        return _check("model_data_plane", "skip", "Azure sign-in not verified")
    scope = resource_id or "<openai-resource-id>"
    if not endpoint.startswith("https://"):
        return _check("model_data_plane", "fail", "OpenAI endpoint must be https",
                      "DOCTOR_MODEL_ENDPOINT")
    url = f"{endpoint.rstrip('/')}/openai/v1/models"
    try:
        done = runner([az_executable(runner), "rest", "--method", "get", "--url", url,
                       "--resource", OPENAI_RESOURCE, "--output", "json"],
                      capture_output=True, text=True, timeout=30, check=False)
    except (IdentityError, OSError, subprocess.TimeoutExpired):
        return _check("model_data_plane", "fail", "cannot reach the OpenAI endpoint",
                      "DOCTOR_MODEL_ENDPOINT")
    if done.returncode == 0:
        return _check("model_data_plane", "ok", "can list models with your Entra token; "
                      "inference permissions and the Search identity's access remain unverified "
                      "(no completion sent)")
    # Classify from stderr without echoing it: it may hold account details.
    if any(marker in (done.stderr or "").lower() for marker in _AUTH_DENIED):
        return _check("model_data_plane", "fail", "model listing was denied for this caller; "
                      "this does not establish a missing role", "DOCTOR_MODEL_ROLE", scope=scope)
    return _check("model_data_plane", "fail", "cannot reach the OpenAI endpoint",
                  "DOCTOR_MODEL_ENDPOINT")


def check_model_deployment(resource_id: str | None, deployment: str | None, signed_in: bool,
                           runner: Runner) -> dict[str, Any]:
    if not resource_id or not deployment:
        return _check("model_deployment", "skip", "subscription/resource unknown: no "
                      "--openai-resource-id and deployment")
    if not signed_in:
        return _check("model_deployment", "skip", "Azure sign-in not verified")
    url = (f"{ARM}{resource_id.rstrip('/')}/deployments/{quote(deployment, safe='')}"
           f"?api-version={OPENAI_API_VERSION}")
    try:
        found = az_json(["rest", "--method", "get", "--url", url], runner=runner)
    except IdentityError:
        return _check("model_deployment", "fail", f"deployment {deployment} was not found",
                      "DOCTOR_MODEL_DEPLOYMENT")
    state = ((found or {}).get("properties") or {}).get("provisioningState")
    if state and state != "Succeeded":
        return _check("model_deployment", "fail", f"deployment {deployment} is {state}",
                      "DOCTOR_MODEL_DEPLOYMENT")
    return _check("model_deployment", "ok", f"deployment {deployment} exists (metadata only)")


def doctor(prog: str, *, tenant_id: str | None = None, state_dir: str | None = None,
           build_journal: str | None = None, provision_journal: bool = False,
           descriptor: str | None = None, search_endpoint: str | None = None,
           index: str | None = None, openai_resource_id: str | None = None,
           deployment: str | None = None, openai_endpoint: str | None = None,
           grounding_index: str | None = None, grounding_graph_name: str | None = None,
           runner: Runner = subprocess.run) -> dict[str, Any]:
    checks = [check_cli_version(), check_python(), check_uv()]
    signin = check_azure_signin(tenant_id, runner)
    checks.append(signin)
    checks.append(check_state_dir(state_dir))
    if provision_journal:
        checks.append(check_provision_journal(state_dir))
    else:
        checks.append(check_build_journal(build_journal))
    served, described = read_descriptor(descriptor)
    if prog != "ekg-provision":
        checks.append(described)
    endpoints = (served or {}).get("endpoints") or {}
    signed_in = signin["status"] == "ok"
    checks.append(check_search_reader(search_endpoint or endpoints.get("search"),
                                      index or endpoints.get("content_index"), signed_in,
                                      runner))
    checks.append(check_grounding_index(search_endpoint or endpoints.get("search"),
                                        grounding_index, signed_in, runner,
                                        graph_name=grounding_graph_name))
    checks.append(check_model_data_plane(openai_endpoint or endpoints.get("openai"),
                                         openai_resource_id, signed_in, runner))
    checks.append(check_model_deployment(openai_resource_id, deployment, signed_in, runner))
    failed = next((item for item in checks if item["status"] == "fail"), None)
    result: dict[str, Any] = {"status": "blocked" if failed else "ok", "tenant_id": tenant_id,
                              "checks": checks}
    if failed:
        result.update(error_code=failed["error_code"], error=failed["detail"],
                      next_step=_next_step(failed["error_code"], prog=prog, command="doctor",
                                           journal_verb=failed.get("journal_verb"),
                                           scope=failed.get("scope")))
    else:
        result["next_step"] = ("Environment is ready; continue with the skill's workflow."
                               if all(c["status"] == "ok" for c in checks) else
                               "Environment is ready for what was checked; pass --tenant-id "
                               "and your inputs to check the rest.")
    warnings = [item["warning"] for item in checks if item.get("warning")]
    if warnings:
        result["warnings"] = warnings
    return result


def render(result: dict[str, Any]) -> list[str]:
    tenant = result.get("tenant_id")
    lines = [f"Tenant: {tenant}" if tenant else "Tenant: none given (Azure checks skipped)"]
    marks = {"ok": "ok  ", "fail": "FAIL", "skip": "skip"}
    for item in result["checks"]:
        line = f"{marks[item['status']]} {item['id']}: {item['detail']}"
        if item.get("warning"):
            line += f" (warning: {item['warning']})"
        lines.append(line)
    lines.append(f"next_step: {result['next_step']}")
    return lines


def add_arguments(parser: Any, *, build: bool = False, provision: bool = False) -> None:
    """Doctor inputs; every one is optional so doctor runs before any config exists."""
    parser.add_argument("--tenant-id", help="tenant to compare with the active az sign-in")
    if provision:
        parser.add_argument("--state-dir", help="provisioning journal folder "
                            "(default ./.ekg/provision-runs)")
    if build:
        parser.add_argument("--build-journal", help="build journal to check for unsettled runs")
        parser.add_argument("--grounding-index", help="existing grounding index to validate "
                            "read-only (needs --search-endpoint)")
        parser.add_argument("--grounding-graph-name", help="the plan's grounding.graph_name; "
                            "checks the index has label rows under it")
    parser.add_argument("--descriptor", action="append", default=[],
                        help="published descriptor to read and whose index to probe")
    parser.add_argument("--search-endpoint", help="Search endpoint for the reader probe")
    parser.add_argument("--index", help="index for the reader probe (default: descriptor's)")
    parser.add_argument("--openai-endpoint", help="Azure OpenAI/Foundry endpoint for the "
                        "data-plane models-list probe (default: descriptor's)")
    parser.add_argument("--openai-resource-id", help="Azure OpenAI/Foundry account ARM ID")
    parser.add_argument("--chat-deployment", help="deployment whose metadata to read")
    parser.add_argument("--embedding-deployment",
                        help="deployment whose metadata to read when no chat deployment")


def from_args(prog: str, args: Any, *, runner: Runner = subprocess.run) -> dict[str, Any]:
    journal = getattr(args, "build_journal", None)
    state_dir = getattr(args, "state_dir", None)
    provision = prog == "ekg-provision"
    if provision:
        state_dir = state_dir or str(Path.cwd() / ".ekg" / "provision-runs")
    elif journal:
        state_dir = str(Path(journal).expanduser().parent)
    descriptors = getattr(args, "descriptor", None) or []
    if isinstance(descriptors, str):
        descriptors = [descriptors]
    if not descriptors and os.environ.get("EKG_DESCRIPTOR"):
        descriptors = [os.environ["EKG_DESCRIPTOR"]]
    return doctor(prog, tenant_id=getattr(args, "tenant_id", None), state_dir=state_dir,
                  build_journal=journal, provision_journal=provision,
                  descriptor=descriptors[0] if descriptors else None,
                  search_endpoint=getattr(args, "search_endpoint", None),
                  index=getattr(args, "index", None),
                  grounding_index=getattr(args, "grounding_index", None),
                  grounding_graph_name=getattr(args, "grounding_graph_name", None),
                  openai_resource_id=getattr(args, "openai_resource_id", None),
                  openai_endpoint=getattr(args, "openai_endpoint", None),
                  deployment=(getattr(args, "chat_deployment", None)
                              or getattr(args, "embedding_deployment", None)),
                  runner=runner)


def _signed_in(runner: Runner) -> dict[str, str | None]:
    try:
        account = az_json(["account", "show"], runner=runner)
    except Exception:
        account = None
    if not isinstance(account, dict):
        return {"tenant_id": None, "account": None}
    user = account.get("user") if isinstance(account.get("user"), dict) else {}
    return {"tenant_id": account.get("tenantId") or None, "account": user.get("name") or None}


def _current() -> dict[str, str] | None:
    try:
        path = resolve_current()
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    ident = (value.get("build_id") or value.get("deployment_id")
             if isinstance(value, dict) else None) or descriptor_name(value)
    return {"kind": "descriptor", "path": str(path), "id": str(ident)}


def contract(result: dict[str, Any], *, runner: Runner = subprocess.run) -> dict[str, Any]:
    """The stable, documented `doctor --json` shape (docs/contract.md)."""
    checks = []
    for item in result["checks"]:
        status = {"ok": "pass", "fail": "fail"}.get(item["status"], "warn")
        if status == "pass" and item.get("warning"):
            status = "warn"
        detail = item["detail"] + (f" (warning: {item['warning']})"
                                   if item.get("warning") else "")
        checks.append({"name": item["id"], "status": status, "detail": detail})
    return {
        "plugin": "ekg-skills",
        "version": package_version(),
        "ready": result["status"] == "ok",
        "signed_in": _signed_in(runner),
        "current": _current(),
        "checks": checks,
        "next_step": result["next_step"],
    }


def run(prog: str, args: Any, *, runner: Runner = subprocess.run) -> None:
    result = from_args(prog, args, runner=runner)
    if getattr(args, "json", False):
        # Agents read the shape, not the exit code; not-ready is still a successful read.
        print(json.dumps(contract(result, runner=runner), indent=2))
        return
    print("\n".join(render(result)))
    if result["status"] != "ok":
        raise SystemExit(2)
