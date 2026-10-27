"""Explicit setup and installation-free execution of the plugin's pinned wheels."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import venv


ROOT = Path(__file__).resolve().parent


class RuntimeErrorDetail(Exception):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def target_id() -> str:
    machine = platform.machine().lower()
    machine = {"amd64": "x86_64", "arm64": "arm64" if sys.platform == "darwin" else "aarch64"}.get(machine, machine)
    return f"{sys.platform}-{machine}"


def asset(root: Path, record: dict) -> Path:
    relative = Path(record["file"])
    path = (root / relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(root.resolve()):
        raise RuntimeErrorDetail("Runtime asset must be inside the plugin runtime directory.")
    if not path.is_file() or digest(path.read_bytes()) != record["sha256"]:
        raise RuntimeErrorDetail(f"Missing or changed runtime asset: {relative}. Reinstall the complete plugin.")
    return path


def cache_root() -> Path:
    override = os.environ.get("FOUNDRY_IQ_RUNTIME_CACHE")
    if override:
        path = Path(override).expanduser()
        if not path.is_absolute():
            raise RuntimeErrorDetail("FOUNDRY_IQ_RUNTIME_CACHE must be an absolute external cache path.")
    elif os.name == "nt":
        path = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "foundry-iq-skills" / "runtimes"
    else:
        path = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "foundry-iq-skills" / "runtimes"
    path = path.resolve()
    plugin = ROOT.parent.resolve()
    cwd = Path.cwd().resolve()
    project = next((folder for folder in (cwd, *cwd.parents)
                    if (folder / ".git").exists() or (folder / "pyproject.toml").is_file()
                    or (folder / "package.json").is_file()), None)
    if project is None and cwd not in (Path.home().resolve(), Path(cwd.anchor)):
        project = cwd
    if path.is_relative_to(plugin) or (project is not None and path.is_relative_to(project)):
        raise RuntimeErrorDetail("Runtime cache must be outside the plugin and the current project directory.")
    return path


def interpreter_binding(domain: str) -> Path:
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    if manifest["schema_version"] != 1 or domain not in manifest["runtimes"]:
        raise RuntimeErrorDetail(f"Unsupported runtime: {domain}.")
    key = digest(canonical({"runtime": manifest["runtimes"][domain], "target": target_id()}))
    return cache_root() / domain / f"interpreter-{key}.json"


def select_python(action: str, binding: Path) -> Path:
    override = os.environ.get("FOUNDRY_IQ_PYTHON")
    if override:
        selected = Path(override).expanduser()
        if not selected.is_absolute():
            raise RuntimeErrorDetail("FOUNDRY_IQ_PYTHON must be an absolute Python 3.12 executable.")
    elif binding.is_file():
        record = json.loads(binding.read_text(encoding="utf-8"))
        selected = Path(record["executable"])
        if not selected.is_absolute():
            raise RuntimeErrorDetail(f"Invalid interpreter binding: {binding}.")
    elif action != "setup":
        raise RuntimeErrorDetail("Runtime is not prepared: no interpreter binding. Run explicit setup first.")
    elif sys.version_info[:2] == (3, 12):
        selected = Path(sys.executable)
    else:
        raise RuntimeErrorDetail(
            "Setup needs an existing Python 3.12 interpreter. Invoke setup with its absolute executable "
            "or set FOUNDRY_IQ_PYTHON to it; no Python was discovered or installed."
        )
    if not selected.is_file():
        raise RuntimeErrorDetail(f"Selected Python executable is missing: {selected}.")
    return selected.resolve()


def bind_python(binding: Path) -> None:
    binding.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=binding.parent, prefix="interpreter-", suffix=".tmp", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(canonical({"executable": str(Path(sys.executable).resolve()), "version": sys.version}))
    try:
        temporary.replace(binding)
    finally:
        temporary.unlink(missing_ok=True)


def verify_python(selected: Path) -> None:
    code = "import json,sys;print(json.dumps({'executable':sys.executable,'version':list(sys.version_info[:2]),'detail':sys.version}))"
    try:
        result = subprocess.run([str(selected), "-I", "-c", code], text=True, capture_output=True, check=False, timeout=15)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeErrorDetail(f"Selected executable {selected} did not answer its Python probe within 15 seconds.") from exc
    if result.returncode:
        raise RuntimeErrorDetail(
            f"Selected executable {selected} failed its Python probe (exit {result.returncode}): {result.stderr.strip()}"
        )
    info = json.loads(result.stdout)
    if info["version"] != [3, 12] or Path(info["executable"]).resolve() != selected:
        raise RuntimeErrorDetail(
            f"Selected executable {selected} reported executable {info['executable']}, version {info['detail']}. "
            "Select a Python 3.12 interpreter executable, not a launcher or another Python version."
        )


def specification(domain: str) -> tuple[dict, str, Path]:
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    if manifest["schema_version"] != 1 or domain not in manifest["runtimes"]:
        raise RuntimeErrorDetail(f"Unsupported runtime: {domain}.")
    spec = manifest["runtimes"][domain]
    target = target_id()
    if target not in spec["targets"]:
        raise RuntimeErrorDetail(f"No dependency lock is supplied for {target}. Obtain a supported platform build; do not substitute dependency versions.")
    spec = {**{name: value for name, value in spec.items() if name != "targets"}, **spec["targets"][target]}
    asset(ROOT, spec["wheel"])
    asset(ROOT, spec["lock"])
    if sys.version_info[:2] != (3, 12):
        raise RuntimeErrorDetail("Selected interpreter is not Python 3.12; the supplied dependency locks require 3.12.")
    identity = {
        "runtime": spec,
        "python": {
            "version": sys.version,
            "implementation": sys.implementation.name,
            "cache_tag": sys.implementation.cache_tag,
            "platform": sysconfig.get_platform(),
            "machine": platform.machine(),
            "executable": str(Path(sys.executable).resolve()),
        },
    }
    key = digest(canonical(identity))
    return spec, key, cache_root() / domain / key


def python_path(environment: Path) -> Path:
    return environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def child_env(environment: Path) -> dict[str, str]:
    env = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "PIP_TARGET", "PIP_PREFIX", "PIP_USER", "PIP_ROOT"):
        env.pop(name, None)
    # Empty target overrides an inherited pip config without disabling package sources.
    env.update(PIP_TARGET="", PIP_ROOT="", PIP_PREFIX=str(environment), PIP_USER="false", PIP_DISABLE_PIP_VERSION_CHECK="1")
    env["PLUGIN_ROOT"] = str(ROOT.parent)
    return env


def checked(args: list[str], environment: Path, *, capture: bool = False) -> str:
    result = subprocess.run(
        [str(python_path(environment)), "-I", "-B", *args], cwd=environment,
        env=child_env(environment), text=True, capture_output=capture, check=False,
    )
    if result.returncode:
        raise RuntimeErrorDetail(
            "Runtime environment verification or installation failed. "
            "Check the preceding error and your configured package sources; no source fallback was attempted."
            + (f"\n{result.stderr.strip()}" if capture else "")
        )
    return result.stdout if capture else ""


def installed(environment: Path) -> dict:
    return json.loads(checked([
        "-c", "import importlib.metadata as m,json,sys;"
        "print(json.dumps({'prefix':sys.prefix,'packages':{d.metadata['Name']:d.version for d in m.distributions()}}))",
    ], environment, capture=True))


def verify_entrypoints(spec: dict, environment: Path) -> None:
    code = (
        "import importlib.metadata as m,json,sys;"
        "d=m.distribution(sys.argv[1]);"
        "actual={e.name:e.value for e in d.entry_points if e.group=='console_scripts'};"
        "assert actual==json.loads(sys.argv[2]),'Wheel entry points do not match the manifest'"
    )
    checked(["-c", code, spec["wheel"]["name"], json.dumps(spec["entry_points"])], environment)


def verify(spec: dict, key: str, environment: Path) -> None:
    ready = environment / "ready.json"
    instruction = "Run explicit setup with the same cache setting."
    if not ready.is_file() or not python_path(environment).is_file():
        raise RuntimeErrorDetail(f"Runtime is not prepared. {instruction}")
    record = json.loads(ready.read_text(encoding="utf-8"))
    if not isinstance(record, dict):
        raise RuntimeErrorDetail(f"Runtime ready marker must be a JSON object. {instruction}")
    if record.get("key") != key:
        raise RuntimeErrorDetail(f"Runtime ready marker does not match this artifact. {instruction}")
    actual = installed(environment)
    packages = {normalized(name): version for name, version in actual["packages"].items()}
    expected = {normalized(item["name"]): item["version"] for item in spec["dependencies"]}
    expected[normalized(spec["wheel"]["name"])] = spec["wheel"]["version"]
    if Path(actual["prefix"]).resolve() != environment.resolve() or any(packages.get(name) != version for name, version in expected.items()):
        raise RuntimeErrorDetail("Prepared runtime no longer matches its pinned wheel/dependencies. Use a new external cache and run setup; warm run will not repair it.")
    if packages != record.get("packages"):
        raise RuntimeErrorDetail("Prepared runtime package inventory changed. Use a new external cache and run setup.")
    verify_entrypoints(spec, environment)


def setup(spec: dict, key: str, environment: Path) -> None:
    if (environment / "ready.json").is_file():
        verify(spec, key, environment)
        return
    environment.parent.mkdir(parents=True, exist_ok=True)
    lock = environment.with_suffix(".lock")
    try:
        lock.mkdir()
    except FileExistsError as exc:
        raise RuntimeErrorDetail("Setup is already active or left an incomplete setup lock. Do not stop other processes; wait for its owner or choose a new external cache.") from exc
    created = False
    try:
        if environment.exists():
            raise RuntimeErrorDetail("Incomplete runtime exists. Inspect it or choose a new external cache; setup will not overwrite it.")
        environment.mkdir()
        created = True
        venv.EnvBuilder(with_pip=True, clear=False).create(environment)
        config = checked(["-m", "pip", "config", "list"], environment, capture=True)
        for line in config.splitlines():
            name, separator, raw = line.partition("=")
            if not separator or name.rsplit(".", 1)[-1] not in {"root", "home", "target", "prefix", "user"}:
                continue
            value = ast.literal_eval(raw)
            if not value or (name.endswith(".user") and str(value).lower() in {"false", "0", "no"}):
                continue
            if name == ":env:.prefix" and value == str(environment):
                continue
            raise RuntimeErrorDetail(
                f"Configured pip destination option {name} is incompatible with plugin isolation. "
                "Use setup configuration containing package sources/proxy settings but no installation destination overrides; no configuration was changed."
            )
        dependencies = asset(ROOT, spec["lock"])
        if spec["dependencies"]:
            checked(["-m", "pip", "install", "--no-input", "--no-user", "--prefix", str(environment),
                     "--only-binary=:all:", "--require-hashes", "--no-deps", "-r", str(dependencies)], environment)
        checked(["-m", "pip", "install", "--no-input", "--no-user", "--prefix", str(environment),
                 "--no-deps", "--no-index", str(asset(ROOT, spec["wheel"]))], environment)
        checked(["-m", "pip", "check"], environment)
        actual = installed(environment)
        packages = {normalized(name): version for name, version in actual["packages"].items()}
        expected = {normalized(item["name"]): item["version"] for item in spec["dependencies"]}
        expected[normalized(spec["wheel"]["name"])] = spec["wheel"]["version"]
        # pip/setuptools are venv provisioning tools, not runtime requirements.
        if {name: version for name, version in packages.items() if name not in {"pip", "setuptools"}} != expected:
            raise RuntimeErrorDetail("Installed package inventory does not match the complete resolved lock.")
        verify_entrypoints(spec, environment)
        temp = environment / "ready.tmp"
        temp.write_bytes(canonical({"key": key, "packages": packages}))
        temp.replace(environment / "ready.json")
        verify(spec, key, environment)
    except BaseException:
        if created:
            shutil.rmtree(environment)
        raise
    finally:
        lock.rmdir()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("setup", "status", "run"))
    parser.add_argument("domain")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    selected = Path(sys.executable).resolve()
    try:
        binding = interpreter_binding(args.domain)
        selected = select_python(args.action, binding)
        if selected != Path(sys.executable).resolve():
            verify_python(selected)
            command = [str(selected), "-I", str(ROOT / "bootstrap.py"), *(sys.argv[1:] if argv is None else argv)]
            # Forward stdio unchanged: MCP stdout must contain only protocol messages.
            if os.name == "nt":
                return subprocess.run(command, check=False).returncode
            os.execve(str(selected), command, os.environ.copy())
        spec, key, environment = specification(args.domain)
        if args.action == "setup":
            if args.command:
                raise RuntimeErrorDetail("Setup accepts only a runtime name.")
            setup(spec, key, environment)
            bind_python(binding)
        else:
            verify(spec, key, environment)
        if args.action == "run":
            if not args.command or args.command[0] not in spec["entry_points"]:
                raise RuntimeErrorDetail("Select a console entry point declared by this runtime wheel.")
            code = (
                "import importlib.metadata as m,sys;"
                "d=m.distribution(sys.argv.pop(1));sys.argv=sys.argv[1:];name=sys.argv[0];"
                "e=next(e for e in d.entry_points if e.group=='console_scripts' and e.name==name);"
                "sys.exit(e.load()())"
            )
            # The distribution is installed locally; no repository imports or PATH lookup.
            if args.command[0] in {"ekg-apps", "grz-mcp", "ontology-apps"} and Path.cwd().resolve().is_relative_to(ROOT.parent.resolve()):
                os.chdir(environment)
            command = [
                str(python_path(environment)), "-I", "-B", "-c", code, spec["wheel"]["name"], *args.command,
            ]
            if os.name == "nt":
                return subprocess.run(command, env=child_env(environment), check=False).returncode
            os.execve(str(python_path(environment)), command, child_env(environment))
        print(json.dumps({"status": "ready", "runtime": args.domain, "key": key, "python": str(python_path(environment))}))
        return 0
    except (RuntimeErrorDetail, OSError, ValueError, KeyError, TypeError) as exc:
        recovery_args = [sys.executable, "-I", str(ROOT / "bootstrap.py"), "setup", args.domain]
        recovery = ("& " + " ".join("'" + item.replace("'", "''") + "'" for item in recovery_args)
                    if os.name == "nt" else shlex.join(recovery_args))
        print(
            f"Runtime {args.action} failed: {exc}\n"
            f"Bootstrap executable: {sys.executable}; version: {sys.version.split()[0]}; selected executable: {selected}.\n"
            "Recovery: set FOUNDRY_IQ_PYTHON to an existing absolute Python 3.12 executable, "
            f"then run explicit setup with the same FOUNDRY_IQ_RUNTIME_CACHE: {recovery}\n"
            "Do not change shared Python defaults; startup never installs or repairs dependencies.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
