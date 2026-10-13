"""CLI output: a 3–6 line summary by default, the full result object with --json.

Every verb returns `(result, exit_code)`. `run_verb` calls a verb, turns a
`Blocked` or unexpected exception into the envelope from `errors`, and
`emit` prints it. Summaries come from a callable (ontology_build.summaries).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Callable, TextIO

from ontology_core import __version__
from ontology_core.errors import EXIT_BLOCKED, EXIT_OK, to_envelope

Result = dict[str, Any]
Summary = Callable[[Result], str]
DEFAULT_STATE_DIR = ".ontology-state"


def dumps(result: Result) -> str:
    return json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)


def blocked_summary(result: Result) -> str:
    lines = [f"Blocked ({result['error_code']}): {result['error']}"]
    if result.get("next_step"):
        lines.append(f"Next step: {result['next_step']}")
    return "\n".join(lines)


def emit(result: Result, json_mode: bool, summary: Summary | None = None, *, stream: TextIO | None = None) -> None:
    """Print `result` as JSON (--json or no summary) or as the verb's short summary."""
    out = stream or sys.stdout
    if json_mode:
        text = dumps(result)
    elif result.get("status") in ("blocked", "error"):
        text = blocked_summary(result)
    elif summary is not None:
        text = summary(result)
    else:
        text = dumps(result)
    out.write(text.rstrip("\n") + "\n")
    out.flush()


def exit_code(result: Result) -> int:
    return EXIT_OK if result.get("status", "ok") == "ok" else EXIT_BLOCKED


def run_verb(fn: Callable[..., Result], /, *args: Any, json_mode: bool = False, **kwargs: Any) -> tuple[Result, int]:
    """Call a verb; any exception becomes the blocked/error envelope. Never raises."""
    try:
        result = fn(*args, **kwargs)
        result.setdefault("status", "ok")
    except Exception as exc:  # the one catch-all per process
        result = to_envelope(exc, include_traceback=json_mode)
    return result, exit_code(result)


def add_json_flag(parser: argparse.ArgumentParser, *, subcommand: bool = False) -> None:
    """`--json` is accepted before or after the verb; SUPPRESS keeps a subparser from resetting it."""
    parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS if subcommand else False,
                        help="print the full JSON result instead of a short summary")


def add_state_dir_flag(parser: argparse.ArgumentParser, *, subcommand: bool = False) -> None:
    parser.add_argument("--state-dir", default=argparse.SUPPRESS if subcommand else DEFAULT_STATE_DIR,
                        help=f"state directory (default {DEFAULT_STATE_DIR})")


def add_common_flags(parser: argparse.ArgumentParser, *, subcommand: bool = False) -> None:
    add_json_flag(parser, subcommand=subcommand)
    add_state_dir_flag(parser, subcommand=subcommand)


def add_version_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
