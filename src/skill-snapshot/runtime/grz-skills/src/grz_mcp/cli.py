"""grz-mcp: the read-only grz-skills MCP server the plugin starts over stdio."""

from __future__ import annotations

import argparse
import json
import sys

from grz_consume.config import add_connection_options, resolve_config
from grz_core.cli_output import add_version_option, error_body
from grz_core.contracts import ContractError

from .mcp import Server, self_test, serve


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="grz-mcp",
        description="Preview read-only grz-skills MCP server. The descriptor is bound at start "
                    "(--descriptor or GRZ_DESCRIPTOR); each tool also accepts an absolute descriptor_path.")
    add_connection_options(result)
    result.add_argument("--self-test", action="store_true",
                        help="Start the server in memory, list its tools, print JSON and exit")
    add_version_option(result)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        config = resolve_config(args)
        server = Server(config)
        if args.self_test:
            print(json.dumps(self_test(server), sort_keys=True))
            return 0
        if config.descriptor is not None:
            # Fail fast at start when a bound descriptor or connection is broken.
            server.service()
        # MCP stdio is UTF-8 JSON-RPC; Windows pipes otherwise default to the ANSI code page.
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
        return serve(server, sys.stdin, sys.stdout)
    except (ContractError, ValueError, OSError, TypeError, ImportError) as exc:
        print(json.dumps(error_body(exc, "CLI_ERROR"), sort_keys=True, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
