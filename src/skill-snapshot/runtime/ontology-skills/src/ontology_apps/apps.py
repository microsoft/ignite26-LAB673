"""Official-SDK Apps tools over the ontology's read-only services."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Any, Callable

from mcp.server.apps import Apps, ResourceCsp, ResourcePermissions, client_supports_apps
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.mcpserver import MCPServer
from mcp.shared.exceptions import MCPError
from mcp.types import CallToolResult, ListResourcesResult, ListToolsResult, TextContent, ToolAnnotations
from pydantic import Field

from ontology_core import __version__, state
from ontology_core.errors import Blocked, to_envelope
from ontology_consume import service

RESOURCE_FILES = {
    "ui://ontology-skills/ontology.html": "ontology.html",
    "ui://ontology-skills/evidence.html": "evidence.html",
}
SHOW_MAX_LIMIT = 200
EVIDENCE_MAX_LIMIT = 50
_READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)


class AppsExposureMiddleware:
    """Expose Apps tools/resources only to a session that negotiated the UI extension."""

    async def __call__(
        self,
        ctx: ServerRequestContext[Any, Any],
        call_next: CallNext,
    ) -> HandlerResult:
        supports_apps = client_supports_apps(ctx)
        if ctx.method == "server/discover":
            result = await call_next(ctx)
            if not supports_apps and isinstance(result, Mapping):
                capabilities = result.get("capabilities")
                if isinstance(capabilities, Mapping):
                    updated_capabilities = dict(capabilities)
                    extensions = updated_capabilities.get("extensions")
                    if isinstance(extensions, Mapping):
                        remaining = {
                            key: value for key, value in extensions.items() if key != "io.modelcontextprotocol/ui"
                        }
                        if remaining:
                            updated_capabilities["extensions"] = remaining
                        else:
                            updated_capabilities.pop("extensions")
                        return {**result, "capabilities": updated_capabilities}
            return result
        if not supports_apps:
            if ctx.method == "tools/list":
                return ListToolsResult(tools=[])
            if ctx.method == "resources/list":
                return ListResourcesResult(resources=[])
            if ctx.method == "resources/read" and (ctx.params or {}).get("uri") in RESOURCE_FILES:
                raise MCPError(code=-32002, message="Resource not found")
            if ctx.method == "tools/call":
                params = ctx.params or {}
                name = params.get("name")
                if name in TOOL_NAMES:
                    raise MCPError(code=-32601, message="Tool not found")
        if ctx.method == "tools/call":
            params = ctx.params or {}
            name = params.get("name")
            if name in TOOL_INPUTS:
                _validate_tool_arguments(name, params.get("arguments", {}))
        return await call_next(ctx)


TOOL_NAMES = frozenset({"ontology_present", "ontology_present_evidence", "ontology_show", "ontology_evidence"})
TOOL_INPUTS = {
    "ontology_present": frozenset({"version", "limit", "offset", "mermaid"}),
    "ontology_show": frozenset({"version", "limit", "offset", "mermaid"}),
    "ontology_present_evidence": frozenset({"type", "version", "limit"}),
    "ontology_evidence": frozenset({"type", "version", "limit"}),
}


def _validate_tool_arguments(name: str, arguments: Any) -> None:
    if not isinstance(arguments, Mapping):
        raise MCPError(code=-32602, message="Tool arguments must be an object")

    extra = set(arguments) - TOOL_INPUTS[name]
    if extra:
        raise MCPError(code=-32602, message=f"Unexpected tool argument(s): {', '.join(sorted(extra))}")

    for key, value in arguments.items():
        valid = False
        if key == "version":
            valid = value is None or (type(value) is int and value >= 0)
        elif key == "limit":
            maximum = SHOW_MAX_LIMIT if name in {"ontology_present", "ontology_show"} else EVIDENCE_MAX_LIMIT
            valid = type(value) is int and 0 <= value <= maximum
        elif key == "offset":
            valid = type(value) is int and value >= 0
        elif key == "mermaid":
            valid = type(value) is bool
        elif key == "type":
            valid = type(value) is str and len(value) > 0
        if not valid:
            raise MCPError(code=-32602, message=f"Invalid tool argument: {key}")

    if name in {"ontology_present_evidence", "ontology_evidence"} and "type" not in arguments:
        raise MCPError(code=-32602, message="Missing required tool argument: type")


def read_resource(uri: str) -> str:
    """Read one allowlisted packaged document without consulting the working directory."""
    try:
        filename = RESOURCE_FILES[uri]
    except KeyError:
        raise ValueError(f"resource not found: {uri}") from None
    try:
        root = files("ontology_apps").joinpath("ui")
        provenance = json.loads(root.joinpath("build-provenance.json").read_bytes())
        expected = provenance["resources"][filename.removesuffix(".html")]
        data = root.joinpath(filename).read_bytes()
        if (len(data) != expected["rawHtmlBytes"]
                or hashlib.sha256(data).hexdigest() != expected["sha256"]):
            raise ValueError("accepted resource hash or size mismatch")
        text = data.decode("utf-8")
        if not text.strip():
            raise ValueError("empty resource")
        return text
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(
            f"cannot load verified packaged Apps document {filename}; "
            "reinstall a complete ontology-skills package"
        ) from exc


def _tool_result(result: dict[str, Any]) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(result, sort_keys=True))],
        structured_content=result,
        is_error=result.get("status") != "ok",
    )


def _run_read(operation: Callable[..., dict[str, Any]], *args: Any, **kwargs: Any) -> CallToolResult:
    try:
        return _tool_result(operation(*args, **kwargs))
    except Blocked as exc:
        return _tool_result(to_envelope(exc))


def create_server(state_dir: Path) -> MCPServer:
    """Create a server whose read scope is fixed to the launch-time state directory."""
    paths = state.paths_for(state_dir)
    apps = Apps()

    @apps.tool(
        resource_uri="ui://ontology-skills/ontology.html",
        visibility=["model"],
        name="ontology_present",
        title="Inspect ontology",
        description="Read a versioned ontology and present it in the ontology view.",
        annotations=_READ_ONLY,
        structured_output=False,
    )
    def ontology_present(
        version: Annotated[int | None, Field(ge=0)] = None,
        limit: Annotated[int, Field(ge=0, le=SHOW_MAX_LIMIT)] = service.SHOW_DEFAULT_LIMIT,
        offset: Annotated[int, Field(ge=0)] = 0,
        mermaid: bool = False,
    ) -> CallToolResult:
        return _run_read(service.show, paths, version=version, limit=limit, offset=offset, mermaid=mermaid)

    @apps.tool(
        resource_uri="ui://ontology-skills/evidence.html",
        visibility=["model"],
        name="ontology_present_evidence",
        title="Inspect ontology evidence",
        description="Read the recorded evidence for a selected ontology type.",
        annotations=_READ_ONLY,
        structured_output=False,
    )
    def ontology_present_evidence(
        type: Annotated[str, Field(min_length=1)],
        version: Annotated[int | None, Field(ge=0)] = None,
        limit: Annotated[int, Field(ge=0, le=EVIDENCE_MAX_LIMIT)] = service.EVIDENCE_DEFAULT_LIMIT,
    ) -> CallToolResult:
        return _run_read(service.evidence, paths, type, version=version, limit=limit)

    for uri in RESOURCE_FILES:
        apps.add_html_resource(
            uri,
            read_resource(uri),
            name=RESOURCE_FILES[uri],
            csp=ResourceCsp(connect_domains=[], resource_domains=[], frame_domains=[], base_uri_domains=[]),
            permissions=ResourcePermissions(),
            prefers_border=True,
        )

    server = MCPServer(
        "ontology-skills",
        version=__version__,
        extensions=[apps],
        middleware=[AppsExposureMiddleware()],
    )

    @server.tool(
        name="ontology_show",
        description="Read a bounded page of ontology classes and properties.",
        annotations=_READ_ONLY,
        meta={"ui": {"visibility": ["app"]}},
        structured_output=False,
    )
    def ontology_show(
        version: Annotated[int | None, Field(ge=0)] = None,
        limit: Annotated[int, Field(ge=0, le=SHOW_MAX_LIMIT)] = service.SHOW_DEFAULT_LIMIT,
        offset: Annotated[int, Field(ge=0)] = 0,
        mermaid: bool = False,
    ) -> CallToolResult:
        return _run_read(service.show, paths, version=version, limit=limit, offset=offset, mermaid=mermaid)

    @server.tool(
        name="ontology_evidence",
        description="Read recorded passages cited for a class or property.",
        annotations=_READ_ONLY,
        meta={"ui": {"visibility": ["app"]}},
        structured_output=False,
    )
    def ontology_evidence(
        type: Annotated[str, Field(min_length=1)],
        version: Annotated[int | None, Field(ge=0)] = None,
        limit: Annotated[int, Field(ge=0, le=EVIDENCE_MAX_LIMIT)] = service.EVIDENCE_DEFAULT_LIMIT,
    ) -> CallToolResult:
        return _run_read(service.evidence, paths, type, version=version, limit=limit)

    return server
