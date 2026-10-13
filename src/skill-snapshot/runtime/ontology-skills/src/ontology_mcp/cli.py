"""`ontology-mcp` entry point: `ontology-mcp [--state-dir <path>] [--self-test] [--json]`."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from ontology_core import output
from ontology_mcp import server


def default_state_dir() -> Path:
    """`$ONTOLOGY_STATE_DIR`, else `./.ontology-state`, made absolute."""
    return Path(os.environ.get("ONTOLOGY_STATE_DIR") or output.DEFAULT_STATE_DIR).expanduser().resolve()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ontology-mcp", description="Read-only MCP server over stdio.")
    output.add_version_flag(parser)
    parser.add_argument("--state-dir", help="state directory (default $ONTOLOGY_STATE_DIR or ./.ontology-state)")
    parser.add_argument("--self-test", action="store_true", help="list tools in-process and exit")
    output.add_json_flag(parser)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    state_dir = Path(args.state_dir).expanduser().resolve() if args.state_dir else default_state_dir()
    if args.self_test:
        result, code = output.run_verb(server.self_test, state_dir, json_mode=args.json)
        output.emit(result, args.json, lambda r: f"ok: {len(r['tools'])} tools")
        return code
    server.Server(state_dir).serve()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
