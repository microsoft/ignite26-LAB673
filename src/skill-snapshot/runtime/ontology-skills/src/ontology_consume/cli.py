"""`ontology-consume` entry point.

Read-only: every verb reads the state dir or a user file and never writes to the state dir (`diagram
--output` writes only the user's file). `doctor` runs the no-Azure subset of checks (`doctor.CONSUME_CHECKS`).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from ontology_core import output
from ontology_core.errors import Blocked

Handler = Callable[[argparse.Namespace], dict[str, Any]]
PROG = "ontology-consume"
VERBS = ("doctor", "status", "show", "diagram", "evidence", "diff", "check", "current")


def not_implemented(args: argparse.Namespace) -> dict[str, Any]:
    raise Blocked("NOT_IMPLEMENTED", f"`{PROG} {args.verb}` is not implemented in this build")


def _paths(args: argparse.Namespace) -> Any:
    from ontology_core import state

    return state.paths_for(args.state_dir)


def run_doctor(state_dir: str | Path, plugin_root: str | None = None) -> dict[str, Any]:
    from ontology_core import doctor as checks
    from ontology_core import state

    paths = state.paths_for(state_dir)
    ctx = checks.DoctorContext(state_dir=paths.root, plugin_root=checks.plugin_root_from(plugin_root))
    return checks.result(checks.run(ctx, checks=checks.CONSUME_CHECKS), next_step_if_ok="ontology-consume status")


def doctor(args: argparse.Namespace) -> dict[str, Any]:
    return run_doctor(args.state_dir, args.plugin_root)


def status(args: argparse.Namespace) -> dict[str, Any]:
    from ontology_consume import service

    return service.status(_paths(args))


def show(args: argparse.Namespace) -> dict[str, Any]:
    from ontology_consume import service

    return service.show(_paths(args), version=args.version_n, limit=args.limit, offset=args.offset,
                        mermaid=args.mermaid)


def diagram(args: argparse.Namespace) -> dict[str, Any]:
    from ontology_consume import service

    return service.diagram(_paths(args), version=args.version_n, with_datatype=args.with_datatype,
                           output=Path(args.output) if args.output else None)


def evidence(args: argparse.Namespace) -> dict[str, Any]:
    from ontology_consume import service

    return service.evidence(_paths(args), args.type_name, version=args.version_n, limit=args.limit)


def diff(args: argparse.Namespace) -> dict[str, Any]:
    from ontology_consume import service

    return service.diff(_paths(args), args.a, args.b)


def check(args: argparse.Namespace) -> dict[str, Any]:
    from ontology_consume import service

    return service.check(Path(args.file))


def current(args: argparse.Namespace) -> dict[str, Any]:
    from ontology_core import current as pointer

    return pointer.result()


HANDLERS: dict[str, Handler] = {"doctor": doctor, "status": status, "show": show, "diagram": diagram,
                                "evidence": evidence, "diff": diff, "check": check, "current": current}


def _non_negative_int(text: str) -> int:
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=PROG, description="Browse ontology versions, evidence and diffs "
                                     "read-only, and check OWL files against the flat-owl profile.")
    output.add_version_flag(parser)
    output.add_common_flags(parser)
    sub = parser.add_subparsers(dest="verb", required=True, metavar="verb")

    def verb(name: str, help_text: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_text)
        output.add_common_flags(p, subcommand=True)
        return p

    p = verb("doctor", "check the install and state dir (no Azure)")
    p.add_argument("--plugin-root")
    verb("status", "connection, versions, approvals and the next step")

    p = verb("show", "classes and properties of a version")
    p.add_argument("--version", type=_non_negative_int, dest="version_n")
    p.add_argument("--mermaid", action="store_true")
    p.add_argument("--limit", type=_non_negative_int, default=50)
    p.add_argument("--offset", type=_non_negative_int, default=0)

    p = verb("diagram", "exact Mermaid diagram of a version (stdout, or --output file.mmd)")
    p.add_argument("--version", type=_non_negative_int, dest="version_n")
    p.add_argument("--output", metavar="FILE")
    p.add_argument("--with-datatype", action="store_true", help="list datatype properties inside each class")
    p = verb("evidence", "passages cited for a class or property")
    p.add_argument("type_name", metavar="TypeName")
    p.add_argument("--version", type=_non_negative_int, dest="version_n")
    p.add_argument("--limit", type=_non_negative_int, default=10)

    p = verb("diff", "what changed between two versions")
    p.add_argument("a", type=_non_negative_int)
    p.add_argument("b", type=_non_negative_int)

    p = verb("check", "validate any OWL file against the flat-owl profile")
    p.add_argument("file")
    verb("current", "the current approved ontology: path, sha256, IRI, counts, source generation")
    return parser


def summary_for(verb: str) -> Callable[[dict[str, Any]], str]:
    from ontology_build import summaries

    return lambda result: summaries.render(verb, result)


def safe_stdout() -> None:
    """A cp1252 pipe must not crash a verb: unencodable characters become backslash escapes (still valid JSON)."""
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None and (sys.stdout.encoding or "").lower().replace("-", "") != "utf8":
        reconfigure(errors="backslashreplace")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    safe_stdout()
    result, code = output.run_verb(HANDLERS[args.verb], args, json_mode=args.json)
    if args.verb == "doctor" and "checks" in result:
        from ontology_core import doctor as checks

        # read-only: exit 0 even when not ready; --json is the cross-plugin doctor shape
        print(output.dumps(checks.report(result)) if args.json else summary_for("doctor")(result))
        return 0
    output.emit(result, args.json, summary_for(args.verb))
    return code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
