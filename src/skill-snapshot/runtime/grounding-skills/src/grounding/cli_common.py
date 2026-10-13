"""Shared CLI plumbing: JSON on stdout, text on stderr, stable exit codes."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Callable

from . import __version__, state
from .azure import Azure, validate_endpoint
from .errors import (EXIT_BLOCKED, EXIT_OK, EXIT_UNEXPECTED, GroundingError)


def emit(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def say(msg: str) -> None:
    print(msg, file=sys.stderr)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):  # usage errors use the same envelope as other blocks
        emit({"ok": False, "code": "USAGE", "message": message})
        raise SystemExit(EXIT_BLOCKED)


def parser(prog: str, description: str) -> _Parser:
    p = _Parser(prog=prog, description=description)
    p.add_argument("--version", action="version", version=f"{prog} {__version__}")
    return p


def add_identity_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--tenant", default="", help="expected tenant ID; abort if the signed-in tenant differs")
    p.add_argument("--subscription", default="", help="subscription ID (default: current az subscription)")


def add_endpoint_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument("--endpoint", default="", help="Search endpoint https://<service>.search.windows.net "
                                                 "(default: saved connection)")


def resolve_endpoint(explicit: str = "", index: str = "") -> str:
    if explicit:
        return validate_endpoint(explicit)
    if index:
        d = state.load_descriptor(index)
        if d and d.get("endpoint"):
            return validate_endpoint(d["endpoint"])
    conn = state.load_connection()
    if conn and conn.get("endpoint"):
        return validate_endpoint(conn["endpoint"])
    raise GroundingError("NO_ENDPOINT", "no Search endpoint known",
                         "Pass --endpoint or run `grounding-provision connect --service <name>` first.")


def identity(az: Azure, args: argparse.Namespace, need_subscription: bool = True) -> dict[str, Any]:
    return az.resolve_identity(getattr(args, "tenant", ""), getattr(args, "subscription", ""), need_subscription)


def run(fn: Callable[[], dict[str, Any]]) -> int:
    try:
        out = fn()
    except GroundingError as exc:
        emit(exc.envelope())
        say(f"{exc.code}: {exc.message}" + (f"\nNext: {exc.next_step}" if exc.next_step else ""))
        return exc.exit_code
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001
        emit({"ok": False, "code": "UNEXPECTED", "message": f"{type(exc).__name__}: {exc}"})
        return EXIT_UNEXPECTED
    emit(out)
    if out.get("approval"):
        say(out["approval"])
    return EXIT_OK if out.get("ok", True) else EXIT_BLOCKED
