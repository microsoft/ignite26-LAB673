"""Stdio MCP transport for the read-only EKG consume operations."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, TextIO

from ekg_core import package_version
from ekg_core.descriptors import resolve_current
from ekg_consume.adapters import QueryAdapter

from .plugin import call as plugin_call
from .server import dispatch


_PROTOCOL_VERSIONS = {"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"}
_DEFAULT_VERSION = "2025-06-18"
_OPERATIONS = {
    "ekg_consume_capabilities": "ekg.consume.capabilities",
    "ekg_consume_health": "ekg.consume.health",
    "ekg_consume_query": "ekg.consume.query",
    "ekg_consume_retrieve": "ekg.consume.retrieve",
    "ekg_consume_graph_query": "ekg.consume.graph_query",
}
_PLUGIN_TOOLS = {
    "ekg_source_inspect": "Report scoped source contract status without inventing an inventory.",
    "ekg_ks_capabilities": "Report offline Knowledge Source route capabilities and uncertainty.",
    "ekg_build_plan": "Plan and preflight an exact BuildSpec offline; never apply writes.",
    "ekg_build_status": "Inspect only the exact local Build journal; never assert live serving state.",
    "ekg_build_telemetry": "Summarize local Build phase timings and Consume latency; read-only, no Azure calls.",
    "ekg_provision_connect": "Discover and validate existing Azure resources for EKG with live "
                             "read-only ARM and data-plane calls; never writes to Azure or disk.",
    "ekg_build_generations": "List EKG build generations on a Search service and which "
                             "descriptors protect them; live read-only, never deletes.",
}
_NO_SPEC_TOOLS = {"ekg_ks_capabilities", "ekg_build_telemetry", "ekg_provision_connect",
                  "ekg_build_generations"}


def _tool(name: str, description: str) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "descriptor_path": {
            "type": "string",
            "description": "Absolute path to a locally held published EKG deployment "
                           "descriptor JSON file; optional. Defaults to the descriptor bound "
                           "at server start (--descriptor or EKG_DESCRIPTOR), else the current "
                           "pointer under EKG_HOME.",
        },
    }
    required: list[str] = []
    if name in {"ekg_consume_query", "ekg_consume_retrieve", "ekg_consume_graph_query"}:
        properties["query"] = {"type": "string", "description": "Search text (1..2048 characters)."}
        required.append("query")
        properties["top"] = {
            "type": "integer", "minimum": 1,
            "maximum": 10 if name == "ekg_consume_graph_query" else 100,
        }
        if name == "ekg_consume_graph_query":
            properties["depth"] = {"type": "integer", "minimum": 1, "maximum": 3}
            properties["fanout"] = {"type": "integer", "minimum": 1, "maximum": 50}
            properties["detail"] = {
                "type": "string", "enum": ["compact", "full"],
                "description": "compact (default): one provenance entry per source and edges "
                               "that list source_ids; full: raw per-chunk provenance on every edge.",
            }
        else:
            properties["vector"] = {
                "type": "boolean",
                "description": "Hybrid vector search when true (default); false uses lexical Search only.",
            }
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object", "properties": properties, "required": required,
            "additionalProperties": False,
        },
    }


_TOOLS = [
    _tool("ekg_consume_capabilities", "Inspect advertised capabilities of a published descriptor offline."),
    _tool("ekg_consume_health", "Validate a published descriptor offline; does not probe Azure."),
    _tool("ekg_consume_query", "Read-only document query (alias of ekg_consume_retrieve)."),
    _tool("ekg_consume_retrieve", "Read-only document retrieval with source/chunk provenance."),
    _tool("ekg_consume_graph_query", "Read-only bounded graph traversal with hydrated source provenance."),
    {
        "name": "ekg_ks_capabilities",
        "description": _PLUGIN_TOOLS["ekg_ks_capabilities"],
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    *[
        {
            "name": name, "description": _PLUGIN_TOOLS[name],
            "inputSchema": {
                "type": "object",
                "properties": {
                    "spec_path": {
                        "type": "string",
                        "description": "Absolute path to a local version-1 BuildSpec JSON file.",
                    },
                    **({"chat_capacity_k_tpm": {
                        "type": "integer", "minimum": 1,
                        "description": "Chat deployment capacity (thousands of TPM) for "
                                       "estimates only; not part of the plan ID.",
                    }} if name == "ekg_build_plan" else {}),
                },
                "required": ["spec_path"], "additionalProperties": False,
            },
        }
        for name in ("ekg_source_inspect", "ekg_build_plan")
    ],
    {
        "name": "ekg_build_status",
        "description": _PLUGIN_TOOLS["ekg_build_status"],
        "inputSchema": {
            "type": "object",
            "properties": {
                "spec_path": {"type": "string", "description": "Absolute BuildSpec JSON path."},
                "working_directory": {
                    "type": "string",
                    "description": "Absolute original Build working directory for relative paths.",
                },
                "run_id": {
                    "type": "string",
                    "description": "Exact journal run ID for an approved source Build.",
                },
            },
            "required": ["spec_path"], "additionalProperties": False,
        },
    },
    {
        "name": "ekg_build_telemetry",
        "description": _PLUGIN_TOOLS["ekg_build_telemetry"],
        "inputSchema": {
            "type": "object",
            "properties": {
                "journal_path": {"type": "string", "description": "Absolute Build journal path."},
                "run_id": {"type": "string", "description": "Exact journal run ID (optional check)."},
                "consume_log_path": {
                    "type": "string",
                    "description": "Absolute Consume telemetry JSONL path.",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "ekg_provision_connect",
        "description": _PLUGIN_TOOLS["ekg_provision_connect"],
        "inputSchema": {
            "type": "object",
            "properties": {
                **{key: {"type": "string", "description": description} for key, description in (
                    ("tenant_id", "Confirmed tenant GUID; the active az login must match."),
                    ("subscription_id", "Confirmed subscription GUID."),
                    ("resource_group", "Resource group used to resolve names and list candidates."),
                    ("search", "Search service name or exact ARM ID."),
                    ("storage", "Storage account name or exact ARM ID."),
                    ("openai", "Azure OpenAI/Foundry account name or exact ARM ID."),
                    ("storage_container", "Existing private Blob container."),
                    ("embedding_deployment", "Existing embedding deployment name."),
                    ("chat_deployment", "Existing chat deployment name."),
                    ("search_identity_resource_id", "User-assigned identity attached to Search."),
                )},
                "embedding_dimensions": {"type": "integer", "minimum": 1},
                "documents": {"type": "integer", "minimum": 1,
                              "description": "Corpus size for the extraction estimate."},
            },
            "required": ["tenant_id", "subscription_id"], "additionalProperties": False,
        },
    },
    {
        "name": "ekg_doctor",
        "description": "Check the operator environment: CLI version, Python and uv, Azure "
                       "sign-in tenant, journal state, descriptor, reader access, model "
                       "data-plane role (models list) and deployment metadata. Read-only; "
                       "no writes, completions or spend.",
        "inputSchema": {
            "type": "object",
            "properties": {
                **{key: {"type": "string", "description": description} for key, description in (
                    ("tenant_id", "Confirmed tenant GUID to compare with the active az sign-in."),
                    ("descriptor_path", "Absolute published descriptor path (defaults to the "
                                        "server's bound descriptor, else current)."),
                    ("build_journal", "Absolute Build journal path to check for unsettled runs."),
                    ("state_dir", "Absolute provisioning journal folder to check."),
                    ("search_endpoint", "https Search endpoint for the reader probe."),
                    ("index", "Index for the reader probe (default: the descriptor's)."),
                    ("openai_endpoint", "https Azure OpenAI/Foundry endpoint for the "
                                        "data-plane models-list probe (default: the "
                                        "descriptor's)."),
                    ("openai_resource_id", "Azure OpenAI/Foundry account ARM ID."),
                    ("deployment", "Model deployment whose metadata to read."),
                    ("grounding_index", "Existing grounding index to validate read-only "
                                        "(edgeList graph profile); needs search_endpoint."),
                    ("grounding_graph_name", "The plan's grounding.graph_name; checks the index "
                                             "has label rows under it."),
                )},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "ekg_build_generations",
        "description": _PLUGIN_TOOLS["ekg_build_generations"],
        "inputSchema": {
            "type": "object",
            "properties": {
                "search_endpoint": {"type": "string", "description": "https Search endpoint."},
                "tenant_id": {"type": "string",
                              "description": "Confirmed tenant GUID; the az login must match."},
                "descriptor_paths": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Absolute paths of serving descriptors to protect.",
                },
            },
            "required": ["search_endpoint", "tenant_id"], "additionalProperties": False,
        },
    },
]
_ALLOWED_ARGS = {tool["name"]: set(tool["inputSchema"]["properties"]) for tool in _TOOLS}
DESCRIPTOR_ENV = "EKG_DESCRIPTOR"
# Bound at server start by --descriptor or EKG_DESCRIPTOR; a per-call descriptor_path wins;
# otherwise EKG_HOME/descriptors/current is used.
_default_descriptor: str | None = None


def _descriptor_default() -> str:
    if _default_descriptor:
        return _default_descriptor
    return str(resolve_current())


def _optional_descriptor_default() -> str | None:
    try:
        return _descriptor_default()
    except (FileNotFoundError, ValueError):
        return None


def _doctor(arguments: dict[str, Any]) -> dict[str, Any]:
    from ekg_core.doctor import doctor
    for key in ("descriptor_path", "build_journal", "state_dir"):
        value = arguments.get(key)
        if value is not None and (not isinstance(value, str) or not Path(value).is_absolute()):
            raise ValueError(f"{key} must be an absolute path")
    return doctor("ekg-mcp", tenant_id=arguments.get("tenant_id"),
                  state_dir=arguments.get("state_dir") or (
                      str(Path(arguments["build_journal"]).parent)
                      if arguments.get("build_journal") else None),
                  build_journal=arguments.get("build_journal"),
                  provision_journal=bool(arguments.get("state_dir")),
                  descriptor=arguments.get("descriptor_path") or _optional_descriptor_default(),
                  search_endpoint=arguments.get("search_endpoint"),
                  index=arguments.get("index"),
                  openai_resource_id=arguments.get("openai_resource_id"),
                  openai_endpoint=arguments.get("openai_endpoint"),
                  deployment=arguments.get("deployment"),
                  grounding_index=arguments.get("grounding_index"),
                  grounding_graph_name=arguments.get("grounding_graph_name"), self_test=False)


def _rpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _read_descriptor(value: Any) -> dict[str, Any]:
    if value in (None, ""):
        try:
            value = str(resolve_current())
        except (FileNotFoundError, ValueError) as error:
            raise ValueError(f"no current descriptor: {error}") from error
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise ValueError("descriptor_path must be an absolute path")
    path = Path(value)
    try:
        if path.stat().st_size > 1024 * 1024:
            raise ValueError("descriptor exceeds the 1 MiB limit")
        descriptor = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("descriptor_path must point to a readable JSON file") from error
    return descriptor


def _call(name: Any, arguments: Any, adapter: QueryAdapter | None) -> dict[str, Any]:
    if not isinstance(name, str) or name not in _ALLOWED_ARGS:
        raise ValueError("Unknown EKG tool")
    if not isinstance(arguments, dict) or set(arguments) - _ALLOWED_ARGS[name]:
        result = {"ok": False, "code": "INVALID_REQUEST", "message": "Unsupported tool arguments"}
    elif name == "ekg_doctor":
        try:
            result = {"ok": True, "result": _doctor(arguments)}
        except ValueError as error:
            result = {"ok": False, "code": "INVALID_REQUEST", "message": str(error)}
    elif name in _PLUGIN_TOOLS:
        if name not in _NO_SPEC_TOOLS and "spec_path" not in arguments:
            result = {"ok": False, "code": "INVALID_REQUEST", "message": "spec_path is required"}
        else:
            try:
                result = {"ok": True, "result": plugin_call(name, arguments)}
            except (ValueError, TypeError, KeyError, OSError) as error:
                print(f"offline EKG contract failed: {type(error).__name__}", file=sys.stderr)
                result = {
                    "ok": False, "code": "INVALID_CONTRACT",
                    "message": "BuildSpec is invalid or cannot be planned offline",
                    "result": {
                        "phase": name.removeprefix("ekg_").replace("_", "."),
                        "status": "blocked", "plan_id": None, "scope": {},
                        "evidence": {"origin": "none"},
                        "uncertainty": ["Exact scope and plan could not be established"],
                        "next_action": "Correct the local BuildSpec and retry offline.",
                    },
                }
    else:
        try:
            descriptor = _read_descriptor(arguments.get("descriptor_path")
                                          or _default_descriptor)
        except ValueError as error:
            result = {"ok": False, "code": "INVALID_DESCRIPTOR", "message": str(error)}
        else:
            request = {
                "operation": _OPERATIONS[name], "descriptor": descriptor,
                **{key: value for key, value in arguments.items() if key != "descriptor_path"},
            }
            if name == "ekg_consume_graph_query":
                request.setdefault("detail", "compact")
            result = dispatch(request, adapter=adapter)
    try:
        text = json.dumps(result)
    except (TypeError, ValueError) as error:
        print(f"read-only consume response failed: {type(error).__name__}", file=sys.stderr)
        result = {
            "ok": False, "code": "CONSUME_BACKEND_ERROR",
            "message": "Read-only consume backend returned an invalid response",
        }
        text = json.dumps(result)
    return {"content": [{"type": "text", "text": text}], "isError": not result["ok"]}


def handle(message: Any, *, adapter: QueryAdapter | None = None) -> dict[str, Any] | None:
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(
        message.get("method"), str
    ):
        return _rpc_error(None, -32600, "Invalid JSON-RPC request")
    if "id" not in message:
        return None
    request_id = message["id"]
    if type(request_id) not in (str, int):
        return _rpc_error(None, -32600, "Invalid JSON-RPC request id")
    method = message["method"]
    params = message.get("params", {})
    if not isinstance(params, dict):
        return _rpc_error(request_id, -32602, "Invalid parameters")
    if method == "initialize":
        requested = params.get("protocolVersion")
        if not isinstance(requested, str):
            return _rpc_error(request_id, -32602, "Missing protocol version")
        result: dict[str, Any] = {
            "protocolVersion": requested if requested in _PROTOCOL_VERSIONS else _DEFAULT_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "ekg-skills", "version": package_version()},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": _TOOLS}
    elif method == "tools/call":
        try:
            result = _call(params.get("name"), params.get("arguments", {}), adapter)
        except ValueError:
            return _rpc_error(request_id, -32602, "Unknown EKG tool")
    else:
        return _rpc_error(request_id, -32601, "Method not found")
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _self_test() -> None:
    """Start in-process, initialize, list the tools and exit; no descriptor or Azure access."""
    started = handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                      "params": {"protocolVersion": _DEFAULT_VERSION}})
    listed = handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    server = started["result"]["serverInfo"]["name"]
    tools = [tool["name"] for tool in listed["result"]["tools"]]
    if server != "ekg-skills" or "ekg_doctor" not in tools:
        print("ekg-mcp self-test failed", file=sys.stderr)
        raise SystemExit(2)
    print(f"ekg-mcp self-test ok: {len(tools)} tools (server {server})")


def _options(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="ekg-mcp",
                                     description="Read-only EKG MCP server over stdio.")
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {package_version()}")
    parser.add_argument("--self-test", action="store_true",
                        help="start, list the tools and exit")
    parser.add_argument("--descriptor", default=os.environ.get(DESCRIPTOR_ENV),
                        help=f"default published descriptor (env {DESCRIPTOR_ENV}); a "
                             "per-call descriptor_path overrides it; omit to use current")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, *, adapter: QueryAdapter | None = None,
         input_stream: TextIO | None = None, output_stream: TextIO | None = None) -> None:
    global _default_descriptor
    if argv is None:
        argv = [] if input_stream is not None else sys.argv[1:]
    options = _options(argv)
    _default_descriptor = (str(Path(options.descriptor).expanduser().resolve())
                           if options.descriptor else None)
    if options.self_test:
        _self_test()
        return
    source = input_stream if input_stream is not None else sys.stdin
    target = output_stream if output_stream is not None else sys.stdout
    for line in source:
        message: Any = None
        try:
            message = json.loads(line)
            response = handle(message, adapter=adapter)
        except json.JSONDecodeError:
            response = _rpc_error(None, -32700, "Parse error")
        if response is not None:
            if (isinstance(message, dict)
                    and message.get("method") == "tools/call"
                    and "result" in response and "id" in message):
                meta = message.get("params", {}).get("_meta", {}) if isinstance(
                    message.get("params"), dict
                ) else {}
                token = meta.get("progressToken") if isinstance(meta, dict) else None
                if type(token) in (str, int):
                    target.write(json.dumps({
                        "jsonrpc": "2.0", "method": "notifications/progress",
                        "params": {"progressToken": token, "progress": 1, "total": 1},
                    }) + "\n")
            target.write(json.dumps(response) + "\n")
            target.flush()


if __name__ == "__main__":
    main()
