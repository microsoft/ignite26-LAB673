"""Read-only stdio MCP server: doctor, plan and check only.

Write operations (create, apply, resume) are deliberately CLI-only so that approval cannot be bypassed by a tool call.
This server never writes to Azure and never writes to disk; plans it returns are previews, and the CLI
`grounding-build plan` is the authoritative step that saves the approved snapshot.
"""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from typing import Any

from . import __version__, build, consume, provision
from .azure import Azure
from .cli_common import resolve_endpoint
from .errors import GroundingError
from .names import default_index_name

PROTOCOLS = ("2024-11-05", "2025-03-26", "2025-06-18")
_IDENT = {"tenant": {"type": "string", "description": "Expected tenant ID; abort on mismatch."},
          "subscription": {"type": "string", "description": "Subscription ID (default: current az subscription)."}}
_EP = {"endpoint": {"type": "string", "description": "https://<service>.search.windows.net (default: saved connection)."}}

TOOLS = [
    {"name": "grounding_provision_doctor",
     "description": "Read-only: check Entra roles, 2026-08-01-preview availability and auth mode of a Search service.",
     "inputSchema": {"type": "object", "properties": {**_IDENT, **_EP}, "additionalProperties": False}},
    {"name": "grounding_build_plan",
     "description": "Read-only dry run: normalize an edge file or a bounded Wikidata seed and report counts, plan ID "
                    "and quota headroom. Does not write to Azure or disk; apply/resume are CLI-only.",
     "inputSchema": {"type": "object", "properties": {
         **_IDENT, **_EP, "file": {"type": "string"}, "format": {"type": "string", "enum": ["csv", "jsonl", "parquet"]},
         "wikidata_seeds": {"type": "array", "items": {"type": "string"}}, "depth": {"type": "integer", "minimum": 1, "maximum": 2},
         "edge_cap": {"type": "integer", "minimum": 1}, "index": {"type": "string"}, "source_label": {"type": "string"},
         "license": {"type": "string"}, "graph_name": {"type": "string"}, "with_labels": {"type": "boolean"}},
           "additionalProperties": False}},
    {"name": "grounding_consume_ready",
     "description": "Read-only: PASS/FAIL whether a graph-extraction build can resolve names against a grounding index "
                    "(profile, label rows, graph name match) with one next_step.",
     "inputSchema": {"type": "object", "properties": {**_IDENT, **_EP, "index": {"type": "string"},
                                                       "graph_name": {"type": "string"}},
                     "required": ["index"], "additionalProperties": False}},
    {"name": "grounding_consume_check",
     "description": "Read-only: validate the edgeList profile, document count and a sample query of a grounding index.",
     "inputSchema": {"type": "object", "properties": {**_IDENT, **_EP, "index": {"type": "string"}},
                     "required": ["index"], "additionalProperties": False}},
]


def _identity(az: Azure, args: dict[str, Any], need_subscription: bool = True) -> dict[str, Any]:
    return az.resolve_identity(args.get("tenant", ""), args.get("subscription", ""), need_subscription)


def call_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    az = Azure()
    if name == "grounding_provision_doctor":
        return provision.doctor(az, _identity(az, args), resolve_endpoint(args.get("endpoint", "")))
    if name == "grounding_consume_check":
        _identity(az, args, need_subscription=False)
        return consume.check(az, resolve_endpoint(args.get("endpoint", ""), args["index"]), args["index"])
    if name == "grounding_consume_ready":
        _identity(az, args, need_subscription=False)
        return consume.ready(az, resolve_endpoint(args.get("endpoint", ""), args["index"]), args["index"],
                             args.get("graph_name", ""))
    if name == "grounding_build_plan":
        ident = _identity(az, args)
        seeds = args.get("wikidata_seeds") or None
        edges, extra = build.load_edges(file=args.get("file", ""), fmt=args.get("format"), wikidata_seeds=seeds,
                                        depth=args.get("depth", 1), edge_cap=args.get("edge_cap"),
                                        source_label=args.get("source_label", "byo"),
                                        license_text=args.get("license", ""), graph_name=args.get("graph_name", ""),
                                          with_labels=args.get("with_labels"))
        index = args.get("index") or default_index_name("-".join(seeds) if seeds else args.get("source_label", "edges"))
        return build.make_plan(az, ident, endpoint=resolve_endpoint(args.get("endpoint", ""), args.get("index", "")),
                               index_name=index, edges=edges, extra=extra, persist=False)
    raise GroundingError("UNKNOWN_TOOL", f"unknown tool {name}")


def handle(msg: dict[str, Any]) -> dict[str, Any] | None:
    mid, method = msg.get("id"), msg.get("method")
    if mid is None:
        return None  # notifications need no reply

    def ok(result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    if method == "initialize":
        want = (msg.get("params") or {}).get("protocolVersion")
        return ok({"protocolVersion": want if want in PROTOCOLS else PROTOCOLS[-1],
                   "capabilities": {"tools": {}}, "serverInfo": {"name": "grounding-skills", "version": __version__}})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": TOOLS})
    if method == "tools/call":
        p = msg.get("params") or {}
        try:
            out, err = call_tool(p.get("name", ""), p.get("arguments") or {}), False
        except GroundingError as exc:
            out, err = exc.envelope(), True
        except Exception as exc:  # noqa: BLE001
            out, err = {"ok": False, "code": "UNEXPECTED", "message": f"{type(exc).__name__}: {exc}"}, True
        return ok({"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}], "isError": err})
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}


def main(argv: list[str] | None = None) -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            reply = handle(json.loads(line))
        except json.JSONDecodeError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        if reply is not None:
            sys.stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
