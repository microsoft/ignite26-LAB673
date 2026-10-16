"""Error codes, the one next step for each, and the blocked/error envelope.

Every failure the plugin reports is a `Blocked` exception carrying a code from
`CODES`. The CLI and optional Apps layer turn it into
`{"status", "error_code", "error", "next_step"}` and exit with `EXIT_BLOCKED`.
`next_step` templates use `{placeholders}`; any placeholder the raiser does not
supply is rendered as `<name>` so the step is still readable.
"""

from __future__ import annotations

import string
import traceback
from typing import Any

EXIT_OK = 0
EXIT_BLOCKED = 2

_PLAN_AGAIN = "`ontology-build plan …` again, then approve the new plan ID"
_REPUBLISH = "republish the GRZ generation, then `ontology-build connect`"
_REINSTALL = ('uv tool install --force --python 3.12 '
              '"<plugin-root>/runtime/ontology-skills"')
_SIGN_IN = "az login --tenant {tenant_id}  # {tenant_name}"
_DESCRIPTOR = "pass the `descriptor.json` written by `grz-build publish` (grz-descriptor-v1)"

CODES: dict[str, str] = {
    "CONFIG_MISSING": (
        "ontology-build connect --tenant-id … --grz-descriptor … --model-endpoint … "
        "--model-deployment … --model-input-price-per-1m … --model-output-price-per-1m …"),
    "CONFIG_CONFLICT": "use a new `--state-dir` for a different generation or model",
    "TENANT_REQUIRED": "pass `--tenant-id <guid>` (the tenant that owns the GRZ Search service)",
    "TENANT_MISMATCH": _SIGN_IN,
    "AZ_NOT_SIGNED_IN": _SIGN_IN,
    "AZ_CLI_MISSING": "install Azure CLI, then `az login --tenant {tenant_id}`",
    "STATE_DIR_UNWRITABLE": "choose a writable `--state-dir`",
    "STATE_INCOMPATIBLE": "this state dir was written by another tool version; use a new `--state-dir`",
    "STATE_LOCKED": "wait for pid {pid} on {host}, or `ontology-build reconcile` if it is not running",
    "JOURNAL_DRIFT": "inspect the listed files; restore them or re-import as a new version",
    "GRZ_DESCRIPTOR_UNREADABLE": _DESCRIPTOR,
    "GRZ_DESCRIPTOR_UNSUPPORTED": _DESCRIPTOR,
    "GRZ_NOT_PUBLIC": "publish a public GRZ generation",
    "GRZ_SIDECAR_ACCESS_DENIED": (
        'ask an owner to run: `az role assignment create --role "Search Index Data Reader" '
        "--assignee {you} --scope {index_scope}`"),
    "GRZ_SIDECAR_NOT_FOUND": "check the descriptor's service and index; the generation may be retired",
    "GRZ_SIDECAR_THROTTLED": "rerun the same command in a few minutes",
    "GRZ_MANIFEST_UNHEALTHY": _REPUBLISH,
    "GRZ_COUNTS_MISMATCH": _REPUBLISH,
    "GRZ_GENERATION_CHANGED": _PLAN_AGAIN,
    "PLAN_STALE": _PLAN_AGAIN,
    "LEVEL_OUT_OF_RANGE": "`ontology-build inspect` to see the levels",
    "PASSAGE_BUDGET_TOO_SMALL": "raise `--passages` to at least {n} or pick a coarser `--level`",
    "PLAN_NOT_FOUND": "`ontology-build plan …` and use the printed plan ID",
    "PLAN_ID_MISMATCH": "`ontology-build plan …` and use the printed plan ID",
    "APPROVAL_REQUIRED": (
        "add `--plan-id {id} --approved-budget-usd {usd} --approve-model-calls` after the user approves"),
    "BUDGET_ABOVE_PLAN_CAP": "approve at most ${cap}, or re-plan with a larger `--model-max-spend-usd`",
    "BUDGET_BELOW_ESTIMATE": "approve at least ${estimate}, or re-plan with fewer `--passages`",
    "BUDGET_CAP_BELOW_ESTIMATE": "ontology-build plan --model-max-spend-usd {min_cap}{flags}",
    "BUDGET_EXHAUSTED": "re-plan with a larger cap and approve it; completed calls are kept",
    "PLAN_ALREADY_EXECUTED": "`ontology-build review --version {n}`",
    "RUN_INCOMPLETE": "rerun the same `propose`, `critique` or `refine` command to resume",
    "MODEL_ACCESS_DENIED": "ask an owner to assign Cognitive Services OpenAI User on {account}",
    "MODEL_DEPLOYMENT_NOT_FOUND": "fix `--model-deployment` and rerun connect",
    "MODEL_THROTTLED": "rerun the same command to resume",
    "MODEL_OUTPUT_INVALID": "rerun to resume; if it repeats, re-plan with a smaller `--shard-chars`",
    "MODEL_OUTPUT_TRUNCATED": "re-plan with a larger `--model-max-output-tokens` or a smaller `--shard-chars`",
    "VERSION_NOT_FOUND": "`ontology-build status`",
    "SCHEMA_ID_MISMATCH": "the version changed on disk; `ontology-build import` it as a new version",
    "NOT_APPROVED": "`ontology-build approve --version {n} --schema-id {id}`",
    "IMPORT_UNSUPPORTED_FORMAT": "use .owl/.rdf/.xml/.ttl/.nt/.json",
    "IMPORT_HAS_IMPORTS": "inline the imported terms and remove `owl:imports`",
    "IMPORT_INVALID": "fix the file (no DOCTYPE/ENTITY, ≤ 5 MB, well-formed)",
    "PROFILE_VIOLATION": "`ontology-consume check {file}` and fix the listed items",
    "BASE_IRI_INVALID": "pass a `--base-iri` that ends with `#` and has no whitespace, quotes or angle brackets",
    "OUTPUT_EXISTS": "choose another `--output` or pass `--force`",
    "EXPORT_FORMAT_UNSUPPORTED": (
        "pass `--format owl` with .owl/.rdf/.xml, or `--format jsonld` with .jsonld; Turtle is unsupported"),
    "JSONLD_EXPORT_UNSUPPORTED": "revise the ontology to use only the supported flat class/property profile",
    "JSONLD_PROFILE_VIOLATION": "inspect the profile violations and reduce or revise the ontology before export",
    "EMPTY_ONTOLOGY": "the result had no valid classes; review the hygiene report",
    "NO_CURRENT": "`ontology-build approve --version <n> --schema-id <id>` to record the current ontology",
    "CURRENT_INVALID": "re-approve or re-export the version to rewrite the current pointer",
    "QUERY_FILE_INVALID": "one JSON object per line with `id` and `query`",
    "NOT_IMPLEMENTED": "this verb is not available in this build; " + _REINSTALL,
    "INTERNAL_ERROR": "rerun with `--json` and file an issue with the output",
    # doctor: one code per check; the doctor fills {detail} placeholders where useful
    "DOCTOR_CLI_VERSION": _REINSTALL,
    "DOCTOR_PYTHON": _REINSTALL,
    "DOCTOR_UV": "install uv and put it on PATH",
    "DOCTOR_AZURE_SIGNIN": _SIGN_IN,
    "DOCTOR_STATE_DIR": "fix permissions or choose another `--state-dir`",
    "DOCTOR_JOURNAL": "`ontology-build reconcile`",
    "DOCTOR_GRZ_DESCRIPTOR": "pass the descriptor that `grz-build publish` wrote",
    "DOCTOR_SIDECAR_READER": (
        'ask an owner to run: `az role assignment create --role "Search Index Data Reader" '
        "--assignee {you} --scope {index_scope}`"),
    "DOCTOR_GRZ_MANIFEST": "republish the GRZ generation, then rerun connect",
    "DOCTOR_MODEL_DATA_PLANE": (
        'ask an owner to run: `az role assignment create --role "Cognitive Services OpenAI User" '
        "--assignee {you} --scope {account}`; otherwise fix `--model-endpoint`"),
    "DOCTOR_MODEL_DEPLOYMENT": "fix `--model-deployment`, or check `--subscription-id/--model-resource-group`",
}

INTERNAL_ERROR = "INTERNAL_ERROR"


class _Keep(dict):
    def __missing__(self, key: str) -> str:
        return f"<{key}>"


def render_next_step(code: str, **fmt: Any) -> str:
    """Fill the `next_step` template for `code`; unknown codes are an internal error."""
    if code not in CODES:
        raise KeyError(f"unknown error code {code!r}")
    return string.Formatter().vformat(CODES[code], (), _Keep({k: v for k, v in fmt.items() if v is not None}))


def placeholders(code: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(CODES[code]) if name}


class Blocked(Exception):
    """A gated or failed step with one error code and one next step.

    `Blocked(code, error, **fmt)`: `error` is the human sentence; `fmt` fills the
    code's `next_step` template. `details` (keyword) adds structured fields to the
    envelope under `"details"` (for example the drifted paths for JOURNAL_DRIFT).
    Pass `next_step=` only to override the table (doctor checks use this).
    """

    def __init__(self, code: str, error: str = "", /, *, details: dict[str, Any] | None = None,
                 next_step: str | None = None, **fmt: Any) -> None:
        if code not in CODES:
            raise KeyError(f"unknown error code {code!r}")
        self.code = code
        self.error = error or code.replace("_", " ").lower()
        self.details = details or {}
        self.fmt = fmt
        self.next_step = next_step or render_next_step(code, **fmt)
        super().__init__(f"{code}: {self.error}")

    def envelope(self) -> dict[str, Any]:
        return envelope(self.code, self.error, self.next_step, details=self.details)


def envelope(code: str, error: str, next_step: str, *, details: dict[str, Any] | None = None) -> dict[str, Any]:
    """The blocked/error result object. INTERNAL_ERROR uses status "error"; every other code "blocked"."""
    body: dict[str, Any] = {
        "status": "error" if code == INTERNAL_ERROR else "blocked",
        "error_code": code,
        "error": error,
        "next_step": next_step,
    }
    if details:
        body["details"] = details
    return body


def internal_error(exc: BaseException, *, include_traceback: bool) -> dict[str, Any]:
    """Envelope for an unexpected exception. The traceback is included only in --json output."""
    details = None
    if include_traceback:
        details = {"traceback": "".join(traceback.format_exception(exc))}
    return envelope(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}", CODES[INTERNAL_ERROR], details=details)


def to_envelope(exc: BaseException, *, include_traceback: bool = False) -> dict[str, Any]:
    if isinstance(exc, Blocked):
        return exc.envelope()
    return internal_error(exc, include_traceback=include_traceback)
