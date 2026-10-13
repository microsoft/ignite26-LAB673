"""grz-build CLI for approval-gated Azure builds."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from grz_build import approval_card
from grz_build.cli_summary import browse_settings, fill_defaults, save_artifacts, summarize
from grz_build.execution import BuildService
from grz_build.generations import list_generations, plan_retire, retire
from grz_build.live import create_live_store, target_index_for_plan
from grz_build.naming import NamingBudget
from grz_build.naming_azure import API_VERSION as NAMING_API_VERSION
from grz_build.naming_azure import PROMPT_VERSION as NAMING_PROMPT_VERSION
from grz_build.naming_azure import AzureOpenAIChatNamer
from grz_build.planner import plan as make_plan
from grz_build.profiles import BUNDLED_PROFILES, load_profile
from grz_build.reader_grants import GRANT_ACTIONS, reader
from grz_core.cli_output import add_json_option, add_version_option, emit, emit_error
from grz_core.doctor import emit_doctor
from grz_core.contracts import (VISIBILITY_BASES, BuildProfile, ContractError, SourceIdentity, attestation_text,
                                 canonical_json, digest)
from grz_core.current import record_current
from grz_core.state import State


LIVE_REQUIRED = ["tenant_id", "subscription_id", "resource_group", "search_service", "source_index",
                 "key_field", "text_field", "source_field", "vector_field", "embedding_model_id",
                 "dataset", "owner_approval", "frozen_evidence", "security_inspection"]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="grz-build",
        description="Preview GRZ sidecar Build; gated live Azure requires explicit tenant/resource approvals."
    )
    parser.add_argument("--state-dir", type=Path, default=Path(".grz-state"))
    parser.add_argument("--profile", default="build-config",
                        help=f"Build profile: a JSON file, or a bundled name ({', '.join(BUNDLED_PROFILES)})")
    parser.add_argument(
        "--backend", choices=["azure"], default="azure",
        help="live Azure, gated, Entra/RBAC only",
    )
    parser.add_argument("--tenant-id", help="Azure tenant ID; no default identity tenant is assumed")
    parser.add_argument("--subscription-id", help="Azure subscription ID for the Search service")
    parser.add_argument("--resource-group", help="Azure resource group for the Search service")
    parser.add_argument("--search-service", help="Azure Search service name (not a URL)")
    parser.add_argument("--source-index", help="Physical source index name")
    parser.add_argument("--key-field", help="Source key field")
    parser.add_argument("--text-field", help="Source text field")
    parser.add_argument("--source-field", help="Source reference field")
    parser.add_argument("--vector-field", help="Source vector field")
    parser.add_argument("--security-field", action="append", default=[], help="Repeat for every source security/visibility field; each must read public")
    parser.add_argument("--source-visibility", choices=VISIBILITY_BASES, default="per-document",
                        help="per-document (default): every document's --security-field must read public. "
                             "public-attested (live only): you confirm every document in an index with no "
                             "visibility field is public; recorded in the plan and descriptor")
    parser.add_argument("--embedding-model-id", help="Owner-provided embedding model identity")
    parser.add_argument("--dataset", help="Lowercase GRZ dataset slug used in target index names")
    parser.add_argument("--alias", help="GRZ serving alias; azure derives grz-{dataset}-{vector-field}-active when omitted")
    parser.add_argument("--owner-approval", help="Named source owner approval attestation")
    parser.add_argument("--frozen-evidence", help="Producer freeze evidence attestation")
    parser.add_argument("--security-inspection", help="Source security inspection attestation")
    parser.add_argument("--native-binary", type=Path, help="Explicit path to the GRZBuildPoc native binary for your platform")
    add_json_option(parser)
    add_version_option(parser)
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor", help="Read only: check this machine, sign-in, state, journal and reader access")
    doctor.add_argument("--naming-endpoint", help="Also check this Azure OpenAI endpoint (metadata only)")
    doctor.add_argument("--naming-deployment", help="Naming deployment to check alongside --naming-endpoint")
    doctor.add_argument("--naming-resource-group",
                        help="Resource group of the Azure OpenAI account for the read-only ARM deployment check; "
                             "defaults to --resource-group")
    doctor.add_argument("--naming-model",
                        help="Model to check for deprecation when the deployment doesn't exist yet: <name>-<version> or <name>")
    commands.add_parser("inspect")
    plan = commands.add_parser("plan", help="Read only: print the plan and save it under --state-dir/plans")
    readers = plan.add_argument_group(
        "reader grants (live only)",
        "Search Index Data Reader grants on the published index are carried to the new index by default. "
        "The reader set enters the plan ID.")
    readers.add_argument("--reader", action="append", default=[], metavar="PRINCIPAL_ID",
                         help="Also grant this principal object ID read access to the new index (repeatable)")
    readers.add_argument("--drop-reader", action="append", default=[], metavar="PRINCIPAL_ID",
                         help="Don't carry this principal's read access to the new index (repeatable)")
    naming = plan.add_argument_group(
        "opt-in community naming (live only)",
        "Name each community with an Azure OpenAI chat deployment. The model spec and budget enter the plan ID; "
        "communities stay unnamed when these flags are omitted.")
    naming.add_argument("--naming-endpoint", help="Azure OpenAI endpoint URL; Entra auth only")
    naming.add_argument("--naming-deployment", help="Chat deployment name; turns naming on")
    naming.add_argument("--naming-model", help="Model behind the deployment, recorded in the plan")
    naming.add_argument("--naming-max-calls", type=int, help="At most one call per community")
    naming.add_argument("--naming-max-tokens", type=int, help="Total prompt plus completion tokens")
    naming.add_argument("--naming-max-spend-usd", type=float, help="Total spend at the stated prices")
    naming.add_argument("--naming-timeout-seconds", type=float, default=60.0, help="Per call")
    naming.add_argument("--naming-input-price-per-1m", type=float, help="USD per 1M prompt tokens")
    naming.add_argument("--naming-output-price-per-1m", type=float, help="USD per 1M completion tokens")
    naming.add_argument("--naming-members-per-prompt", type=int, default=12, help="Distinct sources sampled per community")
    naming.add_argument("--naming-excerpt-chars", type=int, default=200, help="Text excerpt per sampled source")
    naming.add_argument("--naming-max-output-tokens", type=int, default=512, help="Completion cap per call, reasoning included")
    apply = commands.add_parser("apply")
    apply.add_argument("--plan-id", required=True)
    apply.add_argument("--plan-file", type=Path, help="Defaults to the plan saved by plan in --state-dir")
    apply.add_argument("--approved-budget-bytes", type=int, required=True)
    apply.add_argument("--confirm-writes", action="store_true", help="Required for --backend azure before any live write")
    apply.add_argument("--approve-model-calls", action="store_true", help="Required when the plan names communities")
    apply.add_argument("--resume-after-reconcile", action="store_true", help="Resume a live plan after reconcile confirms unresolved writes")
    latest = "Defaults to the latest built generation in --state-dir"
    verify = commands.add_parser("verify")
    verify.add_argument("--generation-id", help=latest)
    publish = commands.add_parser("publish")
    publish.add_argument("--generation-id", help=latest)
    publish.add_argument("--approve-cutover", action="store_true")
    reconcile = commands.add_parser("reconcile")
    reconcile.add_argument("--plan-id")
    reconcile.add_argument("--plan-file", type=Path, help="Defaults to the saved plan named by --plan-id")
    commands.add_parser("status")
    commands.add_parser("generations", help="Live only, read only: list grz-{dataset}- generations and which alias binds each")
    plan_retire = commands.add_parser("plan-retire", help="Live only, read only: bind one superseded generation to a retire plan ID")
    plan_retire.add_argument("--index", required=True, help="Physical generation index to retire")
    retire = commands.add_parser("retire", help="Live only: delete one superseded generation named by an approved retire plan")
    retire.add_argument("--plan-id", required=True)
    retire.add_argument("--plan-file", type=Path, help="Defaults to the retire plan saved by plan-retire")
    retire.add_argument("--confirm-writes", action="store_true", help="Required before the delete request")
    for sub in commands.choices.values():
        add_json_option(sub, subcommand=True)
    return parser


NAMING_REQUIRED = ["naming_endpoint", "naming_model", "naming_max_calls", "naming_max_tokens",
                   "naming_max_spend_usd", "naming_input_price_per_1m", "naming_output_price_per_1m"]


def _naming_request(args: argparse.Namespace) -> tuple[NamingBudget, dict[str, Any]] | None:
    if not getattr(args, "naming_deployment", None):
        return None
    missing = ["--" + name.replace("_", "-") for name in NAMING_REQUIRED if getattr(args, name) is None]
    if missing:
        raise ContractError("NAMING_ARGS_REQUIRED", "Naming needs: " + ", ".join(missing))
    if not args.naming_endpoint.startswith("https://"):
        raise ContractError("NAMING_ENDPOINT_INVALID", "--naming-endpoint must be an https URL")
    budget = NamingBudget(args.naming_max_calls, args.naming_max_tokens, args.naming_max_spend_usd,
                          args.naming_timeout_seconds)
    model = {
        "provider": "azure-openai-chat", "endpoint": args.naming_endpoint.rstrip("/"),
        "deployment": args.naming_deployment, "model": args.naming_model, "api_version": NAMING_API_VERSION,
        "prompt_version": NAMING_PROMPT_VERSION, "members_per_prompt": args.naming_members_per_prompt,
        "excerpt_chars": args.naming_excerpt_chars, "max_output_tokens": args.naming_max_output_tokens,
        "input_price_per_1m": args.naming_input_price_per_1m, "output_price_per_1m": args.naming_output_price_per_1m,
    }
    return budget, model


def _reader_plan(args: argparse.Namespace, store: Any) -> dict[str, Any] | None:
    """Readers of the index behind the alias, plus --reader, minus --drop-reader. None keeps old plan IDs stable."""
    requested = [reader(pid) for pid in getattr(args, "reader", [])]
    dropped = sorted({reader(pid)["principal_id"] for pid in getattr(args, "drop_reader", [])})
    grants = getattr(store, "reader_grants", None)
    current_index = store.resolve_alias(args.alias) if grants is not None else None
    current = grants.list(current_index) if current_index else []
    if grants is None and requested:
        raise ContractError("READER_GRANTS_UNSUPPORTED", "This backend can't grant readers")
    carried = [{k: v for k, v in row.items() if k != "assignment_id"} for row in current if row["principal_id"] not in dropped]
    wanted: dict[tuple[str, str], dict[str, Any]] = {(r["principal_id"], r["role_definition_id"]): r for r in carried}
    for row in requested:
        wanted.setdefault((row["principal_id"], row["role_definition_id"]), row)
    if not wanted and not dropped:
        return None
    grant = [wanted[key] for key in sorted(wanted)]
    if grant:
        grants.check_can_manage(current_index or "the new index", GRANT_ACTIONS)
    return {"from_index": current_index, "grant": grant, "dropped": dropped,
            "approval": f"grant read access to {len(grant)} identit{'y' if len(grant) == 1 else 'ies'} on the new index"}


def _live_plan(args: argparse.Namespace, service: BuildService, store: Any, source: SourceIdentity,
               live: dict[str, Any], state: State) -> dict[str, Any]:
    """Bind the plan to the exact service, source definition, headroom and target so apply can detect drift."""
    inspected = service.inspect(source)
    profile = load_profile(args.profile)
    naming = _naming_request(args)
    base = make_plan(source, profile, target_service=source.service, alias=args.alias, inspected=inspected,
                     naming_budget=naming[0] if naming else None, naming_model=naming[1] if naming else None)
    data = {k: v for k, v in base.items() if k != "plan_id"}
    source_binding = store.source_binding(inspected)
    data.update({
        "backend": "azure", "tenant_id": args.tenant_id, "subscription_id": args.subscription_id,
        "resource_group": args.resource_group, "search_service": args.search_service,
        "endpoint": live["endpoint"], "dataset": args.dataset,
        "source_binding": source_binding,
        "alias_binding": {"alias": args.alias, "source_index": args.source_index, "vector_field": args.vector_field},
        "source_binding_digest": digest(source_binding),
        "warnings": inspected.get("warnings", []),
        "headroom": inspected.get("headroom"), "index_stats": inspected.get("index_stats"),
        "owner_approval": args.owner_approval, "frozen_evidence": args.frozen_evidence,
        "security_inspection": args.security_inspection,
    })
    reader_grants = _reader_plan(args, store)
    if reader_grants is not None:
        data["reader_grants"] = reader_grants
    if source_binding.get("visibility_basis") == "public-attested":
        data["source_visibility"] = {"basis": "public-attested", "index": args.source_index,
                                     "approval": attestation_text(args.source_index)}
    data["target_index"] = target_index_for_plan(args.dataset, data)
    result = {"plan_id": digest(data), **data}
    state.record(result["plan_id"], None, "plan", "planned", expected={"evidence": source.expected_count})
    return result


def _load_plan(path: Path) -> dict[str, Any]:
    """A plan file, without the display-only approval card an agent may have saved from --json output."""
    return {k: v for k, v in json.loads(path.read_text(encoding="utf-8")).items() if k != "approval_card"}


def _account(args: argparse.Namespace, live: dict[str, Any]) -> dict[str, Any]:
    return {"tenant_id": args.tenant_id, "subscription_id": args.subscription_id,
            "resource_group": args.resource_group, **live["names"]()}


def _run_azure(args: argparse.Namespace) -> dict[str, Any]:
    if args.command in ("apply", "retire") and not args.confirm_writes:
        raise ContractError("WRITE_CONFIRMATION_REQUIRED", f"Live {args.command} requires --confirm-writes before any Azure request")
    missing = ["--" + name.replace("_", "-") for name in LIVE_REQUIRED if not getattr(args, name)]
    if missing:
        raise ContractError("AZURE_LIVE_ARGS_REQUIRED", "Missing required live Azure flags: " + ", ".join(missing))
    planned = _load_plan(args.plan_file) if args.command == "apply" else None
    if planned is not None:
        planned_basis = (planned.get("source_binding") or {}).get("visibility_basis", "per-document")
        if planned_basis != args.source_visibility:
            raise ContractError("SOURCE_VISIBILITY_MISMATCH",
                                f"The plan was made with --source-visibility {planned_basis}; apply needs the same value")
    if planned is not None and planned.get("naming_model") is not None and not args.approve_model_calls:
        raise ContractError("MODEL_CALLS_NOT_APPROVED", "This plan names communities; pass --approve-model-calls")
    store, source, live = create_live_store(args)
    state = State(args.state_dir / "operations")
    from grz_adapters.native_adapter import NativeBuildAdapter
    from grz_adapters.native_runner import NativeRunner

    service = BuildService(
        store, state, args.state_dir / "scratch", alias=args.alias,
        native_adapter=NativeBuildAdapter(
            runner=NativeRunner(binary_path=args.native_binary),
            scratch_root=args.state_dir / "native",
        ),
    )
    if args.command == "inspect":
        return service.inspect(source)
    if args.command == "plan":
        planned_now = _live_plan(args, service, store, source, live, state)
        return {**planned_now, "approval_card": approval_card.for_apply(planned_now, _account(args, live))}
    if planned is not None:
        provider = (AzureOpenAIChatNamer.from_plan(planned["naming_model"], args.tenant_id, live["credential"])
                    if planned.get("naming_model") is not None else None)
        descriptor = service.apply(planned, args.plan_id, args.approved_budget_bytes,
                                   resume_after_reconcile=args.resume_after_reconcile,
                                   naming_provider=provider, naming_approved=provider is not None).to_dict()
        if provider is not None:
            # Apply prints only the descriptor so it can be saved and handed to Consume; verify reports usage.
            record = state.generation(descriptor["generation_id"])
            state.save_generation(descriptor["generation_id"], {**record, "naming_usage": provider.usage})
        return descriptor
    if args.command == "reconcile":
        return service.reconcile(_load_plan(args.plan_file))
    if args.command == "verify":
        record = state.generation(args.generation_id)
        descriptor = record["descriptor"]
        counts = service.verify(args.generation_id, descriptor["physical_index"], SourceIdentity(**record["source"]))
        result = {"generation_id": args.generation_id, "counts": counts, "timings_ms": record.get("timings_ms", {})}
        if "naming_usage" in record:
            result["naming_usage"] = record["naming_usage"]
        result["approval_card"] = approval_card.for_publish(args.generation_id, descriptor["physical_index"],
                                                            args.alias, _account(args, live))
        return result
    if args.command == "publish":
        record = state.generation(args.generation_id)
        binding = record.get("source_binding") or {}
        if record.get("alias") != args.alias or binding.get("source_index") != args.source_index or binding.get("vector_field") != args.vector_field:
            raise ContractError("PUBLISH_BINDING_MISMATCH", "Alias, source index and vector field must match the approved plan")
        published = service.publish(args.generation_id, approved=args.approve_cutover).to_dict()
        browse = browse_settings(args, published)
        descriptor = json.loads(Path(browse["env"]["GRZ_DESCRIPTOR"]).read_text(encoding="utf-8"))
        browse["current"] = record_current(descriptor, endpoint=browse["env"]["GRZ_SEARCH_ENDPOINT"],
                                           auth="entra", tenant_id=args.tenant_id)
        return {**published, "browse": browse}
    if args.command == "status":
        return service.status(args.alias)
    if args.command == "generations":
        return list_generations(store, dataset=args.dataset, alias=args.alias, source_index=args.source_index)
    if args.command == "plan-retire":
        retire_plan = plan_retire(store, state, args, args.index)
        return {**retire_plan, "approval_card": approval_card.for_retire(retire_plan, _account(args, live))}
    if args.command == "retire":
        return retire(store, state, args, _load_plan(args.plan_file), args.plan_id)
    raise ContractError("COMMAND_UNSUPPORTED", f"Unsupported Azure command: {args.command}")


def _plan_bound_flags(parser: argparse.ArgumentParser, extras: list[str]) -> list[str]:
    """Plan-only options passed to apply: everything the plan subcommand defines that apply doesn't."""
    commands = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    def options(name: str) -> set[str]:
        return {s for a in commands.choices[name]._actions for s in a.option_strings}
    plan_only = options("plan") - options("apply")
    return sorted({token.split("=", 1)[0] for token in extras if token.split("=", 1)[0] in plan_only})


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = _parser()
    args, extras = parser.parse_known_args(argv)
    if extras and getattr(args, "command", None) == "apply":
        bound = _plan_bound_flags(parser, extras)
        if bound:
            raise ContractError(
                "PLAN_BOUND_FLAG",
                f"{', '.join(bound)} {'is' if len(bound) == 1 else 'are'} bound by plan {args.plan_id}; "
                "apply reads naming and reader settings from the saved plan, so drop them from the apply command")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    try:
        args = _parse(argv)
    except ContractError as exc:
        return emit_error(exc, "--json" in argv, "INPUT_INVALID")
    try:
        if args.command == "doctor":
            from grz_build.doctor import run_doctor

            return emit_doctor(run_doctor(args), args.json, "grz-build")
        fill_defaults(args)
        result = _run_azure(args)
        save_artifacts(args, result)
        emit(result, args.json, lambda r: summarize(args, argv, r) or canonical_json(r))
        return 0
    except (ContractError, ValueError, OSError, KeyError) as exc:
        return emit_error(exc, args.json, "INPUT_INVALID")


if __name__ == "__main__":
    raise SystemExit(main())
