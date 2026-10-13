"""Native binary runner for GRZBuildPoc CLI.

Orchestrates the single-file, self-contained .NET 8 CLI binary for the host RID,
verifying its SHA-256 checksum, validating configuration, invoking commands
via subprocess (without shell), parsing the `grz-cli-v1` JSON stdout envelope,
capturing stderr, and extracting operation support logs and receipt paths.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from grz_core.contracts import ContractError

NATIVE_BINARY_SHA256_BY_RID = {
    "win-x64": "6AA6AC85ED84436CE9676178C252EEDE85891B9D1717ACA66CAE095830354579",
    "linux-x64": "7095407BC5B3499056E2F94401D6EED22B103F2DB947AAE114E96B17FCAAB66A",
}
CLI_SCHEMA_VERSION = "grz-cli-v1"
SUPPORT_LOG_PATTERN = re.compile(r"Customer support log:\s*(.+)")


class _ChecksumPolicy(Enum):
    HOST_DEFAULT = "host-default"


def get_host_rid() -> str:
    """Return the supported .NET runtime identifier for this host."""
    machine = platform.machine().lower()
    architecture = {
        "amd64": "x64",
        "x86_64": "x64",
        "x64": "x64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }.get(machine)
    operating_system = {
        "win32": "win",
        "linux": "linux",
        "darwin": "osx",
    }.get(sys.platform)
    if (
        operating_system is None
        or architecture is None
        or (operating_system == "win" and architecture != "x64")
    ):
        raise ContractError(
            "NATIVE_PLATFORM_UNSUPPORTED",
            f"No GRZBuildPoc build supports platform {sys.platform!r} "
            f"with architecture {machine!r}.",
        )
    return f"{operating_system}-{architecture}"


@dataclass(frozen=True)
class NativeCliResult:
    """Parsed output of a GRZBuildPoc CLI execution."""

    schema_version: str
    status: str  # "succeeded" | "failed"
    command: str  # "validate" | "plan" | "execute"
    exit_code: int
    data: dict[str, Any] | None
    error_code: str | None
    error: str | None
    stdout: str
    stderr: str
    support_log_path: Path | None = None
    receipt_path: Path | None = None
    progress_path: Path | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == "succeeded" and self.exit_code == 0


def compute_binary_sha256(path: Path) -> str:
    """Compute uppercase SHA-256 hex digest of a binary file."""
    hasher = hashlib.sha256()
    with open(path, "rb") as stream:
        while chunk := stream.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest().upper()


def resolve_binary_path(path: Path | str | None = None) -> Path:
    """Resolve the host's GRZBuildPoc binary, in priority order.

    Checks:
    1. Explicit path parameter if provided.
    2. Environment variable GRZ_BUILD_BINARY or GRZ_NATIVE_BINARY.
    3. This snapshot's runtime bin directory, or its installed wheel data.
    4. Versioned host-RID directory, then GRZBuildPoc-extracted in Downloads.
    5. PATH via the host's binary name.

    Missing candidates fall through to the next location.
    """
    rid = get_host_rid()
    binary_name = "GRZBuildPoc.exe" if rid == "win-x64" else "GRZBuildPoc"
    candidates: list[Path] = []
    if path is not None:
        candidates.append(Path(path))

    for variable in ("GRZ_BUILD_BINARY", "GRZ_NATIVE_BINARY"):
        env_path = os.environ.get(variable)
        if env_path:
            candidates.append(Path(env_path))

    candidates.extend([
        Path(__file__).resolve().parents[2] / "bin" / binary_name,
        Path(sys.prefix) / "share" / "foundry-iq-skills" / "grz" / "bin" / binary_name,
    ])

    downloads = Path.home() / "Downloads"
    candidates.extend(
        [
            downloads / f"GRZBuildPoc-0.1.4-local-{rid}" / binary_name,
            downloads / "GRZBuildPoc-extracted" / binary_name,
        ]
    )

    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    which_binary = shutil.which(binary_name)
    if which_binary:
        candidate = Path(which_binary)
        candidates.append(candidate)
        if candidate.is_file():
            return candidate.resolve()

    raise ContractError(
        "NATIVE_BINARY_NOT_FOUND",
        f"GRZBuildPoc native binary for {rid} not found. "
        f"Checked: {[str(c) for c in candidates]} and PATH for {binary_name}.",
    )


def verify_binary(path: Path, expected_sha256: str | None = None) -> str:
    """Verify an explicit SHA-256, or the pinned checksum for the host RID."""
    if not path.is_file():
        raise ContractError(
            "NATIVE_BINARY_NOT_FOUND", f"Binary file does not exist: {path}"
        )
    if expected_sha256 is None:
        rid = get_host_rid()
        expected_sha256 = NATIVE_BINARY_SHA256_BY_RID.get(rid)
        if expected_sha256 is None:
            raise ContractError(
                "NATIVE_BINARY_CHECKSUM_REQUIRED",
                f"No packaged SHA-256 is pinned for {rid}. "
                "Supply a trusted expected_sha256 to NativeRunner.",
            )
    try:
        actual_hash = compute_binary_sha256(path)
    except OSError as exc:
        raise ContractError(
            "NATIVE_BINARY_UNREADABLE", f"Cannot read native binary: {exc}"
        ) from exc
    if actual_hash.upper() != expected_sha256.upper():
        raise ContractError(
            "BINARY_HASH_MISMATCH",
            f"Native binary SHA-256 mismatch. Expected {expected_sha256}, got {actual_hash}",
        )
    return actual_hash


def validate_native_config(config: dict[str, Any] | Path) -> dict[str, Any]:
    """Validate that configuration dictionary matches GRZBuildPoc schema."""
    if isinstance(config, Path):
        try:
            with open(config, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            raise ContractError(
                "CONFIG_INVALID", f"Cannot load configuration file: {exc}"
            ) from exc
    elif isinstance(config, dict):
        data = config
    else:
        raise ContractError(
            "CONFIG_INVALID", "Configuration must be a dict or Path to JSON file"
        )

    search = data.get("search")
    if not isinstance(search, dict):
        raise ContractError(
            "CONFIG_INVALID", "Configuration missing required 'search' section"
        )
    for field in ("endpoint", "sourceIndex", "vectorField"):
        val = search.get(field)
        if not isinstance(val, str) or not val.strip():
            raise ContractError(
                "CONFIG_INVALID", f"search.{field} must be a non-empty string"
            )

    auth = data.get("authentication")
    if not isinstance(auth, dict) or "mode" not in auth:
        raise ContractError(
            "CONFIG_INVALID", "Configuration missing 'authentication.mode'"
        )

    output_dir = data.get("outputDirectory")
    if not isinstance(output_dir, str) or not output_dir.strip():
        raise ContractError(
            "CONFIG_INVALID", "Configuration missing top-level 'outputDirectory'"
        )

    return data


def parse_grz_envelope(stdout: str) -> dict[str, Any]:
    """Extract and parse the single `grz-cli-v1` JSON envelope from CLI stdout."""
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                parsed = json.loads(line)
                if (
                    isinstance(parsed, dict)
                    and parsed.get("schemaVersion") == CLI_SCHEMA_VERSION
                ):
                    return parsed
            except json.JSONDecodeError:
                continue

    raise ContractError(
        "NATIVE_CLI_PROTOCOL_ERROR",
        f"Stdout did not contain a valid '{CLI_SCHEMA_VERSION}' JSON envelope. Output: {stdout[:500]}",
    )


def extract_support_log_path(
    stderr: str, output_dir: Path | None = None
) -> Path | None:
    """Extract the customer support log file path from stderr or output directory."""
    for line in stderr.splitlines():
        match = SUPPORT_LOG_PATTERN.search(line.strip())
        if match:
            path_str = match.group(1).strip()
            log_path = Path(path_str)
            if log_path.exists():
                return log_path
            # Check if it was written relative to cwd or output_dir
            if output_dir and (output_dir / log_path.name).exists():
                return output_dir / log_path.name
            return log_path

    if output_dir and output_dir.is_dir():
        logs = sorted(output_dir.glob("grz-operation-*.log"), key=os.path.getmtime)
        if logs:
            return logs[-1]

    return None


class NativeRunner:
    """Runner for GRZBuildPoc native binary CLI commands."""

    def __init__(
        self,
        binary_path: Path | str | None = None,
        expected_sha256: str | None | _ChecksumPolicy = _ChecksumPolicy.HOST_DEFAULT,
        verify_on_init: bool = False,
    ):
        """Use the host checksum by default; explicit None disables verification."""
        self._binary_path: Path | None = None
        self._raw_path = binary_path
        self._expected_sha256 = expected_sha256
        if verify_on_init:
            self.resolve_and_verify()

    @property
    def binary_path(self) -> Path:
        if self._binary_path is None:
            self._binary_path = resolve_binary_path(self._raw_path)
        return self._binary_path

    def resolve_and_verify(self) -> Path:
        """Resolve path and verify SHA-256."""
        path = self.binary_path
        if self._expected_sha256 is _ChecksumPolicy.HOST_DEFAULT:
            verify_binary(path)
        elif self._expected_sha256 is not None:
            verify_binary(path, self._expected_sha256)
        if sys.platform != "win32" and not os.access(path, os.X_OK):
            raise ContractError(
                "NATIVE_BINARY_NOT_EXECUTABLE",
                f"Native binary is not executable: {path}. "
                "Grant execute permission (chmod +x) before running it.",
            )
        return path

    def run_command(
        self,
        command: str,
        config_path: Path | str,
        extra_flags: list[str] | None = None,
        timeout: float = 600.0,
        cwd: Path | None = None,
    ) -> NativeCliResult:
        """Execute a GRZBuildPoc CLI command via subprocess (no shell).

        Supported commands: "validate", "plan", "execute".
        Passes `--config <config_path>` and `--json`.
        For "execute", `--yes` is required.
        """
        if command not in ("validate", "plan", "execute"):
            raise ContractError(
                "NATIVE_COMMAND_UNSUPPORTED",
                f"Unsupported command '{command}'. Must be validate, plan, or execute.",
            )

        config_path = Path(config_path).resolve()
        if not config_path.is_file():
            raise ContractError(
                "CONFIG_INVALID", f"Configuration file not found: {config_path}"
            )

        binary = self.resolve_and_verify()
        args = [str(binary), command, "--config", str(config_path), "--json"]
        if command == "execute" and (not extra_flags or "--yes" not in extra_flags):
            args.append("--yes")
        if extra_flags:
            for flag in extra_flags:
                if flag not in args:
                    args.append(flag)

        try:
            proc = subprocess.run(
                args,
                shell=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
            )
        except subprocess.TimeoutExpired as exc:
            raise ContractError(
                "NATIVE_EXECUTION_TIMEOUT",
                f"GRZBuildPoc {command} timed out after {timeout} seconds",
            ) from exc
        except OSError as exc:
            raise ContractError(
                "NATIVE_EXECUTION_FAILED",
                f"Failed to execute GRZBuildPoc binary: {exc}",
            ) from exc

        stdout = proc.stdout or ""
        stderr = proc.stderr or ""

        envelope = parse_grz_envelope(stdout)

        # Determine output directory from config if possible
        output_dir: Path | None = None
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg_data = json.load(f)
                out_str = cfg_data.get("outputDirectory")
                if out_str:
                    out_path = Path(out_str)
                    output_dir = (
                        out_path if out_path.is_absolute() else config_path.parent / out_path
                    )
        except Exception:
            pass

        support_log = extract_support_log_path(stderr, output_dir)
        receipt_path = output_dir / "receipt.json" if output_dir and (output_dir / "receipt.json").exists() else None
        progress_path = output_dir / "progress.json" if output_dir and (output_dir / "progress.json").exists() else None

        return NativeCliResult(
            schema_version=envelope.get("schemaVersion", CLI_SCHEMA_VERSION),
            status=envelope.get("status", "failed"),
            command=envelope.get("command", command),
            exit_code=int(envelope.get("exitCode", proc.returncode)),
            data=envelope.get("data"),
            error_code=envelope.get("errorCode"),
            error=envelope.get("error"),
            stdout=stdout,
            stderr=stderr,
            support_log_path=support_log,
            receipt_path=receipt_path,
            progress_path=progress_path,
        )

    def validate(
        self, config_path: Path | str, timeout: float = 60.0
    ) -> NativeCliResult:
        return self.run_command("validate", config_path, timeout=timeout)

    def plan(
        self, config_path: Path | str, timeout: float = 120.0
    ) -> NativeCliResult:
        return self.run_command("plan", config_path, timeout=timeout)

    def execute(
        self, config_path: Path | str, yes: bool = True, timeout: float = 600.0
    ) -> NativeCliResult:
        flags = ["--yes"] if yes else []
        return self.run_command("execute", config_path, extra_flags=flags, timeout=timeout)
