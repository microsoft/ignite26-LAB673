"""Optional MCP Apps presentation over the read-only EKG graph query."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal

from ekg_consume.service import (
    GraphBudgetExceeded,
    compact_graph_result,
    graph_query,
)
from ekg_core.descriptors import resolve_current
from ekg_core.validation import validate_deployment_descriptor

EXTENSION_ID = "io.modelcontextprotocol/ui"
APP_MIME_TYPE = "text/html;profile=mcp-app"
GRAPH_RESOURCE_URI = "ui://ekg-skills/graph.html"
EVIDENCE_RESOURCE_URI = "ui://ekg-skills/evidence.html"
RESOURCE_FILES = {
    GRAPH_RESOURCE_URI: "graph.html",
    EVIDENCE_RESOURCE_URI: "evidence.html",
}
PRESENTER_TOOLS = frozenset({"ekg_present", "ekg_present_evidence"})
SUPPORT_TOOLS = frozenset({"ekg_graph_query"})
APP_TOOLS = PRESENTER_TOOLS | SUPPORT_TOOLS
_QUERY_FIELDS = frozenset({"query", "depth", "top", "fanout", "detail"})
_QUERY_LIMITS = {"depth": (1, 3), "top": (1, 10), "fanout": (1, 50)}


def validate_raw_arguments(name: str, arguments: Any) -> None:
    if type(name) is not str or name not in APP_TOOLS:
        raise ValueError("unknown EKG Apps operation")
    if not isinstance(arguments, Mapping):
        raise ValueError("arguments must be an object")
    if set(arguments) - _QUERY_FIELDS:
        raise ValueError("unsupported graph query argument")
    query = arguments.get("query")
    if (type(query) is not str or not query.strip() or len(query) > 2048
            or any(ord(char) < 32 for char in query)):
        raise ValueError("query must be nonempty text of at most 2048 characters")
    for field, (minimum, maximum) in _QUERY_LIMITS.items():
        value = arguments.get(field, {"depth": 2, "top": 5, "fanout": 20}[field])
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError(f"{field} must be an integer in {minimum}..{maximum}")
    if "detail" in arguments and (
        type(arguments["detail"]) is not str
        or arguments["detail"] not in {"compact", "full"}
    ):
        raise ValueError("detail must be compact or full")


def _load_descriptor(path: str | None) -> dict[str, Any]:
    selected = path or os.environ.get("EKG_DESCRIPTOR")
    if not selected:
        selected = str(resolve_current())
    descriptor_path = Path(selected).expanduser()
    if not descriptor_path.is_absolute():
        raise ValueError("descriptor path must be absolute")
    try:
        if descriptor_path.stat().st_size > 1024 * 1024:
            raise ValueError("descriptor exceeds the 1 MiB limit")
        descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("descriptor must be a readable JSON file") from error
    if not isinstance(descriptor, dict):
        raise ValueError("descriptor must be a JSON object")
    errors = validate_deployment_descriptor(descriptor)
    if errors:
        raise ValueError("descriptor is invalid: " + "; ".join(errors))
    return descriptor


def _query(descriptor: dict[str, Any], query: str, depth: int, top: int,
           fanout: int, detail: str) -> dict[str, Any]:
    try:
        result = graph_query(descriptor, query, depth=depth, top=top, fanout=fanout)
    except GraphBudgetExceeded as error:
        raise ValueError(
            "graph traversal exceeded its bounded Search request budget; split the question "
            "or lower top/fanout"
        ) from error
    return compact_graph_result(result) if detail == "compact" else result


def _load_html(uri: str) -> str:
    filename = RESOURCE_FILES[uri]
    try:
        root = files("adapters.mcp").joinpath("ui")
        provenance = json.loads(root.joinpath("build-provenance.json").read_bytes())
        expected = provenance["resources"][filename.removesuffix(".html")]
        data = root.joinpath(filename).read_bytes()
        if (len(data) != expected["rawHtmlBytes"]
                or hashlib.sha256(data).hexdigest() != expected["sha256"]):
            raise ValueError("accepted resource hash or size mismatch")
        html = data.decode("utf-8")
        if not html.strip():
            raise ValueError("empty resource")
        return html
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise RuntimeError(
            f"cannot load verified packaged EKG app {filename}; "
            "reinstall a complete ekg-skills-local package"
        ) from error


def create_server(*, descriptor_path: str | None = None):
    from mcp.server.apps import (
        Apps,
        ResourceCsp,
        ResourcePermissions,
        client_supports_apps,
    )
    from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
    from mcp.server.mcpserver import MCPServer
    from mcp.shared.exceptions import MCPError
    from mcp.types import ListResourcesResult, ListToolsResult

    descriptor = _load_descriptor(descriptor_path)
    apps = Apps()
    csp = ResourceCsp(
        connect_domains=[],
        resource_domains=[],
        frame_domains=[],
        base_uri_domains=[],
    )
    permissions = ResourcePermissions()
    for uri in RESOURCE_FILES:
        apps.add_html_resource(
            uri,
            _load_html(uri),
            csp=csp,
            permissions=permissions,
        )

    class AppsMiddleware:
        async def __call__(
            self,
            ctx: ServerRequestContext[Any, Any],
            call_next: CallNext,
        ) -> HandlerResult:
            supports_apps = client_supports_apps(ctx)
            if ctx.method == "server/discover" and not supports_apps:
                result = await call_next(ctx)
                if isinstance(result, dict):
                    capabilities = result.get("capabilities")
                    if isinstance(capabilities, dict):
                        capabilities = dict(capabilities)
                        extensions = capabilities.get("extensions")
                        if isinstance(extensions, dict):
                            extensions = dict(extensions)
                            extensions.pop(EXTENSION_ID, None)
                            if extensions:
                                capabilities["extensions"] = extensions
                            else:
                                capabilities.pop("extensions", None)
                        return {**result, "capabilities": capabilities}
                return result

            if not supports_apps:
                if ctx.method == "tools/list":
                    return ListToolsResult(tools=[])
                if ctx.method == "resources/list":
                    return ListResourcesResult(resources=[])
                if ctx.method == "resources/read":
                    params = ctx.params or {}
                    uri = params.get("uri")
                    if type(uri) is str and uri in RESOURCE_FILES:
                        raise MCPError(-32002, "Resource not found")
                if ctx.method == "tools/call":
                    params = ctx.params or {}
                    name = params.get("name")
                    if type(name) is str and name in APP_TOOLS:
                        raise MCPError(-32601, "Tool not found")
                return await call_next(ctx)

            if ctx.method == "tools/call":
                params = ctx.params or {}
                name = params.get("name")
                if type(name) is str and name in APP_TOOLS:
                    arguments = params.get("arguments", {})
                    try:
                        validate_raw_arguments(name, arguments)
                    except ValueError as error:
                        raise MCPError(-32602, str(error)) from error
            return await call_next(ctx)

    def run_graph(query: str, depth: int = 2, top: int = 5, fanout: int = 20,
                  detail: Literal["compact", "full"] = "full") -> dict[str, Any]:
        return _query(descriptor, query, depth, top, fanout, detail)

    @apps.tool(
        resource_uri=GRAPH_RESOURCE_URI,
        visibility=["model"],
        description="Show a bounded EKG graph query with source evidence.",
    )
    def ekg_present(query: str, depth: int = 2, top: int = 5, fanout: int = 20,
                    detail: Literal["compact", "full"] = "full") -> dict[str, Any]:
        return run_graph(query, depth, top, fanout, detail)

    @apps.tool(
        resource_uri=EVIDENCE_RESOURCE_URI,
        visibility=["model"],
        description="Inspect graph relationships and their hydrated source evidence.",
    )
    def ekg_present_evidence(query: str, depth: int = 2, top: int = 5, fanout: int = 20,
                             detail: Literal["compact", "full"] = "full") -> dict[str, Any]:
        return run_graph(query, depth, top, fanout, detail)

    server = MCPServer(
        name="ekg-skills",
        version="0.1.0",
        extensions=[apps],
        middleware=[AppsMiddleware()],
    )

    @server.tool(
        name="ekg_graph_query",
        description="Read bounded graph and source evidence for the Apps presentation.",
        meta={"ui": {"visibility": ["app"]}},
    )
    def graph_query_read(query: str, depth: int = 2, top: int = 5, fanout: int = 20,
                         detail: Literal["compact", "full"] = "full") -> dict[str, Any]:
        return run_graph(query, depth, top, fanout, detail)

    return server


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="ekg-apps")
    parser.add_argument(
        "--descriptor",
        default=os.environ.get("EKG_DESCRIPTOR"),
        help="operator-selected absolute published descriptor (default: EKG_DESCRIPTOR/current)",
    )
    args = parser.parse_args(argv)
    try:
        server = create_server(descriptor_path=args.descriptor)
    except ModuleNotFoundError as error:
        if error.name and error.name.split('.')[0] == 'mcp':
            parser.exit(1, 'Apps support is optional; install it with `pip install ''ekg-skills-local[apps]''`.\n')
        raise
    except (FileNotFoundError, ValueError, RuntimeError) as error:
        parser.error(str(error))
    server.run()


if __name__ == "__main__":
    main()
