"""Launch the optional official-SDK MCP Apps server over stdio."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from importlib.util import find_spec
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ontology-apps", description="Serve ontology MCP Apps over stdio.")
    parser.add_argument("--state-dir", required=True, help="explicit read-only ontology state directory")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    if find_spec("mcp") is None:
        raise SystemExit("Apps support is optional; install it with `pip install 'ontology-skills[apps]'`.")
    parser = build_parser()
    args = parser.parse_args(argv)
    state_dir = Path(args.state_dir).expanduser()
    if not state_dir.is_absolute():
        parser.error("--state-dir must be an absolute path")
    from ontology_apps.apps import create_server

    try:
        server = create_server(state_dir.resolve())
    except RuntimeError as error:
        parser.error(str(error))
    server.run()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
