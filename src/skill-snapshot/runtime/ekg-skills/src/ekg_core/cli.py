"""House style shared by every ekg-skills CLI.

* argparse subparsers; a bare invocation prints help.
* A 3-6 line human summary by default; ``--json`` (before or after the verb) prints the
  full result.
* Every blocked or error result is ``{"status": "blocked", "error_code", "error",
  "next_step"}`` with exit code 2. ``next_step`` comes from :data:`NEXT_STEPS`, one table
  keyed by ``error_code``.
"""

from __future__ import annotations

import argparse
import json
import re
import string
import sys
from typing import Any, NoReturn, Sequence

EXIT_BLOCKED = 2

# One next step per error code. Placeholders are filled from the blocking context; any
# placeholder without a value is rendered as ``<name>``.
NEXT_STEPS: dict[str, str] = {
    "USAGE": "Run `{prog} {command} --help` and supply the missing or corrected flags.",
    "INVALID_INPUT": "Correct the input named in the error, then run `{prog} {command}` again.",
    "LOCAL_IO": "Check that the named local file or folder exists and is readable or "
                "writable, then run `{prog} {command}` again.",
    "APPROVAL_REQUIRED": "Review the plan with `{prog} {plan_verb}`, get explicit approval "
                         "of its plan ID, then run `{prog} {command}` with the same flags "
                         "plus --plan-id <approved-id> --confirm-writes.",
    "TENANT_MISMATCH": "Name the intended tenant, then select it with `az login --tenant "
                       "<tenant-id>` and run `{prog} doctor --tenant-id <tenant-id>`.",
    "AZ_SIGNIN": "Name the intended tenant, then sign in with `az login --tenant "
                 "<tenant-id>` and run `{prog} doctor --tenant-id <tenant-id>`.",
    "AZURE_ERROR": "Run `{prog} doctor` to check sign-in and access, then retry the "
                   "read-only command; never retry a write whose outcome is unknown.",
    "PLAN_BLOCKED": "Resolve the first blocker, then run `{prog} plan` again and review "
                    "the new plan ID.",
    "APPLY_INCOMPLETE": "Run `{prog} reconcile` with the same flags to learn the outcome; "
                        "do not re-run apply until reconcile says it is safe.",
    "RETIRE_BLOCKED": "Resolve the blocker, then run `{prog} plan-retire` again and review "
                      "the new plan ID.",
    "RETIRE_STOPPED": "Run `{prog} plan-retire` again with the same flags to see what is "
                      "left, and approve that new plan ID.",
    "UPDATE_BLOCKED": "Resolve the blocker, then run `{prog} plan-update` again and review "
                      "the new plan ID.",
    "UPDATE_WAITING": "Run `{prog} update` again with the same --plan-id to finish; it "
                      "resumes from the journal.",
    "UPDATE_STOPPED": "Run `{prog} update` again with the same --plan-id; it resumes from "
                      "the journal and never repeats a write whose outcome is unknown.",
    "UPDATE_INCONSISTENT": "Rebuild with `{prog} plan` and `{prog} apply`; the in-place update "
                           "left the graph inconsistent.",
    "SOURCE_UNAVAILABLE": "Check the source location and your read access to it, then run "
                          "`{prog} inventory` again.",
    "RBAC_BLOCKED": "Resolve the blocker, then run `{prog} plan-rbac` again and review the "
                    "new plan ID.",
    "BUILD_BLOCKED": "Resolve the blocker in the plan, then run `{prog} plan` again.",
    "PROVISION_INCOMPLETE": "Run `{prog} inspect` with the same flags, then review "
                            "`{prog} plan-resume`; never retry an unknown-outcome write.",
    "PROVISION_FAILED": "Run `{prog} inspect` with the same flags to see what exists, then "
                        "review `{prog} plan-resume` before any further write.",
    "PUBLIC_DATA_STOPPED": "Run `{prog} inspect` with the same flags and review the local "
                           "journal. Do not retry, resume or clean up automatically. "
                           "Review a fresh isolated plan and obtain new exact approval "
                           "before further provisioning; cleanup needs separate approval.",
    "SMOKE_FAILED": "Run `{prog} inspect` to confirm what exists, then review "
                    "`{prog} plan-smoke` again.",
    "CAPACITY_BLOCKED": "Resolve the blocker, then run `{prog} plan-capacity` again and "
                        "review the new plan ID.",
    "CONNECT_BLOCKED": "Resolve the first blocker, then run `{prog} connect` again.",
    "DESCRIPTOR_INVALID": "Publish a build with `ekg-build publish`, or pass --descriptor "
                          "<file>.",
    "CAPABILITY_UNAVAILABLE": "Use an operation the descriptor advertises; run "
                              "`ekg-consume capabilities --descriptor <path>` to list them.",
    "CONSUME_FAILED": "Run `ekg-consume doctor --descriptor <path>` to check the descriptor "
                      "and reader access, then retry the read-only query.",
    "DOCTOR_CLI_VERSION": "Reinstall the CLI from this plugin with `uv tool install "
                          "--force <plugin-root>`, then run `{prog} doctor` again.",
    "DOCTOR_PYTHON": "Install Python 3.12 or newer (for example `uv python install 3.12`) "
                     "and reinstall the CLI, then run `{prog} doctor` again.",
    "DOCTOR_UV": "Install uv (https://docs.astral.sh/uv/) and put it on PATH, then run "
                 "`{prog} doctor` again.",
    "DOCTOR_AZURE_SIGNIN": "Name the intended tenant, then run `az login --tenant "
                           "<tenant-id>` yourself and run `{prog} doctor --tenant-id "
                           "<tenant-id>` again.",
    "DOCTOR_STATE_DIR": "Make the state folder writable (or pass a writable "
                        "--state-dir), and remove leftover *.tmp files only after checking "
                        "no other command is running.",
    "DOCTOR_JOURNAL": "Run `{prog} {journal_verb}` with the same flags before anything "
                      "else; never re-run a write whose outcome is unknown.",
    "DOCTOR_DESCRIPTOR": "Pass --descriptor with a readable published descriptor written by "
                         "`ekg-build publish --output`.",
    "DOCTOR_SEARCH_READER": "Ask an owner of the Search service to grant your identity "
                            "Search Index Data Reader on the index, then run `{prog} doctor` "
                            "again.",
    "DOCTOR_GROUNDING_INDEX": "Use an existing Search index with an edgeList graph profile "
                              "(ekg-skills never creates one), readable by your identity, "
                              "with label rows (rdfs:label / skos:altLabel) whose graph_name "
                              "equals the plan's grounding.graph_name; then run `{prog} "
                              "doctor` again.",
    "GROUNDING_INDEX_UNREADABLE": "Ask an owner of the Search service to run `az role "
                                  "assignment create --assignee <your-object-id> --role "
                                  "\"Search Index Data Reader\" --scope "
                                  "<search-service-resource-id>`, then run `{prog} doctor` "
                                  "again.",
    "GROUNDING_INDEX_NOT_FOUND": "Check the grounding index name and Search endpoint (the "
                                 "index must already exist; ekg-skills never creates it), "
                                 "then run `{prog} doctor` again.",
    "DOCTOR_MODEL_ROLE": "Ask an owner to verify model-list authorization at {scope}: "
                         "assigned role-definition permissions, groups, active PIM, conditions "
                         "and deny policy. Do not infer a missing role or grant one automatically; "
                         "any optional grant needs separate approval. Then run `{prog} doctor` again.",
    "DOCTOR_MODEL_ENDPOINT": "Pass --openai-endpoint with the account's https endpoint (as "
                             "shown by `ekg-provision connect`), then run `{prog} doctor` again.",
    "DOCTOR_MODEL_DEPLOYMENT": "Fix the deployment name (list them with `ekg-provision "
                               "connect`), then run `{prog} doctor` again.",
}


class Blocked(Exception):
    """A blocked result with a known error code; ``result`` is merged into the envelope."""

    def __init__(self, code: str, error: str, *, result: dict[str, Any] | None = None,
                 **context: Any) -> None:
        if code not in NEXT_STEPS:
            raise KeyError(f"unknown error_code {code}")
        super().__init__(error)
        self.code = code
        self.error = error
        self.result = result
        self.context = context


class _Defaults(dict):
    def __missing__(self, key: str) -> str:
        return f"<{key}>"


def next_step(code: str, **context: Any) -> str:
    template = NEXT_STEPS[code]
    values = _Defaults({"plan_verb": "plan", "journal_verb": "reconcile", "command": "",
                        **{k: v for k, v in context.items() if v is not None}})
    text = " ".join(string.Formatter().vformat(template, (), values).split())
    return re.sub(r" +`(?=[\s.,;:)]|$)", "`", text)


def envelope(code: str, error: str, **context: Any) -> dict[str, Any]:
    return {"status": "blocked", "error_code": code, "error": error,
            "next_step": next_step(code, **context)}


_JSON_MODE = False


def json_mode() -> bool:
    return _JSON_MODE


def emit_blocked(code: str, error: str, *, result: dict[str, Any] | None = None,
                 **context: Any) -> NoReturn:
    body = {**(result or {}), **envelope(code, error, **context)}
    if _JSON_MODE:
        print(json.dumps(body, indent=2, default=str))
    else:
        print(f"Blocked ({code}): {error}")
        print(f"Next: {body['next_step']}")
    raise SystemExit(EXIT_BLOCKED)


def report(error: Blocked, *, prog: str, command: str) -> NoReturn:
    emit_blocked(error.code, error.error, result=error.result,
                 **{"prog": prog, "command": command, **error.context})


class HouseParser(argparse.ArgumentParser):
    """Argument errors use the blocked envelope with code USAGE and exit code 2."""

    def error(self, message: str) -> NoReturn:
        prog, _, command = self.prog.partition(" ")
        emit_blocked("USAGE", message, prog=prog, command=command or "")


def add_json(parser: argparse.ArgumentParser, *, top: bool = False) -> None:
    parser.add_argument("--json", action="store_true",
                        default=False if top else argparse.SUPPRESS,
                        help="print the full JSON result instead of the summary")


def new_parser(prog: str, description: str, version: str) -> tuple[HouseParser, Any]:
    parser = HouseParser(prog=prog, description=description)
    parser.add_argument("--version", action="version", version=f"%(prog)s {version}")
    add_json(parser, top=True)
    commands = parser.add_subparsers(dest="command", metavar="<command>")
    return parser, commands


def add_command(commands: Any, name: str, help_text: str,
                parents: Sequence[argparse.ArgumentParser] = ()) -> argparse.ArgumentParser:
    sub = commands.add_parser(name, help=help_text, description=help_text,
                              parents=list(parents))
    add_json(sub)
    return sub


def parse(parser: HouseParser, argv: Sequence[str] | None,
          defaults: dict[str, Any] | None = None) -> argparse.Namespace:
    global _JSON_MODE
    argv = list(sys.argv[1:] if argv is None else argv)
    _JSON_MODE = "--json" in argv
    if not argv:
        parser.print_help()
        raise SystemExit(0)
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        raise SystemExit(0)
    for key, value in (defaults or {}).items():
        if not hasattr(args, key):
            setattr(args, key, list(value) if isinstance(value, list) else value)
    _JSON_MODE = bool(args.json)
    return args


def summary_lines(result: Any, *, prog: str, command: str) -> list[str]:
    if not isinstance(result, dict):
        return [f"{prog} {command}: done."]
    card = result.get("approval_card")
    if isinstance(card, str) and card and not (result.get("blocked_by") or result.get("blockers")):
        # The approval card is shown verbatim; it is the one thing a user approves.
        return card.splitlines() + ["Add --json for the full result."]
    status = result.get("status")
    if status is None and "completed" in result:
        status = "completed" if result["completed"] else "incomplete"
    head = str(result.get("summary") or f"{prog} {command}: {status or 'done'}.").splitlines()
    extra = []
    facts = []
    for key, label in (("plan_id", "Plan ID"), ("run_id", "Run ID"),
                       ("generation", "Generation")):
        if isinstance(result.get(key), str):
            facts.append(f"{label}: {result[key]}")
    if status and "summary" in result:
        facts.append(f"Status: {status}")
    if facts:
        extra.append("; ".join(facts))
    blockers = result.get("blocked_by") or result.get("blockers")
    covered = result.get("grounding_coverage")
    if isinstance(covered, dict) and covered.get("status") == "measured":
        confidence = covered.get("mean_confidence")
        extra.append(f"Grounding: {covered['end_share']:.0%} of {covered['edges']} edges' "
                     "endpoints resolved" + (f", mean confidence {confidence}"
                                              if confidence is not None else ""))
    if isinstance(blockers, list) and blockers:
        more = f" (+{len(blockers) - 1} more)" if len(blockers) > 1 else ""
        extra.append(f"Blocked by: {blockers[0]}{more}")
    if result.get("warning"):
        # A warning is never squeezed out by the line budget below.
        head.append(f"Warning: {result['warning']}")
    tail = []
    step = result.get("next_step") or result.get("next_action")
    if isinstance(step, str) and step:
        tail.append(f"Next: {step}")
    if len(head) < 5:
        tail.append("Add --json for the full result.")
    room = max(0, 6 - len(head) - len(tail))
    return head + extra[:room] + tail


def say(result: Any, args: argparse.Namespace, *, prog: str, file: Any = None) -> None:
    if args.json:
        print(json.dumps(result, indent=2, default=str), file=file)
        return
    for line in summary_lines(result, prog=prog, command=args.command):
        print(line, file=file)
