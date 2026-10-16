"""Read-only CLI for the candidate sidecar."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Callable

from grz_core.cli_output import add_json_option, add_version_option, error_body, emit
from grz_core.doctor import emit_doctor
from grz_core.contracts import ContractError

from .config import add_connection_options, build_service, resolve_config
from .service import ConsumeService

JSON_SCHEMA_VERSION = "grz-consume-v1"


def add_source_options(parser: argparse.ArgumentParser) -> None:
    add_connection_options(parser)
    parser.add_argument("--query-key", help="Azure Search query key; prefer GRZ_SEARCH_QUERY_KEY")


def make_service(args: argparse.Namespace) -> ConsumeService:
    return build_service(resolve_config(args))


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="grz-consume", description="Preview read-only candidate sidecar browser")
    add_source_options(result)
    add_json_option(result)
    add_version_option(result)
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Read only: check this machine, sign-in, descriptor and sidecar access")
    commands.add_parser("status")
    listing = commands.add_parser("list-communities")
    listing.add_argument("--level", type=int, help="Defaults to the level with about 10-30 communities; 0 is finest")
    listing.add_argument("--page-size", type=int, default=100)
    listing.add_argument("--cursor")
    community = commands.add_parser("get-community")
    community.add_argument("community_id")
    community.add_argument("--children-page-size", type=int, default=1000)
    community.add_argument("--children-cursor")
    members = commands.add_parser("list-members")
    members.add_argument("community_id")
    members.add_argument("--page-size", type=int)
    members.add_argument("--cursor")
    chunk = commands.add_parser("get-chunk")
    chunk.add_argument("chunk_id")
    for sub in commands.choices.values():
        add_json_option(sub, subcommand=True)
    return result



def _name(row: dict[str, Any]) -> str:
    return row.get("label") or "(unnamed)"


def _more(result: dict[str, Any], command: str) -> str:
    return f"\nMore: run the same {command} with --cursor {result['next_cursor']}" if result.get("next_cursor") else ""


CHECKS = {
    "build_attested_manifest_and_live_counts": "the live document counts match what the build verified",
}


def summarize_status(result: dict[str, Any]) -> str:
    counts = result.get("communities_per_level") or {}
    levels = ", ".join(f"level {level}: {counts[level]}" for level in sorted(counts, key=int, reverse=True))
    check = CHECKS.get(result["verification_scope"], result["verification_scope"])
    return (f"Ready: {check}.\n"
            f"Communities per level (0 is finest): {levels}.\n"
            f"Browsing starts at level {result['browse_level']}. Next: list-communities")


def summarize_communities(result: dict[str, Any]) -> str:
    rows = result["items"]
    lines = [f"{len(rows)} communities" + (f" at level {result['level']}" if "level" in result else "") + ":"]
    for row in sorted(rows, key=lambda r: -r["member_count"]):
        lines.append(f"  {_name(row)} - {row['member_count']} chunks  [{row['community_id']}]")
    lines.append("Next: get-community <id> or list-members <id>")
    return "\n".join(lines) + _more(result, "list-communities")


def summarize_community(result: dict[str, Any]) -> str:
    children = result.get("children") or []
    return (f"{_name(result)}: {result['member_count']} chunks at level {result['level']}, "
            f"{len(children)} finer communities.\nNext: list-members {result['community_id']}")


def summarize_members(result: dict[str, Any]) -> str:
    lines = [f"{len(result['items'])} members:"] + [f"  {r['source_id']}  [{r['chunk_id']}]" for r in result["items"]]
    return "\n".join(lines + ["Next: get-chunk <chunk id>"]) + _more(result, "list-members")


def summarize_chunk(result: dict[str, Any]) -> str:
    text = " ".join(str(result.get("text", "")).split())
    return f"{result.get('source_id')}\n{text[:600]}" + ("..." if len(text) > 600 else "")


def _emit_result(result: dict[str, Any], as_json: bool,
                 summary: Callable[[dict[str, Any]], str] | None) -> None:
    if as_json:
        print(json.dumps({"schema_version": JSON_SCHEMA_VERSION, "result": result},
                         sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")))
    else:
        emit(result, False, summary, compact=False)


def _emit_error(exc: BaseException, as_json: bool) -> int:
    body = error_body(exc, "QUERY_INVALID")
    if as_json:
        print(json.dumps({"schema_version": JSON_SCHEMA_VERSION, **body},
                         sort_keys=True, ensure_ascii=False), file=sys.stderr)
    else:
        print(f"Blocked. {body['error_code']}: {body['error']}\nNext step: {body['next_step']}",
              file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "doctor":
            from .doctor import run_doctor

            report = run_doctor(resolve_config(args))
            if args.json:
                _emit_result(report, True, None)
                return 0
            return emit_doctor(report, False, "grz-consume")
        service = make_service(args)
        if args.command == "status":
            result, summary = service.status(), summarize_status
        elif args.command == "list-communities":
            level = args.level if args.level is not None else service.browse_level()
            result = {**service.list_communities(level, args.page_size, args.cursor), "level": level}
            summary = summarize_communities
        elif args.command == "get-community":
            result = service.get_community(args.community_id, args.children_page_size, args.children_cursor)
            summary = summarize_community
        elif args.command == "list-members":
            page_size = args.page_size if args.page_size is not None else 100
            result = service.list_members(args.community_id, page_size, args.cursor)
            summary = summarize_members
        else:
            result, summary = service.get_chunk(args.chunk_id), summarize_chunk
        _emit_result(result, args.json, summary)
        return 0
    except (ContractError, ValueError, OSError, TypeError, ImportError) as exc:
        return _emit_error(exc, args.json)


if __name__ == "__main__":
    raise SystemExit(main())
