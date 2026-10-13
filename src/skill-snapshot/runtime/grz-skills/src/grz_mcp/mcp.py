"""Minimal stdio JSON-RPC MCP server (grz-skills) for read-only GRZ Consume browsing."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Any, TextIO

from grz_consume.config import ConsumeConfig, build_service
from grz_consume.question import embed_question
from grz_consume.service import ConsumeService
from grz_core.cli_output import error_body
from grz_core.contracts import ContractError
from grz_core.doctor import installed_version

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "grz-skills"


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


PAGE_SIZE = {"type": "integer", "minimum": 1, "maximum": 1000, "default": 100}
CURSOR = {"type": "string"}
DESCRIPTOR_PATH = {"type": "string", "minLength": 1,
                   "description": "Optional absolute path to a descriptor; overrides the one bound at start for this call."}
TOOLS: list[dict[str, Any]] = [
    {
        "name": "grz_status",
        "description": "Return verified descriptor and sidecar status for the bound GRZ generation.",
        "inputSchema": _schema({"descriptor_path": DESCRIPTOR_PATH}),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "grz_list_communities",
        "description": "List communities at one level. Omit level to get the level with about 10-30 communities "
                       "(grz_status reports it as browse_level); level 0 is the finest.",
        "inputSchema": _schema({
            "level": {"type": "integer", "minimum": 0},
            "page_size": PAGE_SIZE,
            "cursor": CURSOR,
            "descriptor_path": DESCRIPTOR_PATH,
        }),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "grz_get_community",
        "description": "Get one community by community_id.",
        "inputSchema": _schema({"community_id": {"type": "string", "minLength": 1},
                                "descriptor_path": DESCRIPTOR_PATH}, ["community_id"]),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "grz_list_members",
        "description": "Without a question: members in stable order. With question or question_vector: that community's chunks ranked by similarity to the question, top_k distinct articles with scores.",
        "inputSchema": _schema({
            "community_id": {"type": "string", "minLength": 1},
            "page_size": PAGE_SIZE,
            "cursor": CURSOR,
            "question": {"type": "string", "minLength": 1},
            "question_vector": {"type": "array", "items": {"type": "number"}},
            "top_k": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
            "descriptor_path": DESCRIPTOR_PATH,
        }, ["community_id"]),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "grz_get_chunk",
        "description": "Get public chunk evidence by chunk_id.",
        "inputSchema": _schema({"chunk_id": {"type": "string", "minLength": 1},
                                "descriptor_path": DESCRIPTOR_PATH}, ["chunk_id"]),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "grz_doctor",
        "description": "Read-only environment check: CLI version, Python, uv, Azure sign-in tenant, descriptor, "
                       "sidecar health and reader access. Run it first, and again after any blocked result.",
        "inputSchema": _schema({"descriptor_path": DESCRIPTOR_PATH}),
        "annotations": {"readOnlyHint": True},
    },
]


class Server:
    """Holds the descriptor bound at start and the services built for per-call descriptor_path overrides."""

    def __init__(self, config: ConsumeConfig | None = None, service: ConsumeService | None = None):
        self.config = config or ConsumeConfig()
        self._services: dict[Path | None, ConsumeService] = {}
        if service is not None:
            self._services[None] = service

    def config_for(self, descriptor_path: str | None) -> ConsumeConfig:
        if descriptor_path is None:
            return self.config
        path = Path(descriptor_path)
        if not path.is_absolute():
            raise ContractError("ARGS_INVALID", "descriptor_path must be an absolute path")
        return self.config.with_descriptor(path)

    def service(self, descriptor_path: str | None = None) -> ConsumeService:
        key = None if descriptor_path is None else Path(descriptor_path)
        if key not in self._services:
            self._services[key] = build_service(self.config_for(descriptor_path))
        return self._services[key]


def _validate_args(schema: dict[str, Any], args: Any) -> dict[str, Any]:
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise ContractError("ARGS_INVALID", "Tool arguments must be an object")
    extra = set(args) - set(schema["properties"])
    if extra:
        raise ContractError("ARGS_INVALID", f"Unsupported argument(s): {', '.join(sorted(extra))}")
    for required in schema.get("required", []):
        if required not in args:
            raise ContractError("ARGS_INVALID", f"Missing required argument: {required}")
    for name, value in args.items():
        spec = schema["properties"][name]
        if spec.get("type") == "string" and (not isinstance(value, str) or (spec.get("minLength") and not value)):
            raise ContractError("ARGS_INVALID", f"{name} must be a nonempty string")
        if spec.get("type") == "integer" and (type(value) is not int or value < spec.get("minimum", -2**31) or value > spec.get("maximum", 2**31)):
            raise ContractError("ARGS_INVALID", f"{name} must be an integer in range")
        if spec.get("type") == "number" and (isinstance(value, bool) or not isinstance(value, (int, float))):
            raise ContractError("ARGS_INVALID", f"{name} must be a number")
        if spec.get("type") == "array":
            item_type = (spec.get("items") or {}).get("type")
            if not isinstance(value, list) or (item_type == "number" and any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in value)):
                raise ContractError("ARGS_INVALID", f"{name} must be an array of numbers")
    return args


def _content(value: Any, *, is_error: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)}], "isError": is_error}


def _call_tool(server: Server | ConsumeService, name: str, arguments: Any) -> dict[str, Any]:
    if isinstance(server, ConsumeService):
        server = Server(service=server)
    tool = next((tool for tool in TOOLS if tool["name"] == name), None)
    try:
        if tool is None:
            raise ContractError("TOOL_NOT_FOUND", f"No tool named {name!r}")
        args = _validate_args(tool["inputSchema"], arguments)
        if name == "grz_doctor":
            from grz_consume.doctor import run_doctor
            from grz_core.doctor import ok

            config = server.config_for(args.get("descriptor_path"))
            report = run_doctor(config, self_test=lambda: ok("mcp_self_test", f"{SERVER_NAME} is running"))
            return _content(report, is_error=False)
        service = server.service(args.get("descriptor_path"))
        if name == "grz_status":
            result = service.status()
        elif name == "grz_list_communities":
            level = args["level"] if "level" in args else service.browse_level()
            result = {**service.list_communities(level, args.get("page_size", 100), args.get("cursor")), "level": level}
        elif name == "grz_get_community":
            result = service.get_community(args["community_id"])
        elif name == "grz_list_members":
            if args.get("question") and args.get("question_vector") is not None:
                raise ContractError("ARGS_INVALID", "Use question or question_vector, not both")
            if args.get("question") or args.get("question_vector") is not None:
                if args.get("cursor") is not None or "page_size" in args:
                    raise ContractError("ARGS_INVALID", "page_size/cursor are not valid with a question")
                vector = (args["question_vector"] if args.get("question_vector") is not None else
                          embed_question(args["question"], service.descriptor.embedding_model_id, service.descriptor.dimension))
                result = service.rank_members(args["community_id"], vector, args.get("top_k", 10))
            else:
                result = service.list_members(args["community_id"], args.get("page_size", 100), args.get("cursor"))
        else:
            result = service.get_chunk(args["chunk_id"])
        return _content(result)
    except (ContractError, ValueError, OSError, TypeError, ImportError) as exc:
        return _content(error_body(exc, "QUERY_INVALID"), is_error=True)


def _success(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def handle_message(server: Server | ConsumeService, message: Any) -> dict[str, Any] | None:
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
        return _error(message.get("id") if isinstance(message, dict) else None, -32600, "Invalid Request")
    method = message["method"]
    request_id = message.get("id")
    is_notification = "id" not in message
    params = message.get("params", {})
    if method == "notifications/initialized":
        return None
    if is_notification:
        return None
    if method == "initialize":
        return _success(request_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": installed_version() or "unknown"},
        })
    if method == "ping":
        return _success(request_id, {})
    if method == "tools/list":
        return _success(request_id, {"tools": TOOLS})
    if method == "tools/call":
        if not isinstance(params, dict) or not isinstance(params.get("name"), str):
            return _error(request_id, -32600, "Invalid Request")
        return _success(request_id, _call_tool(server, params["name"], params.get("arguments", {})))
    return _error(request_id, -32601, "Method not found")


def serve(server: Server | ConsumeService, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> int:
    for line in stdin:
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            print(json.dumps(_error(None, -32700, "Parse error"), sort_keys=True), file=stdout, flush=True)
            continue
        response = handle_message(server, message)
        if response is not None:
            print(json.dumps(response, sort_keys=True, ensure_ascii=False, allow_nan=False), file=stdout, flush=True)
    return 0


def self_test(server: Server) -> dict[str, Any]:
    """Start the protocol loop in memory, list tools, and exit; touches no data."""
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    out = io.StringIO()
    serve(server, io.StringIO("".join(json.dumps(r) + "\n" for r in requests)), out)
    responses = [json.loads(line) for line in out.getvalue().splitlines()]
    info = responses[0]["result"]["serverInfo"]
    tools = [tool["name"] for tool in responses[1]["result"]["tools"]]
    if info["name"] != SERVER_NAME or not tools:
        raise ContractError("MCP_SELF_TEST_FAILED", "Server did not initialize or list tools")
    return {"status": "ok", "server": info["name"], "version": info["version"], "tools": tools}
