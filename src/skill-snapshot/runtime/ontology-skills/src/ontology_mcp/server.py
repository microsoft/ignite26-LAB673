"""Hand-rolled stdio JSON-RPC 2.0 MCP server, one JSON object per line."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, TextIO

from ontology_core import __version__
from ontology_core.errors import to_envelope
from ontology_mcp import tools

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "ontology-skills"


class Server:
    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """An MCP tool result: the CLI `--json` object as text plus `structuredContent`; blocked sets `isError`."""
        try:
            if name not in tools.HANDLERS:
                raise KeyError(name)
            state_dir = tools.resolve_state_dir(arguments, self.state_dir)
            rest = {k: v for k, v in arguments.items() if k != "state_dir"}
            result = tools.HANDLERS[name](state_dir, rest)
            result.setdefault("status", "ok")
        except Exception as exc:  # tool failures are results, not protocol errors
            result = to_envelope(exc)
        return {"content": [{"type": "text", "text": json.dumps(result, sort_keys=True)}],
                "structuredContent": result, "isError": result.get("status") != "ok"}

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Handle one JSON-RPC message; returns the response, or None for notifications."""
        method = message.get("method")
        msg_id = message.get("id")
        params = message.get("params") or {}
        if msg_id is None:
            return None
        if method == "initialize":
            result: Any = {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {"listChanged": False}},
                           "serverInfo": {"name": SERVER_NAME, "version": __version__}}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": tools.TOOLS}
        elif method == "tools/call":
            name = params.get("name")
            if name not in tools.HANDLERS:
                return _error(msg_id, -32602, f"unknown tool: {name}")
            arguments = params.get("arguments") or {}
            if not isinstance(arguments, dict):
                return _error(msg_id, -32602, "arguments must be an object")
            result = self.call_tool(name, arguments)
        else:
            return _error(msg_id, -32601, f"method not found: {method}")
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def serve(self, stdin: TextIO | None = None, stdout: TextIO | None = None) -> None:
        source, sink = stdin or sys.stdin, stdout or sys.stdout
        for line in source:
            if not line.strip():
                continue
            try:
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise ValueError("not an object")
            except ValueError:
                response: dict[str, Any] | None = _error(None, -32700, "parse error")
            else:
                response = self.handle(message)
            if response is not None:
                sink.write(json.dumps(response, separators=(",", ":")) + "\n")
                sink.flush()


def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def self_test(state_dir: Path) -> dict[str, Any]:
    """In-process `initialize` + `tools/list`; checks 8 read-only tools and that `ontology_status` exposes
    the latest critique. Returns the verb result."""
    server = Server(state_dir)
    init = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                          "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                                     "clientInfo": {"name": "self-test", "version": __version__}}})
    listed = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    problems = []
    if not init or init.get("result", {}).get("protocolVersion") != PROTOCOL_VERSION:
        problems.append("initialize failed")
    names = [t["name"] for t in (listed or {}).get("result", {}).get("tools", [])]
    if len(names) != len(tools.TOOLS):
        problems.append(f"expected {len(tools.TOOLS)} tools, got {len(names)}")
    not_read_only = [t["name"] for t in tools.TOOLS if t.get("annotations", {}).get("readOnlyHint") is not True]
    if not_read_only:
        problems.append("not read-only: " + ", ".join(not_read_only))
    if "latest_critique" not in tools.status(state_dir, {}):
        problems.append("ontology_status lacks latest_critique")
    if problems:
        from ontology_core.errors import Blocked

        raise Blocked("DOCTOR_MCP_SELF_TEST", "; ".join(problems))
    return {"status": "ok", "tools": names, "protocol_version": PROTOCOL_VERSION}
