"""Write a published descriptor and say how to browse it from Copilot CLI."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ekg_core.descriptors import (
    default_descriptor_path, descriptor_name, write_current,
)

AUTH = "Microsoft Entra ID through the signed-in Azure CLI (az login); no keys"


def write_descriptor(descriptor: dict[str, Any], out: str | None, previous: list[str],
                     tenant_id: str | None, *, set_current: bool = True) -> dict[str, Any]:
    path = (Path(out).expanduser().resolve() if out
            else default_descriptor_path(descriptor_name(descriptor)))
    if any(path == Path(item).expanduser().resolve() for item in previous):
        raise ValueError("--output must be a new file, not the previous --descriptor, "
                         "which publish reads to propose cleanup")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(descriptor, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    if set_current:
        write_current(path)
    prompt = ("Using the ekg-skills MCP tools, answer \"<your question>\" from the graph "
              "and cite the source file for every hop.")
    login = f"az login --tenant {tenant_id}" if tenant_id else "az login"
    browse = {"descriptor_path": str(path),
              "search_endpoint": descriptor.get("endpoints", {}).get("search"),
              "auth": AUTH, "tenant_id": tenant_id, "current": set_current,
              "commands": [login, "copilot"], "example_prompt": prompt}
    default_line = ("  then just ask; ekg-consume and the MCP tools use this descriptor by default."
                    if set_current else
                    f"  the current pointer is unchanged; name this descriptor in the prompt "
                    f"(descriptor_path {path}) or pass --descriptor to ekg-consume.")
    summary = "\n".join([
        f"Published descriptor: {path}",
        f"Search endpoint: {browse['search_endpoint']}",
        f"Auth: {AUTH}; tenant {tenant_id or '<the tenant you built in>'}",
        "Browse from Copilot CLI (with the ekg-skills plugin installed):",
        *(f"  {line}" for line in browse["commands"]),
        default_line,
        f"  for example: {prompt}",
    ])
    return {**descriptor, "status": "published", "descriptor_path": str(path),
            "browse": browse, "summary": summary}
