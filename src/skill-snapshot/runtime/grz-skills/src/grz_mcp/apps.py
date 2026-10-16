"""Optional MCP Apps assets for the official MCP SDK adapter."""

from __future__ import annotations

import hashlib
import json
from importlib.resources import files

from grz_core.contracts import ContractError

try:
    from mcp.server.apps import APP_MIME_TYPE, EXTENSION_ID
except ImportError:  # the base build/consume install does not depend on MCP
    APP_MIME_TYPE = "text/html;profile=mcp-app"
    EXTENSION_ID = "io.modelcontextprotocol/ui"

EXTENSION = EXTENSION_ID
MIME_TYPE = APP_MIME_TYPE
RESOURCES = {
    "ui://grz/explorer.html": ("explorer.html", "GRZ communities"),
    "ui://grz/evidence.html": ("evidence.html", "GRZ chunk evidence"),
}
ASSET_FILES = frozenset({
    "explorer.html", "evidence.html", "explorer.THIRD_PARTY_NOTICES.txt",
    "evidence.THIRD_PARTY_NOTICES.txt", "build-provenance.json", "bundle-report.json",
})


def load_assets() -> dict[str, str]:
    """Missing, incomplete or altered packaged Apps assets fail closed."""
    root = files("grz_mcp").joinpath("assets")
    try:
        manifest = json.loads(root.joinpath("assets.json").read_text(encoding="utf-8"))
        if manifest.get("version") != "grz-app-assets-v1" or set(manifest["files"]) != ASSET_FILES:
            raise ValueError("Unsupported asset manifest")
        result = {}
        for name, expected in manifest["files"].items():
            data = root.joinpath(name).read_bytes()
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError(f"Packaged asset hash mismatch: {name}")
            result[name] = data.decode("utf-8")
        return result
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ContractError("APP_ASSETS_INVALID", str(exc)) from exc
