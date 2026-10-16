"""State directory layout, user-only permissions, atomic writes and record loading.

All plugin writes go through `atomic_write`. Hashed files (`ontology.v<N>.json`,
evidence lines, the lock) use canonical JSON; human-facing files use indented
JSON. Every file ends with one LF. Mutating verbs hold `journal.StateLock`.
"""

from __future__ import annotations

import getpass
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

from ontology_core import __version__, hashing
from ontology_core.errors import Blocked
from ontology_core.model import (
    Approval, Config, Diff, EvidenceRecord, Ontology, Plan, Record, SchemaError, Version,
)

if TYPE_CHECKING:
    from ontology_core.journal import Journal

R = TypeVar("R", bound=Record)


def utc_now() -> str:
    """UTC ISO-8601 with millisecond precision and a `Z` suffix."""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def tool_version() -> str:
    return __version__


def actor() -> str:
    """The local user name recorded on approvals and runs; never an Azure call."""
    return getpass.getuser()


# --------------------------------------------------------------------------- layout


def judge_call(round_: int, sample: int = 1) -> str:
    """The journal call name of judge sample `sample` in round `round_`: `judge-<k>`, then `judge-<k>-s<j>`."""
    return f"judge-{round_}" if sample == 1 else f"judge-{round_}-s{sample}"


@dataclass(frozen=True)
class StatePaths:
    """Every path in the state dir. Build with `StatePaths(Path(state_dir).resolve())`."""

    root: Path

    @property
    def config(self) -> Path:
        return self.root / "config.json"

    @property
    def descriptor(self) -> Path:
        return self.root / "grz-descriptor.json"

    @property
    def journal(self) -> Path:
        return self.root / "journal.jsonl"

    @property
    def lock(self) -> Path:
        return self.root / ".lock"

    @property
    def plans_dir(self) -> Path:
        return self.root / "plans"

    def plan(self, plan_id: str) -> Path:
        return self.plans_dir / f"{plan_id}.json"

    def run_dir(self, plan_id: str) -> Path:
        return self.root / "runs" / plan_id

    def sample(self, plan_id: str) -> Path:
        return self.run_dir(plan_id) / "sample.json"

    def shard_request(self, plan_id: str, k: int) -> Path:
        return self.run_dir(plan_id) / f"shard-{k}.request.json"

    def shard_response(self, plan_id: str, k: int) -> Path:
        return self.run_dir(plan_id) / f"shard-{k}.response.json"

    def audit_request(self, plan_id: str) -> Path:
        return self.run_dir(plan_id) / "audit.request.json"

    def audit_response(self, plan_id: str) -> Path:
        return self.run_dir(plan_id) / "audit.response.json"

    @property
    def versions_dir(self) -> Path:
        return self.root / "versions"

    def version_dir(self, n: int) -> Path:
        return self.versions_dir / f"v{n}"

    def version_json(self, n: int) -> Path:
        return self.version_dir(n) / "version.json"

    def ontology(self, n: int) -> Path:
        return self.version_dir(n) / f"ontology.v{n}.json"

    def evidence(self, n: int) -> Path:
        return self.version_dir(n) / f"evidence.v{n}.jsonl"

    def diff(self, n: int) -> Path:
        return self.version_dir(n) / f"diff.v{n}.json"

    def approval(self, n: int) -> Path:
        return self.version_dir(n) / "approval.json"

    @property
    def exports_dir(self) -> Path:
        return self.root / "exports"

    def export_manifest(self, schema_id: str) -> Path:
        return self.exports_dir / f"export-manifest.{hashing.schema_hash12(schema_id)}.json"

    def jsonld_export_manifest(self, schema_id: str) -> Path:
        return self.exports_dir / f"jsonld-export-manifest.{hashing.schema_hash12(schema_id)}.json"

    def judge_request(self, plan_id: str, round_: int, sample: int = 1) -> Path:
        return self.run_dir(plan_id) / f"{judge_call(round_, sample)}.request.json"

    def judge_response(self, plan_id: str, round_: int, sample: int = 1) -> Path:
        return self.run_dir(plan_id) / f"{judge_call(round_, sample)}.response.json"

    def refine_record(self, plan_id: str) -> Path:
        return self.run_dir(plan_id) / "refine.json"

    @property
    def critiques_dir(self) -> Path:
        return self.root / "critiques"

    def critique(self, critique_id: str) -> Path:
        return self.critiques_dir / f"{critique_id}.json"

    def relative(self, path: Path) -> str:
        """Path relative to the state dir with `/` separators, as journaled in `artifact_written`."""
        return Path(path).resolve().relative_to(self.root).as_posix()


def paths_for(state_dir: str | os.PathLike[str]) -> StatePaths:
    return StatePaths(Path(state_dir).expanduser().resolve())


# --------------------------------------------------------------------------- permissions


def _windows_user() -> str:
    domain = os.environ.get("USERDOMAIN")
    user = os.environ.get("USERNAME") or getpass.getuser()
    return f"{domain}\\{user}" if domain else user


# Windows principals allowed besides the current user: the OS itself and local administrators.
_WINDOWS_SYSTEM_PRINCIPALS = frozenset({"nt authority\\system", "builtin\\administrators"})


def _icacls(path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    # run from the parent with a relative name so output lines are ". <ACE>" whatever the path form
    return subprocess.run(["icacls", path.name or str(path), *args], cwd=path.parent,
                          capture_output=True, text=True, check=False)


def _acl_entries(path: Path) -> list[tuple[str, str]]:
    """`[(principal, flags)]` from `icacls`; Windows only."""
    result = _icacls(path)
    if result.returncode != 0:
        return []
    prefix = len(path.name) + 1
    entries = []
    for number, line in enumerate(result.stdout.splitlines()):
        ace = (line[prefix:] if number == 0 else line).strip()
        if ":(" not in ace:
            continue
        principal, _, flags = ace.partition(":(")
        entries.append((principal.strip(), "(" + flags))
    return entries


def _is_current_user(principal: str) -> bool:
    user = (os.environ.get("USERNAME") or getpass.getuser()).lower()
    return principal.lower().rsplit("\\", 1)[-1] == user


def restrict_to_user(path: Path) -> None:
    """Windows: drop inherited ACEs, grant the current user full control, and remove every other
    principal except SYSTEM and Administrators. POSIX: chmod 700."""
    if sys.platform != "win32":
        os.chmod(path, 0o700)
        return
    path = Path(path).resolve()
    result = _icacls(path, "/inheritance:r", "/grant:r", f"{_windows_user()}:(OI)(CI)F")
    if result.returncode == 0:
        for principal, _flags in _acl_entries(path):
            if not _is_current_user(principal) and principal.lower() not in _WINDOWS_SYSTEM_PRINCIPALS:
                result = _icacls(path, "/remove:g", principal)
                if result.returncode != 0:
                    break
    if result.returncode != 0:
        raise Blocked("STATE_DIR_UNWRITABLE",
                      f"could not restrict {path}: {result.stdout.strip()} {result.stderr.strip()}".strip())


def is_user_only(path: Path) -> bool:
    """True when only the current user can access `path`: mode 700 and owned by us on POSIX; on
    Windows every ACE (explicit or inherited) is the user, SYSTEM or Administrators."""
    if sys.platform != "win32":
        st = os.stat(path)
        return st.st_uid == os.getuid() and (st.st_mode & 0o077) == 0
    entries = _acl_entries(Path(path).resolve())
    if not any(_is_current_user(p) for p, _ in entries):
        return False
    return all(_is_current_user(p) or p.lower() in _WINDOWS_SYSTEM_PRINCIPALS for p, _ in entries)


def ensure_dir(path: str | os.PathLike[str], *, private: bool = True) -> Path:
    """Create `path` (and parents). A directory this call creates gets user-only permissions
    when `private` (the default); an existing directory is left as it is."""
    target = Path(path)
    if target.is_dir():
        return target
    missing = [p for p in [target, *target.parents] if not p.exists()]
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise Blocked("STATE_DIR_UNWRITABLE", f"cannot create {target}: {exc}") from exc
    if private:
        # the outermost new directory carries the ACL; children inherit it (OI)(CI)
        restrict_to_user(missing[-1] if missing else target)
    return target


def ensure_state(state_dir: str | os.PathLike[str]) -> StatePaths:
    """Create the state root (user-only) if needed and confirm it is writable."""
    paths = paths_for(state_dir)
    ensure_dir(paths.root)
    if not os.access(paths.root, os.W_OK):
        raise Blocked("STATE_DIR_UNWRITABLE", f"{paths.root} is not writable")
    return paths


# --------------------------------------------------------------------------- writes


def _fsync_dir(directory: Path) -> None:
    if sys.platform == "win32":
        return
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write(path: str | os.PathLike[str], data: bytes) -> str:
    """Write `path.tmp`, fsync, `os.replace`, fsync the directory. Returns the SHA-256 of `data`."""
    target = Path(path)
    ensure_dir(target.parent)
    tmp = target.with_name(target.name + ".tmp")
    with open(tmp, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, target)
    _fsync_dir(target.parent)
    return hashing.sha256_bytes(data)


def write_json(path: str | os.PathLike[str], value: Any, *, canonical: bool = False) -> str:
    """Write JSON (canonical for hashed files, indented otherwise). Returns the file's SHA-256."""
    data = hashing.canonical_bytes(value) if canonical else hashing.pretty_json(value)
    return atomic_write(path, data)


def write_record(path: str | os.PathLike[str], record: Record, *, canonical: bool = False) -> str:
    record.validate()
    if isinstance(record, Ontology):
        return atomic_write(path, record.to_bytes())
    return write_json(path, record.to_dict(), canonical=canonical)


# --------------------------------------------------------------------------- reads


def _incompatible(path: Path, errors: list[str]) -> Blocked:
    return Blocked("STATE_INCOMPATIBLE", f"{path.name} does not match this tool version ({tool_version()}): "
                   + "; ".join(errors[:3]), details={"path": str(path), "errors": errors[:20]})


def read_json(path: str | os.PathLike[str]) -> Any:
    """Parse a state file. Unparsable JSON is `STATE_INCOMPATIBLE`; a missing file raises FileNotFoundError."""
    target = Path(path)
    raw = target.read_bytes()
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _incompatible(target, [f"invalid JSON: {exc}"]) from exc


def read_record(path: str | os.PathLike[str], cls: type[R]) -> R:
    """Load and schema-validate one record. Schema failure is `STATE_INCOMPATIBLE`."""
    target = Path(path)
    data = read_json(target)
    try:
        return cls.from_dict(data)
    except SchemaError as exc:
        raise _incompatible(target, exc.errors) from exc


def read_jsonl(path: str | os.PathLike[str], cls: type[R]) -> list[R]:
    target = Path(path)
    out: list[R] = []
    for number, line in enumerate(target.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            out.append(cls.from_dict(json.loads(line)))
        except (json.JSONDecodeError, SchemaError) as exc:
            raise _incompatible(target, [f"line {number}: {exc}"]) from exc
    return out


def load_config(paths: StatePaths) -> Config:
    if not paths.config.is_file():
        raise Blocked("CONFIG_MISSING", f"no config.json in {paths.root}; run connect first")
    return read_record(paths.config, Config)


def save_config(paths: StatePaths, config: Config) -> str:
    return write_record(paths.config, config)


def load_plan(paths: StatePaths, plan_id: str) -> Plan:
    """Load a saved plan; missing is `PLAN_NOT_FOUND`, a hash that no longer matches is `PLAN_ID_MISMATCH`."""
    path = paths.plan(plan_id)
    if not path.is_file():
        raise Blocked("PLAN_NOT_FOUND", f"no plan {plan_id} in {paths.plans_dir}")
    plan = read_record(path, Plan)
    if plan.plan_id != plan_id or not plan.id_matches():
        raise Blocked("PLAN_ID_MISMATCH", f"plan file {path.name} does not hash to {plan_id}")
    return plan


# --------------------------------------------------------------------------- versions


def list_versions(paths: StatePaths) -> list[int]:
    """Version numbers with a `version.json`, ascending."""
    if not paths.versions_dir.is_dir():
        return []
    found = []
    for child in paths.versions_dir.iterdir():
        name = child.name
        if name.startswith("v") and name[1:].isdigit() and (child / "version.json").is_file():
            found.append(int(name[1:]))
    return sorted(found)


def latest_version(paths: StatePaths) -> int | None:
    versions = list_versions(paths)
    return versions[-1] if versions else None


def next_version(paths: StatePaths) -> int:
    """The next free version number; `v0` is reserved for `import --as-seed`, so proposals start at 1."""
    latest = latest_version(paths)
    return 1 if latest is None else latest + 1


def resolve_version(paths: StatePaths, n: int | None) -> int:
    """`n`, or the latest version when `n` is None. `VERSION_NOT_FOUND` if there is none."""
    if n is None:
        n = latest_version(paths)
        if n is None:
            raise Blocked("VERSION_NOT_FOUND", "there are no versions yet")
    if not paths.version_json(n).is_file():
        raise Blocked("VERSION_NOT_FOUND", f"version {n} does not exist")
    return n


def load_version(paths: StatePaths, n: int | None = None, *, verify: bool = True) -> tuple[Version, Ontology]:
    """Load `version.json` and the ontology. With `verify`, the ontology bytes must hash to
    `version.schema_id`, otherwise `SCHEMA_ID_MISMATCH`."""
    n = resolve_version(paths, n)
    meta = read_record(paths.version_json(n), Version)
    raw = paths.ontology(n).read_bytes()
    if verify and hashing.schema_id_of_bytes(raw) != meta.schema_id:
        raise Blocked("SCHEMA_ID_MISMATCH", f"v{n} ontology bytes no longer hash to {meta.schema_id}",
                      details={"version": n, "path": str(paths.ontology(n))})
    return meta, read_record(paths.ontology(n), Ontology)


def load_evidence(paths: StatePaths, n: int) -> list[EvidenceRecord]:
    path = paths.evidence(n)
    return read_jsonl(path, EvidenceRecord) if path.is_file() else []


def load_diff(paths: StatePaths, n: int) -> Diff | None:
    path = paths.diff(n)
    return read_record(path, Diff) if path.is_file() else None


def load_approval(paths: StatePaths, n: int) -> Approval | None:
    path = paths.approval(n)
    return read_record(path, Approval) if path.is_file() else None


def latest_approved_version(paths: StatePaths) -> int | None:
    for n in reversed(list_versions(paths)):
        if paths.approval(n).is_file():
            return n
    return None


def write_version(paths: StatePaths, journal: Journal, *, version: Version, ontology: Ontology,
                  evidence: list[EvidenceRecord], diff: Diff | None) -> dict[str, str]:
    """Write `versions/v<N>/` (ontology, evidence, diff, then version.json last) and journal each file
    as `artifact_written` plus one `version_created`. The caller holds the lock.
    Returns `{relative path: sha256}`. Refuses to overwrite an existing version (INTERNAL_ERROR)."""
    n = version.version
    if ontology.version != n or version.schema_id != ontology.schema_id():
        raise Blocked("INTERNAL_ERROR", f"version {n} metadata does not match its ontology")
    if paths.version_dir(n).exists():
        raise Blocked("INTERNAL_ERROR", f"version directory v{n} already exists")
    written: dict[str, str] = {}

    def record(path: Path, sha: str) -> None:
        rel = paths.relative(path)
        written[rel] = sha
        journal.append("artifact_written", path=rel, sha256=sha)

    record(paths.ontology(n), write_record(paths.ontology(n), ontology))
    lines = b"".join(hashing.canonical_bytes(e.to_dict()) for e in sorted(evidence, key=lambda e: e.evidence_id))
    record(paths.evidence(n), atomic_write(paths.evidence(n), lines))
    if diff is not None:
        record(paths.diff(n), write_record(paths.diff(n), diff))
    record(paths.version_json(n), write_record(paths.version_json(n), version))
    journal.append("version_created", version=n, schema_id=version.schema_id, origin=version.origin,
                   plan_id=version.plan_id)
    return written
