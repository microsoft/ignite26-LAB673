"""Run the optional read-only GRZ MCP Apps adapter over the official SDK stdio transport."""

from __future__ import annotations

import argparse
import json
import sys

from grz_consume.config import add_connection_options, resolve_config
from grz_core.cli_output import add_version_option, error_body
from grz_core.contracts import ContractError


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="grz-mcp",
        description=(
            "Read-only GRZ Apps adapter. Descriptor and Azure connection scope are bound "
            "at startup; tool calls cannot override them."
        ),
    )
    add_connection_options(result)
    result.add_argument("--query-key", help="Azure Search query key; prefer GRZ_SEARCH_QUERY_KEY")
    add_version_option(result)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        config = resolve_config(args)
        from .mcp import create_server

        server = create_server(config)
        # MCP stdio is UTF-8 JSON-RPC; Windows pipes otherwise default to the ANSI code page.
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
        server.run()
        return 0
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.split('.')[0] == 'mcp':
            print(json.dumps({'error': 'Apps support is optional; install it with `pip install ''grz-skills[apps]''`.', 'error_code': 'APPS_EXTRA_MISSING', 'status': 'blocked'}, sort_keys=True), file=sys.stderr)
            return 2
        print(json.dumps(error_body(exc, 'CLI_ERROR'), sort_keys=True, ensure_ascii=False), file=sys.stderr)
        return 2
    except (ContractError, ValueError, OSError, TypeError, ImportError) as exc:
        print(json.dumps(error_body(exc, "CLI_ERROR"), sort_keys=True, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
