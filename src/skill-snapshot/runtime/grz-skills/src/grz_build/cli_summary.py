"""Short grz-build summaries, plus the plan and descriptor files that let users skip copying IDs around."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from grz_core.cli_output import mb
from grz_core.contracts import ContractError, canonical_json
from grz_core.state import State

from grz_build.live import service_endpoint


def _quote(arg: str) -> str:
    # Single quotes work the same way in PowerShell and POSIX shells.
    return arg if re.fullmatch(r"[\w@%+=:,./\\-]+", arg) else "'" + arg.replace("'", "''") + "'"


def command_prefix(argv: list[str], command: str) -> str:
    """The user's own global flags, so a printed next step can be pasted as is."""
    head = argv[:argv.index(command)] if command in argv else []
    return " ".join(["grz-build", *(_quote(a) for a in head if a != "--json")])


def plan_path(state_dir: Path, plan_id: str) -> Path:
    return state_dir / "plans" / f"{plan_id}.json"


def descriptor_path(state_dir: Path) -> Path:
    return state_dir / "descriptor.json"


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(value), encoding="utf-8")


def latest_generation(state: State) -> str:
    built = [e["generation_id"] for e in state.events()
             if e.get("stage") == "apply" and e.get("state") == "verified" and e.get("generation_id")]
    if not built:
        raise ContractError("GENERATION_UNKNOWN", "No built generation in this state directory")
    return built[-1]


def fill_defaults(args: argparse.Namespace) -> None:
    """Let apply, reconcile and retire find the saved plan, and read-only verify find the latest build.

    publish is a write, so it never picks its generation implicitly; a stale or aborted build could be cut over unnamed.
    """
    if args.command in ("apply", "reconcile", "retire") and getattr(args, "plan_file", None) is None:
        if not getattr(args, "plan_id", None):
            raise ContractError("PLAN_NOT_FOUND", f"{args.command} needs --plan-id (or --plan-file)")
        args.plan_file = plan_path(args.state_dir, args.plan_id)
        if not args.plan_file.exists():
            raise ContractError("PLAN_NOT_FOUND", f"No saved plan {args.plan_id} in {args.state_dir}")
    if args.command == "publish" and getattr(args, "generation_id", None) is None:
        latest = latest_generation(State(args.state_dir / "operations"))
        error = ContractError("GENERATION_REQUIRED", "publish is a write and needs --generation-id naming the generation to cut over")
        error.next_step = f"pass --generation-id {latest} (the latest verified build) once that cutover is approved."
        raise error
    if args.command == "verify" and getattr(args, "generation_id", None) is None:
        args.generation_id = latest_generation(State(args.state_dir / "operations"))


def generation_descriptor_path(state_dir: Path, generation_id: str) -> Path:
    return state_dir / "descriptors" / f"{generation_id}.json"


def browse_settings(args: argparse.Namespace, result: dict[str, Any]) -> dict[str, Any]:
    """The environment a Copilot CLI session needs to browse the generation just published. Never a key or token."""
    env = {"GRZ_DESCRIPTOR": str(generation_descriptor_path(args.state_dir, result["generation_id"]).resolve()),
           "GRZ_SEARCH_ENDPOINT": service_endpoint(args.search_service),
           "GRZ_SEARCH_AUTH": "entra",
           "GRZ_TENANT_ID": args.tenant_id}
    return {"env": env,
            "powershell": [f"$env:{name} = '{value}'" for name, value in env.items()],
            "note": "Set these in the shell, then start Copilot CLI from it so the GRZ MCP server inherits them."}


def save_artifacts(args: argparse.Namespace, result: dict[str, Any]) -> None:
    # The approval card is display-only; saved plans and descriptors must match their digests without it.
    result = {k: v for k, v in result.items() if k != "approval_card"}
    if args.command in ("plan", "plan-retire") and "plan_id" in result:
        _write(plan_path(args.state_dir, result["plan_id"]), result)
    elif args.command == "apply" and "generation_id" in result:
        _write(generation_descriptor_path(args.state_dir, result["generation_id"]), result)
        _write(descriptor_path(args.state_dir), result)


def _approve_line(result: dict[str, Any], prefix: str) -> str:
    flags = f"--plan-id {result['plan_id']} --approved-budget-bytes {result['estimated_bytes']}"
    if result.get("backend") == "azure":
        flags += " --confirm-writes"
    if result.get("naming_model"):
        flags += " --approve-model-calls"
    return f"To run it after approval:\n  {prefix} apply {flags}"


def _card(result: dict[str, Any]) -> str | None:
    card = result.get("approval_card")
    return card["text"] if card else None


def summarize_plan(result: dict[str, Any], prefix: str) -> str:
    card = _card(result)
    if card:
        return "\n".join([card, *(result.get("warnings") or []), _approve_line(result, prefix)])
    source = result["source"]
    lines = [f"Plan {result['plan_id']}",
             f"  Builds communities from {source['expected_count']:,} chunks in {source['index']} "
             f"({source['dimension']}-d, {source['embedding_model_id']}).",
             f"  Writes one new index{' ' + result['target_index'] if result.get('target_index') else ''} "
             f"of up to {result['estimated_documents']:,} documents, within a budget of {mb(result['estimated_bytes'])}.",
             f"  Nothing goes live until you publish to {result['alias']}."]
    budget = result.get("naming_budget")
    if budget:
        lines.append(f"  Names communities: up to {budget['max_calls']} model calls, {budget['max_tokens']:,} tokens, "
                     f"${budget['max_spend']:.2f}.")
    readers = result.get("reader_grants")
    if readers:
        lines.append(f"  Will {readers['approval']}.")
    attested = result.get("source_visibility")
    if attested:
        lines.append(f"  {attested['approval']}. The index has no per-document visibility field to check.")
    lines += [f"  {w}" for w in result.get("warnings") or []]
    return "\n".join(lines + [_approve_line(result, prefix)])


def _publish_line(result: dict[str, Any], prefix: str) -> str:
    card = _card(result)
    return (card + "\n" if card else "") + f"To publish it after approval:\n  {prefix} publish --generation-id {result['generation_id']} --approve-cutover"


def summarize_apply(result: dict[str, Any], state_dir: Path, prefix: str) -> str:
    return ("Built and verified a new generation. It isn't live yet.\n"
            f"Descriptor for Consume: {descriptor_path(state_dir)}\n"
            f"Next, read it back; verify shows the publish approval:\n  {prefix} verify --generation-id {result['generation_id']}")


def summarize_verify(result: dict[str, Any], prefix: str) -> str:
    counts = result["counts"]
    text = ("Verified: every document read back. "
            + ", ".join(f"{counts[k]:,} {k}" for k in sorted(counts)) + ".")
    usage = result.get("naming_usage")
    if usage:
        text += (f"\nNaming used {usage.get('calls', 0)} calls, {usage.get('input_tokens', 0) + usage.get('output_tokens', 0):,} tokens, "
                 f"${float(usage.get('spend_usd', 0)):.3f}.")
    return text + ("\n" + _publish_line(result, prefix) if result.get("generation_id") else "")


def summarize_publish(result: dict[str, Any]) -> str:
    text = "Published. Consumers of this dataset now see the new communities."
    browse = result.get("browse")
    if browse:
        text += ("\ngrz-consume and the grz-skills MCP tools now browse this build by default; "
                 "start Copilot CLI and ask what topics exist.")
        text += "\nTo browse it from another account or machine, set:\n" + "\n".join(f"  {line}" for line in browse["powershell"])
    return text


def summarize_status(result: dict[str, Any]) -> str:
    serving = result.get("active_physical_index")
    incomplete = result.get("incomplete_generations") or []
    text = (f"Published: {result['alias']} serves {serving}." if serving
            else "Nothing is published yet.")
    if incomplete:
        text += f"\n{len(incomplete)} build(s) failed; run reconcile before retrying."
    return text


def summarize_generations(result: dict[str, Any]) -> str:
    lines = [f"  {row['role']:<13} {row['index']}  {row['document_count']:,} docs, {mb(row['storage_bytes'])}"
             for row in result["generations"]]
    candidates = result.get("retire_candidates") or []
    tail = f"Can be retired: {', '.join(candidates)}" if candidates else "Nothing to retire."
    return "\n".join(["Generations:"] + lines + [tail])


def summarize_retire_plan(result: dict[str, Any], prefix: str) -> str:
    card = _card(result)
    if card:
        return card + f"\nTo run it after approval:\n  {prefix} retire --plan-id {result['plan_id']} --confirm-writes"
    readers = result.get("reader_grants") or []
    return (f"Retire plan {result['plan_id']}\n"
            f"  Deletes {result['index']} ({result['document_count']:,} docs, {mb(result['storage_bytes'])}). "
            "The published generation and the source index are untouched."
            + (f"\n  Also removes {len(readers)} reader grant(s) on it." if readers else "")
            + f"\nTo run it after approval:\n  {prefix} retire --plan-id {result['plan_id']} --confirm-writes")


def summarize_retire(result: dict[str, Any]) -> str:
    revoked = result.get("reader_grants_revoked")
    return f"Retired {result['index']}; checked it's gone and the published generation didn't move." + (
        f" Removed {revoked} reader grant(s)." if revoked else "")


def summarize_inspect(result: dict[str, Any], prefix: str) -> str:
    stats = result.get("index_stats") or {}
    headroom = result.get("headroom") or {}
    lines = ["Source looks usable for a GRZ build."]
    if stats:
        lines.append(f"  {int(stats.get('documentCount') or 0):,} documents, {mb(stats.get('storageSize'))}.")
    if headroom:
        lines.append(f"  {headroom.get('free_index_slots')} free index slot(s) on the service.")
    lines += [f"  {w}" for w in result.get("warnings") or []]
    return "\n".join(lines + [f"Next:\n  {prefix} plan"])


def summarize(args: argparse.Namespace, argv: list[str], result: Any) -> str | None:
    command = args.command
    prefix = command_prefix(argv, command)
    with_prefix = {"plan": summarize_plan, "plan-retire": summarize_retire_plan, "inspect": summarize_inspect,
                   "verify": summarize_verify}
    plain = {"publish": summarize_publish, "status": summarize_status,
             "generations": summarize_generations, "retire": summarize_retire}
    if command == "apply":
        return summarize_apply(result, args.state_dir, prefix)
    if command in with_prefix:
        return with_prefix[command](result, prefix)
    return plain[command](result) if command in plain else None
