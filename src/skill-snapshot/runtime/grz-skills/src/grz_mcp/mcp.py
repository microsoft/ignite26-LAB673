"""Optional official MCP SDK Apps adapter over bounded GRZ reads."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from grz_consume.config import ConsumeConfig, build_service
from grz_consume.service import ConsumeService
from grz_core.cli_output import error_body
from grz_core.contracts import ContractError
from grz_core.doctor import installed_version

from . import apps

SERVER_NAME = "grz-skills"
ALIASES = {
    "grz_explore": "grz_list_communities",
    "grz_evidence": "grz_get_chunk",
    "grz_app_list_members": "grz_list_members",
}

# type, required, min, max; optional arguments may be omitted or explicitly null.
ARGUMENTS: dict[str, dict[str, tuple[str, bool, int | None, int | None]]] = {
    "grz_status": {},
    "grz_list_communities": {
        "level": ("integer", False, 0, None),
        "page_size": ("integer", False, 1, 1000),
        "cursor": ("string", False, None, None),
    },
    "grz_get_community": {
        "community_id": ("identifier", True, None, None),
        "children_page_size": ("integer", False, 1, 1000),
        "children_cursor": ("string", False, None, None),
    },
    "grz_get_chunk": {"chunk_id": ("identifier", True, None, None)},
    "grz_explore": {
        "level": ("integer", False, 0, None),
        "page_size": ("integer", False, 1, 1000),
        "cursor": ("string", False, None, None),
    },
    "grz_evidence": {"chunk_id": ("identifier", True, None, None)},
    "grz_app_list_members": {
        "community_id": ("identifier", True, None, None),
        "page_size": ("integer", False, 1, 1000),
        "cursor": ("string", False, None, None),
    },
}
APP_ONLY_TOOLS = frozenset(ARGUMENTS)

if TYPE_CHECKING:
    from mcp.server.context import CallNext, HandlerResult, ServerRequestContext


def _invalid(detail: str) -> ContractError:
    return ContractError("ARGS_INVALID", detail)


def _validate_arguments(name: str, arguments: Any) -> dict[str, Any]:
    if name not in ARGUMENTS:
        raise ContractError("TOOL_NOT_FOUND", f"No tool named {name!r}")
    if not isinstance(arguments, dict):
        raise _invalid("Tool arguments must be an object")
    if any(type(key) is not str for key in arguments):
        raise _invalid("Tool argument names must be strings")
    schema = ARGUMENTS[name]
    extra = set(arguments) - set(schema)
    if extra:
        raise _invalid(f"Unsupported argument(s): {', '.join(sorted(extra))}")
    for field, (kind, required, minimum, maximum) in schema.items():
        if field not in arguments:
            if required:
                raise _invalid(f"Missing required argument: {field}")
            continue
        value = arguments[field]
        if value is None:
            if required:
                raise _invalid(f"{field} must be a nonempty string")
            continue
        if kind in ("string", "identifier"):
            if type(value) is not str or not value:
                raise _invalid(f"{field} must be a nonempty string")
            if kind == "string" and value == "null":
                raise _invalid(f"{field} must not be the string 'null'; omit it or send JSON null")
        elif kind == "integer":
            if type(value) is not int or (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
                bounds = f"{minimum}..{maximum}" if maximum is not None else f">={minimum}"
                raise _invalid(f"{field} must be an integer in range {bounds}")
    return arguments


def _content(value: Any, *, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)}],
        "isError": is_error,
    }


def _dispatch(
    service: ConsumeService,
    name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    try:
        action = ALIASES.get(name, name)
        if action == "grz_status":
            result = service.status()
        elif action == "grz_list_communities":
            level = arguments.get("level")
            if level is None:
                level = service.browse_level()
            result = {
                **service.list_communities(level, arguments.get("page_size", 100) or 100,
                                           arguments.get("cursor")),
                "level": level,
            }
        elif action == "grz_get_community":
            result = service.get_community(arguments["community_id"],
                                           arguments.get("children_page_size", 1000) or 1000,
                                           arguments.get("children_cursor"))
        elif action == "grz_list_members":
            result = service.list_members(arguments["community_id"],
                                          arguments.get("page_size", 100) or 100,
                                          arguments.get("cursor"))
        elif action == "grz_get_chunk":
            result = service.get_chunk(arguments["chunk_id"])
        else:
            raise ContractError("TOOL_NOT_FOUND", f"No tool named {name!r}")
        return _content(result)
    except (ContractError, ValueError, OSError, TypeError, ImportError) as exc:
        return _content(error_body(exc, "QUERY_INVALID"), is_error=True)


def _call_tool(
    service: ConsumeService,
    name: str,
    arguments: Any,
) -> dict[str, Any]:
    """In-process tool dispatch shared by SDK handlers and focused service tests."""
    try:
        checked = _validate_arguments(name, arguments)
    except ContractError as exc:
        return _content(error_body(exc, "QUERY_INVALID"), is_error=True)
    return _dispatch(service, name, checked)


def _sdk_result(result: dict[str, Any]) -> Any:
    from mcp.types import CallToolResult, TextContent

    text = result["content"][0]["text"]
    return CallToolResult(
        content=[TextContent(text=text)],
        structuredContent=json.loads(text),
        isError=result["isError"],
    )


def _strip_discovery_extension(result: Any) -> Any:
    if isinstance(result, dict):
        capabilities = dict(result.get("capabilities") or {})
        extensions = dict(capabilities.get("extensions") or {})
        extensions.pop(apps.EXTENSION, None)
        if extensions:
            capabilities["extensions"] = extensions
        else:
            capabilities.pop("extensions", None)
        return {**result, "capabilities": capabilities}
    capabilities = result.capabilities
    extensions = dict(capabilities.extensions or {})
    extensions.pop(apps.EXTENSION, None)
    capabilities = capabilities.model_copy(update={"extensions": extensions or None})
    return result.model_copy(update={"capabilities": capabilities})


class AppsSessionMiddleware:
    """Gate app metadata, tools and resources against each connection's negotiated support."""

    async def __call__(
        self,
        ctx: ServerRequestContext[Any, Any],
        call_next: CallNext,
    ) -> HandlerResult:
        from mcp.server.apps import client_supports_apps
        from mcp.shared.exceptions import MCPError
        from mcp.types import ListResourcesResult, ListToolsResult

        apps_enabled = client_supports_apps(ctx)
        if ctx.params is None:
            params: dict[str, Any] = {}
        elif isinstance(ctx.params, Mapping):
            params = dict(ctx.params)
        else:
            raise MCPError(-32602, "Request parameters must be an object")

        if ctx.method == "tools/call":
            if set(params) - {"name", "arguments", "_meta"}:
                raise MCPError(-32602, "Unsupported tools/call parameter")
            name = params.get("name")
            if not isinstance(name, str) or name not in ARGUMENTS:
                raise MCPError(-32601, "Tool not found")
            if not apps_enabled:
                raise MCPError(-32601, "Tool not found")
            arguments = params.get("arguments", {})
            try:
                _validate_arguments(name, arguments)
            except ContractError as exc:
                raise MCPError(-32602, str(exc)) from exc
            return await call_next(ctx)

        if ctx.method == "resources/read":
            if not apps_enabled:
                raise MCPError(-32002, "Resource not found")
            uri = params.get("uri")
            if set(params) - {"uri", "_meta"} or not isinstance(uri, str) or uri not in apps.RESOURCES:
                raise MCPError(-32002, "Resource not found")

        if not apps_enabled and ctx.method == "tools/list":
            return ListToolsResult(tools=[])
        if not apps_enabled and ctx.method == "resources/list":
            return ListResourcesResult(resources=[])
        result = await call_next(ctx)
        if ctx.method == "server/discover" and not apps_enabled:
            return _strip_discovery_extension(result)
        return result


def create_server(config: ConsumeConfig, service: ConsumeService | None = None) -> Any:
    """Bind one read scope and verified Apps assets before accepting sessions."""
    from mcp.server.apps import Apps, ResourceCsp, ResourcePermissions
    from mcp.server.mcpserver import MCPServer
    from mcp.types import ToolAnnotations

    loaded_assets = apps.load_assets()
    extension = Apps()
    csp = ResourceCsp(connectDomains=[], resourceDomains=[], frameDomains=[], baseUriDomains=[])
    permissions = ResourcePermissions()
    for uri, (filename, title) in apps.RESOURCES.items():
        extension.add_html_resource(
            uri=uri,
            html=loaded_assets[filename],
            name=title,
            csp=csp,
            permissions=permissions,
            prefers_border=True,
        )

    bound_service = service

    def get_service() -> ConsumeService:
        nonlocal bound_service
        if bound_service is None:
            bound_service = build_service(config)
        return bound_service

    read_only = ToolAnnotations(readOnlyHint=True)
    app_only = {"ui": {"visibility": ["app"]}}

    def invoke(name: str, arguments: dict[str, Any]) -> Any:
        return _sdk_result(_dispatch(get_service(), name, arguments))

    @extension.tool(resource_uri="ui://grz/explorer.html", visibility=["model"],
                    name="grz_explore", description="Present a GRZ community explorer.",
                    annotations=read_only)
    def grz_explore(level: int | None = None, page_size: int | None = 100,
                    cursor: str | None = None) -> Any:
        return invoke("grz_explore", {"level": level, "page_size": page_size, "cursor": cursor})

    @extension.tool(resource_uri="ui://grz/evidence.html", visibility=["model"],
                    name="grz_evidence", description="Present GRZ chunk evidence.",
                    annotations=read_only)
    def grz_evidence(chunk_id: str) -> Any:
        return invoke("grz_evidence", {"chunk_id": chunk_id})

    server = MCPServer(
        name=SERVER_NAME,
        version=installed_version() or "unknown",
        extensions=[extension],
        middleware=[AppsSessionMiddleware()],
    )

    @server.tool(name="grz_status", description="Return verified status for the server-bound GRZ generation.",
                 annotations=read_only, meta=app_only)
    def grz_status() -> Any:
        return invoke("grz_status", {})

    @server.tool(name="grz_list_communities",
                 description="List a bounded page of communities at one hierarchy level.",
                 annotations=read_only, meta=app_only)
    def grz_list_communities(level: int | None = None, page_size: int | None = 100,
                             cursor: str | None = None) -> Any:
        return invoke("grz_list_communities", {"level": level, "page_size": page_size, "cursor": cursor})

    @server.tool(name="grz_get_community", description="Get one community and a bounded page of its children.",
                 annotations=read_only, meta=app_only)
    def grz_get_community(community_id: str, children_page_size: int | None = 1000,
                          children_cursor: str | None = None) -> Any:
        return invoke("grz_get_community", {
            "community_id": community_id,
            "children_page_size": children_page_size,
            "children_cursor": children_cursor,
        })

    @server.tool(name="grz_get_chunk", description="Get public chunk evidence by chunk ID.",
                 annotations=read_only, meta=app_only)
    def grz_get_chunk(chunk_id: str) -> Any:
        return invoke("grz_get_chunk", {"chunk_id": chunk_id})

    @server.tool(name="grz_app_list_members",
                 description="List community members in stable order without model calls.",
                 annotations=read_only, meta=app_only)
    def grz_app_list_members(community_id: str, page_size: int | None = 100,
                             cursor: str | None = None) -> Any:
        return invoke("grz_app_list_members", {
            "community_id": community_id,
            "page_size": page_size,
            "cursor": cursor,
        })

    return server
