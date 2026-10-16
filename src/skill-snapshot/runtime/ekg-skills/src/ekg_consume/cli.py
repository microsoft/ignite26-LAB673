from __future__ import annotations

import json
import os
import time
from pathlib import Path

from ekg_core import package_version
from ekg_core.cli import Blocked, add_command, new_parser, parse, report, say
from ekg_core.descriptors import resolve_current
from ekg_core.telemetry import CONSUME_LOG_ENV, append_consume_event, consume_event
from ekg_core.validation import validate_deployment_descriptor
from .runtime import CapabilityError, capabilities
from .service import compact_graph_result, graph_query, retrieve

PROG = "ekg-consume"
DESCRIPTOR_ENV = "EKG_DESCRIPTOR"


def _parser():
    parser, commands = new_parser(PROG, "Query a published EKG through its descriptor "
                                        "(read-only).", package_version())
    from ekg_core import doctor
    doctor.add_arguments(add_command(
        commands, "doctor", "Check this operator environment (read-only, no model calls)."))
    for name, text in (("capabilities", "List what the descriptor supports (offline)."),
                       ("query", "Retrieve evidence for a question (read-only).")):
        sub = add_command(commands, name, text)
        sub.add_argument("--descriptor", default=os.environ.get(DESCRIPTOR_ENV),
                         help=f"published descriptor (default ${DESCRIPTOR_ENV}, else the "
                              "current pointer under EKG_HOME)")
    query = commands.choices["query"]
    query.add_argument("--query", required=True)
    mode = query.add_mutually_exclusive_group()
    mode.add_argument("--graph", action="store_true", help="native graph traversal")
    mode.add_argument("--lexical", action="store_true", help="keyword retrieval only")
    query.add_argument("--depth", type=int, default=2, help="graph hops (1..3)")
    query.add_argument("--top", type=int, default=5,
                       help="results (1..100 for documents; 1..10 for graph seeds)")
    query.add_argument("--fanout", type=int, default=20,
                       help="graph rows per edge query (1..50)")
    query.add_argument("--detail", choices=("compact", "full"),
                       help="graph result evidence detail (default: full)")
    query.add_argument("--telemetry-log", default=os.environ.get(CONSUME_LOG_ENV),
                       help="append a timing event per query to this JSONL file "
                            f"(env {CONSUME_LOG_ENV})")
    return parser


def _descriptor(path: str | None) -> dict:
    if not path:
        try:
            path = str(resolve_current())
        except (FileNotFoundError, ValueError) as error:
            raise Blocked("DESCRIPTOR_INVALID", f"no current descriptor: {error}") from error
    if not Path(path).expanduser().is_absolute():
        raise Blocked("DESCRIPTOR_INVALID", "descriptor path must be absolute")
    try:
        descriptor = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise Blocked("DESCRIPTOR_INVALID", f"cannot read {path}: {error}") from error
    errors = validate_deployment_descriptor(descriptor)
    if errors:
        raise Blocked("DESCRIPTOR_INVALID", "; ".join(errors))
    return descriptor


def _summary(args, result: dict) -> dict:
    if args.command == "capabilities":
        enabled = sorted(key for key, value in result.items() if value)
        disabled = sorted(key for key, value in result.items() if not value)
        return {"summary": f"Enabled: {', '.join(enabled) or 'none'}\n"
                           f"Not enabled: {', '.join(disabled) or 'none'}",
                "next_step": "Run `ekg-consume query --query <question>` to retrieve evidence."}
    telemetry = result.get("telemetry") or {}
    lines = [f"{len(result.get('provenance') or [])} source(s) for {result['query']!r} "
             f"({telemetry.get('method')}, {telemetry.get('latency_ms')} ms)"]
    if "nodes" in result:
        lines.append(f"{len(result['nodes'])} node(s), {len(result['edges'])} edge(s)")
        lines += [f"  {node['name']} is also known as {', '.join(node['aliases'])}"
                  for node in result["nodes"] if node.get("aliases")]
    lines += [f"  {item.get('citation_uri') or item.get('source')}"
              for item in (result.get("provenance") or [])[:3]]
    return {"summary": "\n".join(lines)}


def _run(args) -> dict:
    descriptor = _descriptor(args.descriptor)
    if args.command == "capabilities":
        return capabilities(descriptor)
    if args.detail and not args.graph:
        raise Blocked("INVALID_INPUT", "--detail is only valid with --graph")
    started = time.time()
    try:
        if args.graph:
            result = graph_query(descriptor, args.query, depth=args.depth, top=args.top,
                                 fanout=args.fanout)
            if args.detail == "compact":
                result = compact_graph_result(result)
        else:
            result = retrieve(descriptor, args.query, top=args.top, vector=not args.lexical)
    except CapabilityError as error:
        raise Blocked("CAPABILITY_UNAVAILABLE", str(error)) from error
    except ValueError as error:
        raise Blocked("INVALID_INPUT", str(error)) from error
    except RuntimeError as error:
        raise Blocked("CONSUME_FAILED", str(error)) from error
    if args.telemetry_log:
        append_consume_event(args.telemetry_log, consume_event(
            "graph_query" if args.graph else "retrieve", result, started))
    return result


def main(argv: list[str] | None = None) -> None:
    args = parse(_parser(), argv)
    if args.command == "doctor":
        from ekg_core import doctor
        doctor.run(PROG, args)
        return
    try:
        result = _run(args)
    except Blocked as blocked:
        report(blocked, prog=PROG, command=args.command)
    except OSError as error:
        report(Blocked("LOCAL_IO", str(error)), prog=PROG, command=args.command)
    say(result if args.json else _summary(args, result), args, prog=PROG)
