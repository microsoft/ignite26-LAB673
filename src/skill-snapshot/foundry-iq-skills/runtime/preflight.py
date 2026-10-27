"""Read-only graph-demo prerequisites; setup and live source inspection are explicit."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
DOMAINS = ("ekg", "grz", "ontology")
OPTIONAL_APPS = {"ekg-apps", "grz-mcp", "ontology-apps"}
TIMEOUT = 60
NATIVE_NEXT = (
    "GRZBuildPoc 0.1.4-local trusted distribution location is unresolved (release blocker). "
    "Obtain the pinned host binary through an operator-approved trusted channel, then pass "
    "--native-binary with its absolute path. No download or checksum override is offered."
)
SOURCE_NEXT = (
    "Search owns the generated EKG schema; schema_org does not guarantee GRZ compatibility. "
    "As soon as the physical content index exists, explicitly inspect it with --inspect-source "
    "and the GRZ source flags before advancing the demo or GRZ planning. Managed ingestion may "
    "already be running; this check does not pause or cancel it. Keep the original EKG descriptor "
    "authoritative. New GRZ plans default to --source-compatibility auto: direct when supported, "
    "otherwise an eligible source needs an explicitly planned and approved faithful compatibility "
    "snapshot. Eligibility is not native-original readiness or copy authorization. Off must fail "
    "closed on unsupported originals. Never change the native executable/pins, fake metadata, "
    "silently copy, or rewrite historical plans. The explicit captured-input alternative uses "
    "plan --capture-source --capture-coverage with separately authorized source reads/local "
    "capture, not a producer freeze or atomic Azure snapshot. Preflight never captures input; "
    "apply must use the exact retained artifact without recapture. Cloud writes, native execution "
    "and publication retain their separate exact approval gates."
)
SOURCE_FLAGS = {
    "--tenant-id", "--subscription-id", "--resource-group", "--search-service",
    "--source-index", "--key-field", "--text-field", "--source-field", "--vector-field",
    "--embedding-model-id", "--dataset", "--owner-approval", "--frozen-evidence",
    "--security-inspection", "--security-field", "--source-visibility",
}

# Reuse the pinned wheel's policies, without starting native code or constructing write/state services.
NATIVE_CODE = """
import json,sys
from pathlib import Path
from grz_adapters.native_runner import NativeRunner,NATIVE_BINARY_SHA256_BY_RID,get_host_rid
try:
    selected = sys.argv[1] or None
    if selected and (not Path(selected).is_absolute() or not Path(selected).is_file()):
        raise ValueError('Explicit native binary must be an existing absolute file; no fallback.')
    path = NativeRunner(binary_path=selected).resolve_and_verify()
    if selected and path != Path(selected).resolve():
        raise ValueError('Explicit native binary was not selected; no fallback.')
    sha = NATIVE_BINARY_SHA256_BY_RID[get_host_rid()]
    print(json.dumps({'status':'ready','path':str(path),'sha256':sha,'rid':get_host_rid()}))
except Exception as exc:
    print(json.dumps({'status':'blocked','error_code':getattr(exc,'code',type(exc).__name__),'detail':str(exc)}))
    sys.exit(1)
"""
SOURCE_CODE = """
import json,sys
from grz_build.cli import _parser,LIVE_REQUIRED
from grz_build.live import create_live_store
try:
    requested_mode = sys.argv[1]
    parser = _parser()
    supports_compatibility = '--source-compatibility' in parser._option_string_actions
    options = ['--source-compatibility',requested_mode] if supports_compatibility else []
    args = parser.parse_args([*sys.argv[2:],*options,'inspect'])
    missing = [name for name in LIVE_REQUIRED if not getattr(args,name)]
    if missing:
        raise ValueError('Missing explicit source flags: '+', '.join(missing))
    store,source,_ = create_live_store(args)
    observed = store.inspect(source)
    compatibility = observed.get('source_compatibility')
    if not supports_compatibility or (requested_mode == 'off' and compatibility is None):
        compatibility = {'version':'grz-source-compatibility-v1',
            'requested_mode':requested_mode,'resolved_mode':'direct',
            'native_direct_supported':True,'export_strategy':'keyset','max_export_documents':None}
    if not isinstance(compatibility,dict):
        raise ValueError('Runtime inspection omitted source_compatibility; no readiness inferred.')
    status = 'conditional' if compatibility.get('resolved_mode') == 'snapshot-copy' else 'verified'
    print(json.dumps({'status':status,'source_index':source.index,
        'definition_fingerprint':observed['definition_fingerprint'],
        'source_binding':store.source_binding(observed),'source_compatibility':compatibility,
        'runtime_contract':'compatibility' if supports_compatibility else 'legacy-direct-only'}))
except Exception as exc:
    code = getattr(exc,'code',type(exc).__name__)
    detail = (str(exc) if getattr(exc,'code',None) or isinstance(exc,ValueError) else
        'Unexpected '+type(exc).__name__+' during source inspection; run the leaf inspect command '
        'with the same source flags for diagnostics. No write or source repair was attempted.')
    if code in {'SOURCE_SCAN_UNSUPPORTED','SOURCE_VECTORS_NOT_RETRIEVABLE','NATIVE_SOURCE_INCOMPATIBLE'}:
        detail = ('The original EKG source failed the pinned GRZ compatibility check ('+code+'). '
            'Direct use is blocked. An eligible compatibility snapshot requires a supporting runtime, '
            'a new explicit plan and exact approval; preflight performs no copy or native change.')
    print(json.dumps({'status':'blocked','error_code':code,
        'detail':detail}))
    sys.exit(1)
"""


def bootstrap_module():
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("demo_bootstrap", ROOT / "bootstrap.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def execute(command: list[str], *, env: dict | None = None, cwd: Path | None = None):
    return subprocess.run(command, env=env, cwd=cwd, capture_output=True, text=True,
                          check=False, timeout=TIMEOUT)


def source_arguments(values: list[str]) -> list[str]:
    if not values or len(values) % 2:
        raise ValueError("--inspect-source requires explicit GRZ global flag/value pairs.")
    seen = set()
    for flag, value in zip(values[::2], values[1::2]):
        if flag not in SOURCE_FLAGS or not value or value.startswith("--"):
            raise ValueError("Only read-only GRZ source flags are accepted; no verbs, state, naming or write flags.")
        if flag in seen and flag != "--security-field":
            raise ValueError(f"Duplicate source flag: {flag}")
        seen.add(flag)
    return values


def validate_source_compatibility(observed: dict, requested_mode: str) -> None:
    compatibility = observed.get("source_compatibility")
    if not isinstance(compatibility, dict) or compatibility.get("requested_mode") != requested_mode:
        raise ValueError("Source inspection omitted or changed the requested compatibility mode.")
    if compatibility.get("version") != "grz-source-compatibility-v1":
        raise ValueError("Unsupported source compatibility contract version.")
    resolved = compatibility.get("resolved_mode")
    if resolved == "direct":
        if (observed["status"] != "verified" or
                compatibility.get("native_direct_supported") is not True or
                compatibility.get("export_strategy") != "keyset"):
            raise ValueError("Direct-source readiness lacks the native direct/keyset contract.")
    elif resolved == "snapshot-copy":
        limit = compatibility.get("max_export_documents")
        if (requested_mode != "auto" or observed["status"] != "conditional" or
                compatibility.get("native_direct_supported") is not False or
                compatibility.get("export_strategy") != "bounded-offset" or
                type(limit) is not int or not 0 < limit <= 100000):
            raise ValueError("Compatibility snapshot eligibility lacks a valid bounded export contract.")
    else:
        raise ValueError("Unknown source compatibility resolution; no readiness inferred.")


def child_check(bootstrap, environment: Path, code: str, arguments: list[str]) -> dict:
    result = execute([str(bootstrap.python_path(environment)), "-I", "-B", "-c", code, *arguments],
                     env=bootstrap.child_env(environment), cwd=environment)
    observed = json.loads(result.stdout)
    expected = "ready" if code == NATIVE_CODE else "verified"
    allowed = {expected, "blocked"} if code == NATIVE_CODE else {"verified", "conditional", "blocked"}
    if not isinstance(observed, dict) or observed.get("status") not in allowed:
        raise ValueError("Invalid prerequisite response.")
    if result.returncode and observed["status"] != "blocked":
        raise ValueError("Prerequisite process failed despite a success response.")
    if observed["status"] != "blocked":
        required = ("path", "sha256", "rid") if expected == "ready" else (
            "source_index", "definition_fingerprint", "source_binding")
        if not all(observed.get(name) for name in required):
            raise ValueError("Prerequisite response lacks verification evidence.")
        if code == SOURCE_CODE:
            validate_source_compatibility(observed, arguments[0])
    return observed


def preflight(native_binary: str | None = None, inspect_source: list[str] | None = None,
              source_compatibility: str = "auto") -> dict:
    if source_compatibility not in {"auto", "off"}:
        raise ValueError("Source compatibility must be auto or off.")
    bootstrap = bootstrap_module()
    runtimes = {}
    environments = {}
    for domain in DOMAINS:
        instruction = f'Run explicit setup: "{sys.executable}" -I "{ROOT / "bootstrap.py"}" setup {domain}'
        checks = {}
        try:
            spec, key, environment = bootstrap.specification(domain)
            bootstrap.verify(spec, key, environment)
            environments[domain] = environment
            for entrypoint in spec["entry_points"]:
                if entrypoint in OPTIONAL_APPS:
                    continue
                try:
                    result = execute([sys.executable, "-I", "-B", str(ROOT / "bootstrap.py"),
                                      "run", domain, entrypoint, "--help"])
                    checks[entrypoint] = {"status": "ready" if result.returncode == 0 else "blocked"}
                    if result.returncode:
                        checks[entrypoint]["detail"] = (result.stderr or result.stdout).strip()
                except (OSError, subprocess.TimeoutExpired) as exc:
                    checks[entrypoint] = {"status": "blocked", "detail": str(exc)}
            status = "ready" if checks and all(c["status"] == "ready" for c in checks.values()) else "blocked"
            runtimes[domain] = {"status": status, "entrypoints": checks}
            if status == "blocked":
                runtimes[domain]["next_step"] = instruction + "; inspect the startup error; preflight never repairs."
        except (bootstrap.RuntimeErrorDetail, OSError, ValueError, KeyError, TypeError) as exc:
            runtimes[domain] = {"status": "blocked", "detail": str(exc), "next_step": instruction}

    native = {"status": "blocked", "detail": "GRZ runtime must pass before its pinned resolver can be loaded."}
    if runtimes["grz"]["status"] == "ready":
        try:
            native = child_check(bootstrap, environments["grz"], NATIVE_CODE, [native_binary or ""])
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            native = {"status": "blocked", "detail": str(exc)}
    native["distribution"] = "unresolved"
    native["next_step"] = NATIVE_NEXT if native["status"] != "ready" else (
        "Retain this exact path through GRZ --native-binary; recheck after any runtime or binary change. "
        "Operator-supplied binary passed; release-wide trusted distribution is still unresolved."
    )
    local_ready = all(r["status"] == "ready" for r in runtimes.values()) and native["status"] == "ready"
    source = {"status": "unknown", "requested_mode": source_compatibility, "next_step": SOURCE_NEXT}
    if inspect_source is not None:
        try:
            arguments = source_arguments(inspect_source)
            if not local_ready:
                raise ValueError("Local prerequisites failed; no source/authentication request was made.")
            source = child_check(bootstrap, environments["grz"], SOURCE_CODE,
                                 [source_compatibility, *arguments])
            source["next_step"] = (
                "Retain this exact physical index, mapping and freeze evidence; leaf inspect must recheck at handoff. "
                "This is source compatibility, not build, model, quota or write approval."
                if source["status"] == "verified" else (
                    "Snapshot-copy eligible, not native-original-ready. Review a new GRZ plan binding the "
                    "original source/fingerprints, faithful content and persistent manifest digests, "
                    "copy index/schema and separate upload/storage estimates, "
                    "native input and lifecycle. Wait for exact approval before create/upload; verify copy parity "
                    "before native execution. No automatic cleanup or historical-plan changes."
                    if source["status"] == "conditional" else SOURCE_NEXT
                )
            )
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            source = {"status": "blocked", "detail": str(exc), "next_step": SOURCE_NEXT}
    blocked = not local_ready or source["status"] == "blocked"
    status = "blocked" if blocked else ("ready" if source["status"] == "verified" else "conditional")
    return {
        "schema_version": 1, "route": "graph-demo", "phase": "prerequisites", "status": status,
        "local_status": "ready" if local_ready else "blocked",
        "runtimes": runtimes, "native": native, "source": source,
        "scope": "Prerequisites only; no Azure write, model readiness, or whole-chain success claim.",
        "exit_code": 1 if blocked else (0 if status == "ready" else 2),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-binary", help="Operator-selected absolute trusted GRZBuildPoc path.")
    parser.add_argument("--source-compatibility", choices=("auto", "off"), default="auto",
                        help="New-plan policy: direct or explicitly approved compatibility snapshot; off requires direct.")
    parser.add_argument("--inspect-source", nargs=argparse.REMAINDER,
                        help="Explicit opt-in to live read-only Azure source inspection; remaining GRZ source flags.")
    args = parser.parse_args(argv)
    try:
        report = preflight(args.native_binary, args.inspect_source, args.source_compatibility)
    except (OSError, ValueError, ImportError, KeyError, TypeError) as exc:
        report = {
            "schema_version": 1, "route": "graph-demo", "phase": "prerequisites",
            "status": "blocked", "exit_code": 1, "error_code": "PREFLIGHT_UNAVAILABLE",
            "detail": str(exc), "next_step": "Reinstall the complete plugin; preflight will not repair it.",
        }
    print(json.dumps(report))
    return report["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
