from __future__ import annotations

import argparse
import json
from pathlib import Path

from ekg_core import package_version
from ekg_core.cli import Blocked, add_command, new_parser, parse, report, say
from ekg_core.execution import ApprovalRequired, serialize_events
from ekg_core.models import (
    MODEL_DEPLOYMENT_SKUS, BuildAccessSpec, ModelDeploymentSpec, NetworkSpec, ProvisioningSpec, PublicTestSpec,
    PublicDataSpec, Target,
)
from .backends import AzureSdkBackend, ProvisioningError
from .capacity import CapacityError, capacity_plan, capacity_update, quota_check
from .journal import ProvisioningJournal
from .planner import plan
from .renderers import write_artifacts
from .rbac import RbacError, RbacSpec, rbac_check, rbac_grant, rbac_plan
from .smoke import AzureTransport, SmokeError, SmokeSpec, run_smoke, smoke_plan

PROG = "ekg-provision"
MODEL_DEFAULTS = {"embedding": ("text-embedding-3-small", "1"),
                  "chat": ("gpt-5-mini", "2025-08-07")}
_DEFAULTS = {
    "plan_id": None, "confirm_writes": False, "run_id": None, "output": None, "state_dir": None,
    "smoke_id": None, "smoke_container": None, "smoke_vpn_egress_ip": None,
    "smoke_embedding_deployment": None, "rbac_principal_object_id": None,
    "rbac_principal_type": None, "rbac_container": None, "capacity_deployment": None,
    "capacity": None, "search_identity_name": None, "storage_container": None,
    "operator_object_id": None, "operator_principal_type": "User",
}
# Gated verb -> the review verb whose plan ID it takes.
_GATED = {"apply": "plan", "resume-apply": "plan-resume", "smoke-run": "plan-smoke",
          "rbac-grant": "plan-rbac", "capacity-update": "plan-capacity",
          "connect-apply": "connect", "connect-grant": "connect",
          "cleanup-approve": "plan-cleanup"}
_LIVE = ("inspect", "apply", "verify", "plan-resume", "resume-apply", "smoke-run",
         "rbac-check", "rbac-grant", "quota", "plan-capacity", "capacity-update")
_LIVE_TENANT = ("inspect", "verify", "quota", "plan-capacity", "capacity-update")


def _account() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--subscription-id", help="required for live Azure commands")
    parser.add_argument("--tenant-id", help="required for default/private live inspect and verify")
    parser.add_argument("--resource-group")
    parser.add_argument("--state-dir", help="local provisioning journal folder "
                                            "(default ./.ekg/provision-runs)")
    return parser


def _resources() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False, parents=[_account()])
    parser.add_argument("--location")
    parser.add_argument("--search-name")
    parser.add_argument("--storage-name")
    parser.add_argument("--openai-name")
    parser.add_argument("--content-understanding-name")
    parser.add_argument("--search-sku", default="basic")
    parser.add_argument("--create-resource-group", action="store_true")
    parser.add_argument("--network-vnet-name")
    parser.add_argument("--network-subnet-name")
    parser.add_argument("--network-vnet-cidr")
    parser.add_argument("--network-subnet-cidr")
    parser.add_argument("--public-test", action="store_true",
                        help="opt in to a time-limited synthetic-only public test")
    parser.add_argument("--public-test-mode", choices=("ip_allowlist", "entra_only"),
                        help="explicit public network posture; never inferred from missing IPs")
    parser.add_argument("--public-test-tenant-id")
    parser.add_argument("--public-test-egress-ip", action="append")
    parser.add_argument("--public-test-expires-at")
    parser.add_argument("--synthetic-data-only", action="store_true")
    parser.add_argument("--public-data-entra", action="store_true",
                        help="bounded public-corpus-only Entra setup; not synthetic public-test")
    parser.add_argument("--public-data-only", action="store_true",
                        help="acknowledge genuinely public corpus only, no non-public data")
    parser.add_argument("--public-data-expires-at", help="UTC expiry in the next 72 hours")
    parser.add_argument("--search-identity-name",
                        help="managed identity to create and attach to Search (build access)")
    parser.add_argument("--storage-container", help="private Blob container to create "
                                                    "(build access)")
    parser.add_argument("--operator-object-id",
                        help="your Entra object ID; gets the 4 Build roles (build access)")
    parser.add_argument("--operator-principal-type", choices=("User", "ServicePrincipal"),
                        default="User")
    for role, (model, version) in MODEL_DEFAULTS.items():
        parser.add_argument(f"--{role}-deployment",
                            help=f"create the {role} model deployment with this name")
        parser.add_argument(f"--{role}-model", help=f"{role} model name (default {model})")
        parser.add_argument(f"--{role}-model-version",
                            help=f"{role} model version (default {version})")
        parser.add_argument(f"--{role}-sku", choices=MODEL_DEPLOYMENT_SKUS,
                            help="deployment SKU (default GlobalStandard)")
        parser.add_argument(f"--{role}-capacity", type=int,
                            help="capacity in thousands of tokens per minute (default 50)")
    return parser


def _smoke() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--smoke-id", required=True,
                        help="twelve unique lowercase hexadecimal characters")
    parser.add_argument("--smoke-container", required=True,
                        help="existing approved synthetic-only Blob container")
    parser.add_argument("--smoke-vpn-egress-ip", help="exact single IP bound to the public plan")
    parser.add_argument("--smoke-embedding-deployment",
                        help="existing separately approved embedding deployment, if available")
    return parser


def _rbac() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--rbac-principal-object-id", required=True)
    parser.add_argument("--rbac-principal-type", choices=("User", "ServicePrincipal"),
                        required=True)
    parser.add_argument("--rbac-container", required=True)
    return parser


def _capacity() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--capacity-deployment", required=True,
                        help="existing deployment name")
    parser.add_argument("--capacity", type=int, required=True,
                        help="desired thousands of tokens per minute")
    return parser


def _connect_arguments() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False, parents=[_account()])
    for kind in ("search", "storage", "openai"):
        parser.add_argument(f"--{kind}-name")
    for kind in ("search", "storage", "openai", "search-identity"):
        parser.add_argument(f"--{kind}-resource-id",
                            help=f"exact ARM ID of the existing {kind} resource")
    parser.add_argument("--storage-container", help="existing private Blob container")
    parser.add_argument("--embedding-deployment")
    parser.add_argument("--chat-deployment")
    parser.add_argument("--embedding-dimensions", type=int,
                        help="embedding dimensions when the model is not recognized")
    parser.add_argument("--documents", type=int,
                        help="corpus document count for the extraction estimate")
    return parser


def _gate(parser: argparse.ArgumentParser, what: str, *, writes: bool = True) -> None:
    parser.add_argument("--plan-id", help=f"the exact {what} plan ID the user approved")
    if writes:
        parser.add_argument("--confirm-writes", action="store_true",
                            help="confirm the Azure writes of the approved plan")


def _run_id(parser: argparse.ArgumentParser, text: str) -> None:
    parser.add_argument("--run-id", required=True, help=text)


def _build_parser():
    parser, commands = new_parser(PROG, "Plan, provision and connect EKG Azure resources.",
                                  package_version())
    resources, smoke, rbac, capacity = _resources(), _smoke(), _rbac(), _capacity()
    connect = _connect_arguments()
    from ekg_core import doctor
    doctor.add_arguments(add_command(
        commands, "doctor", "Check this operator environment (read-only, no Azure writes)."),
        provision=True)
    for name, text in (("plan", "Review the provisioning plan and its plan ID (offline)."),
                       ("render", "Write Bicep parameters and Portal guidance (offline).")):
        add_command(commands, name, text, [resources]).add_argument(
            "--output", help="folder for Bicep parameters and Portal guidance")
    add_command(commands, "inspect", "Inspect the live resources (read-only).", [resources])
    add_command(commands, "verify", "Verify the provisioned resources (read-only).", [resources])
    _gate(add_command(commands, "apply", "Apply the approved bounded public plan.", [resources]),
          "provisioning")
    _run_id(add_command(commands, "plan-resume", "Review resuming an interrupted run.",
                        [resources]), "the run to resume")
    resume = add_command(commands, "resume-apply", "Apply the approved resume plan.", [resources])
    _run_id(resume, "the run to resume")
    _gate(resume, "resume")
    for name, text in (("plan-cleanup", "Review cleanup of a run's resources (offline)."),
                       ("cleanup-approve", "Record approval of a cleanup plan (offline).")):
        sub = add_command(commands, name, text)
        sub.add_argument("--state-dir", help="local provisioning journal folder")
        _run_id(sub, "the run to clean up")
    _gate(commands.choices["cleanup-approve"], "cleanup", writes=False)
    add_command(commands, "plan-smoke", "Review the synthetic smoke test.", [resources, smoke])
    _gate(add_command(commands, "smoke-run", "Run the approved smoke test.",
                      [resources, smoke]), "smoke")
    add_command(commands, "plan-rbac", "Review the role assignments.", [resources, rbac])
    add_command(commands, "rbac-check", "Check the role assignments (read-only).",
                [resources, rbac])
    _gate(add_command(commands, "rbac-grant", "Grant the approved role assignments.",
                      [resources, rbac]), "RBAC")
    add_command(commands, "quota", "Check model quota (read-only).", [resources])
    add_command(commands, "plan-capacity", "Review a model capacity change.",
                [resources, capacity])
    _gate(add_command(commands, "capacity-update", "Apply the approved capacity change.",
                      [resources, capacity]), "capacity")
    telemetry = add_command(commands, "telemetry", "Summarize a run's timings (offline).")
    telemetry.add_argument("--state-dir", help="local provisioning journal folder")
    _run_id(telemetry, "the run to summarize")
    add_command(commands, "connect", "Discover and validate existing resources (read-only).",
                [connect])
    _gate(add_command(commands, "connect-apply",
                      "Apply the approved connect setup plan (container, models, roles).",
                      [connect]), "connect setup")
    _gate(add_command(commands, "connect-grant", "Alias of connect-apply.", [connect]),
          "connect setup")
    return parser


def _journal(args) -> ProvisioningJournal:
    return ProvisioningJournal(args.state_dir or Path.cwd() / ".ekg" / "provision-runs")


def _telemetry(args) -> dict:
    from ekg_core.telemetry import summarize_phases, valid_event
    try:
        record = _journal(args).read(args.run_id)
    except json.JSONDecodeError as error:
        raise Blocked("INVALID_INPUT", str(error)) from error
    events = [event for event in record.get("telemetry") or [] if valid_event(event)]
    return {
        "phase": "provision.telemetry", "run_id": args.run_id,
        "plan_id": record.get("plan_id"), "completed": record.get("completed"),
        "evidence": {"origin": "local_provisioning_journal"},
        "phases": summarize_phases(events),
        "uncertainty": [] if events else ["Run predates telemetry events."],
    }


def _usage(message: str) -> Blocked:
    return Blocked("USAGE", message)


def _validate_command_args(args) -> tuple[tuple[str | None, ...], list[ModelDeploymentSpec]]:
    for flag in ("resource_group", "location", "search_name", "storage_name", "openai_name"):
        if getattr(args, flag) is None:
            raise _usage(f"--{flag.replace('_', '-')} is required")
    network_args = (
        args.network_vnet_name, args.network_subnet_name,
        args.network_vnet_cidr, args.network_subnet_cidr,
    )
    if any(value is not None for value in network_args) and not all(
        value is not None for value in network_args
    ):
        raise _usage("network configuration requires --network-vnet-name, "
                     "--network-subnet-name, --network-vnet-cidr and --network-subnet-cidr "
                     "together")
    if args.public_data_entra:
        if (args.public_test or args.public_test_mode or args.public_test_tenant_id
                or args.public_test_egress_ip or args.public_test_expires_at
                or args.synthetic_data_only):
            raise _usage("--public-data-entra rejects all public-test/synthetic settings")
        if not (args.tenant_id and args.public_data_only and args.public_data_expires_at):
            raise _usage("--public-data-entra requires --tenant-id, --public-data-only and "
                         "--public-data-expires-at")
        if any(value is not None for value in network_args):
            raise _usage("--public-data-entra cannot use private networking")
    elif args.public_data_only or args.public_data_expires_at:
        raise _usage("public-data settings require --public-data-entra")
    if args.public_test:
        if not (args.public_test_mode and args.public_test_tenant_id
                and args.public_test_expires_at and args.synthetic_data_only):
            raise _usage("--public-test requires --public-test-mode, --public-test-tenant-id, "
                         "--public-test-expires-at and --synthetic-data-only")
        if args.public_test_mode == "ip_allowlist" and not args.public_test_egress_ip:
            raise _usage("ip_allowlist requires --public-test-egress-ip")
        if args.public_test_mode == "entra_only" and args.public_test_egress_ip:
            raise _usage("entra_only rejects --public-test-egress-ip")
        if any(value is not None for value in network_args):
            raise _usage("--public-test cannot be combined with private networking")
        if args.tenant_id and args.tenant_id != args.public_test_tenant_id:
            raise _usage("--tenant-id must match --public-test-tenant-id")
    elif (args.public_test_mode or args.public_test_tenant_id or args.public_test_egress_ip
          or args.public_test_expires_at or args.synthetic_data_only):
        raise _usage("public-test settings require --public-test")
    if args.command in ("plan-resume", "resume-apply") and not args.public_test:
        raise _usage("resume requires --public-test")
    if args.command in ("plan-smoke", "smoke-run"):
        if not args.public_test:
            raise _usage("smoke requires --public-test")
        if args.public_test_mode == "ip_allowlist" and not args.smoke_vpn_egress_ip:
            raise _usage("ip_allowlist smoke requires --smoke-vpn-egress-ip")
        if args.public_test_mode == "entra_only" and args.smoke_vpn_egress_ip:
            raise _usage("entra_only smoke rejects --smoke-vpn-egress-ip")
    if args.command in ("plan-rbac", "rbac-check", "rbac-grant") and not args.public_test:
        raise _usage("RBAC requires --public-test")
    deployments = []
    for role, (model, version) in MODEL_DEFAULTS.items():
        name = getattr(args, f"{role}_deployment")
        options = [getattr(args, f"{role}_{key}") for key in ("model", "model_version", "sku",
                                                               "capacity")]
        if name is None:
            if any(value is not None for value in options):
                raise _usage(f"--{role}-* settings require --{role}-deployment")
            continue
        try:
            deployments.append(ModelDeploymentSpec(
                role=role, name=name, model=options[0] or model,
                version=options[1] or (version if options[0] in (None, model) else ""),
                sku=options[2] or "GlobalStandard",
                capacity=50 if options[3] is None else options[3],
            ))
        except ValueError as error:
            raise _usage(f"{role} deployment: {error}") from error
    if args.command == "quota" and not deployments:
        raise _usage("quota requires --embedding-deployment and/or --chat-deployment")
    access_args = (args.search_identity_name, args.storage_container, args.operator_object_id)
    if any(access_args):
        if not all(access_args):
            raise _usage("build access needs --search-identity-name, --storage-container and "
                         "--operator-object-id together")
        if not (args.public_test or args.public_data_entra):
            raise _usage("build access requires --public-test or --public-data-entra")
        if {deployment.role for deployment in deployments} != {"embedding", "chat"}:
            raise _usage("build access needs --embedding-deployment and --chat-deployment, "
                         "so one plan finishes setup")
    return network_args, deployments


def _spec(args, network_args, deployments) -> ProvisioningSpec:
    return ProvisioningSpec(
        target=Target(
            subscription_id=args.subscription_id,
            resource_group=args.resource_group,
            location=args.location,
        ),
        search_name=args.search_name,
        storage_name=args.storage_name,
        openai_name=args.openai_name,
        content_understanding_name=args.content_understanding_name,
        search_sku=args.search_sku,
        create_resource_group=args.create_resource_group,
        network=(NetworkSpec(*network_args) if all(
            value is not None for value in network_args
        ) else None),
        public_test=(PublicTestSpec(
            tenant_id=args.public_test_tenant_id,
            egress_ips=tuple(args.public_test_egress_ip or ()),
            expires_at=args.public_test_expires_at,
            synthetic_data_only=args.synthetic_data_only,
            mode=args.public_test_mode,
        ) if args.public_test else None),
        public_data=(PublicDataSpec(
            tenant_id=args.tenant_id, expires_at=args.public_data_expires_at,
            public_data_only=args.public_data_only,
        ) if args.public_data_entra else None),
        model_deployments=tuple(deployments),
        build_access=(BuildAccessSpec(
            search_identity_name=args.search_identity_name,
            storage_container=args.storage_container,
            operator_object_id=args.operator_object_id,
            operator_principal_type=args.operator_principal_type or "User",
        ) if args.search_identity_name else None),
    )


def _run(args) -> dict:
    if args.command in _GATED and not (
        args.plan_id and (args.confirm_writes or args.command == "cleanup-approve")
    ):
        needs = "--plan-id" if args.command == "cleanup-approve" else "--plan-id and " \
                                                                     "--confirm-writes"
        raise Blocked("APPROVAL_REQUIRED", f"{args.command} requires {needs}",
                      plan_verb=_GATED[args.command])
    if args.command in ("connect", "connect-apply", "connect-grant"):
        return _connect(args)
    if args.command == "telemetry":
        return _telemetry(args)
    if args.command == "plan-cleanup":
        return _journal(args).cleanup_plan(args.run_id)
    if args.command == "cleanup-approve":
        return _journal(args).approve_cleanup(args.run_id, args.plan_id)
    spec = _spec(args, *_validate_command_args(args))
    if spec.public_data is not None:
        plan(spec, require_active=args.command not in ("inspect", "verify"))
    if args.command in _LIVE and not args.subscription_id:
        raise _usage("--subscription-id is required for live Azure commands")
    tenant = args.tenant_id or args.public_test_tenant_id
    if args.command in _LIVE_TENANT and not tenant:
        raise _usage("--tenant-id is required for live Azure commands")
    if args.command in ("quota", "plan-capacity", "capacity-update"):
        return _cmd_capacity(args, spec, tenant)
    if args.command in ("plan-rbac", "rbac-check", "rbac-grant"):
        return _cmd_rbac(args, spec)
    if args.command in ("plan-smoke", "smoke-run"):
        return _cmd_smoke(args, spec)
    if args.command in ("plan", "render"):
        return _cmd_plan(args, spec)
    return _cmd_backend(args, spec)


def _cmd_capacity(args, spec: ProvisioningSpec, tenant: str | None) -> dict:
    if args.command == "quota":
        return quota_check(spec, tenant_id=tenant)
    if args.command == "plan-capacity":
        review = capacity_plan(spec, args.capacity_deployment, args.capacity, tenant_id=tenant)
        if review["change"] != "none" and not review["blockers"]:
            current = review["current"]
            review["approval_card"] = _simple_card(
                spec, tenant, "change a model deployment's capacity", review["plan_id"],
                [f"Change deployment {review['deployment']} ({current['sku']}) from "
                 f"{current['capacity_k_tpm']}K to {review['desired_capacity_k_tpm']}K "
                 "tokens per minute"])
        return review
    return capacity_update(spec, args.capacity_deployment, args.capacity, tenant_id=tenant,
                           approved_plan_id=args.plan_id, confirmed=args.confirm_writes)


def _cmd_rbac(args, spec: ProvisioningSpec) -> dict:
    rbac = RbacSpec(args.rbac_principal_object_id, args.rbac_principal_type, args.rbac_container)
    review = rbac_plan(spec, rbac)
    if args.command == "plan-rbac":
        review["approval_card"] = _simple_card(
            spec, spec.public_test.tenant_id if spec.public_test else args.tenant_id,
            "grant EKG's roles", review["plan_id"],
            [f"Grant {item['principal_type']} {item['principal_object_id']} "
             f"{item['role']} on {item['scope'].rsplit('/', 1)[-1]}"
             for item in review["operations"]])
        return review
    if args.command == "rbac-check":
        return rbac_check(spec, rbac)
    if args.plan_id != review["plan_id"]:
        raise ApprovalRequired(f"explicit approval of RBAC plan {review['plan_id']} is required")
    return rbac_grant(spec, rbac, approved_plan_id=args.plan_id, confirmed=args.confirm_writes)


def _cmd_smoke(args, spec: ProvisioningSpec) -> dict:
    smoke = SmokeSpec(args.smoke_id, args.smoke_container, args.smoke_vpn_egress_ip,
                      args.smoke_embedding_deployment)
    review = smoke_plan(spec, smoke)
    if args.command == "plan-smoke":
        return review
    if args.plan_id != review["plan_id"]:
        raise ApprovalRequired(f"explicit approval of smoke plan {review['plan_id']} is required")
    backend = AzureSdkBackend(journal_root=args.state_dir,
                              expected_tenant_id=args.tenant_id or args.public_test_tenant_id)
    inspection = backend.inspect(spec)
    return run_smoke(spec, smoke, approved_smoke_plan_id=args.plan_id,
                     confirmed=args.confirm_writes,
                     transport=AzureTransport(backend._sdk_credential), inspection=inspection,
                     journal_dir=args.state_dir or Path.cwd() / ".ekg" / "provision-runs")


def _simple_card(spec: ProvisioningSpec, tenant: str | None, what: str, plan_id: str,
                 changes: list[str]) -> str:
    """Card for a small change to existing resources: minutes, and no charge of its own."""
    from ekg_core import approval
    names = approval.azure_context(tenant, spec.target.subscription_id)
    return approval.card(
        what=what, plan_id=plan_id, changes=changes, time=approval.time_text(1, 2),
        cost=approval.cost_text(0.0), tenant_id=tenant, tenant_name=names.get("tenant_name"),
        subscription=names.get("subscription") or spec.target.subscription_id,
        resource_group=spec.target.resource_group)


def _provision_card(spec: ProvisioningSpec, plan_id: str, writes: list[str]) -> str:
    from ekg_core import approval
    from ekg_core.pricing import search_usd_per_day
    tenant = spec.public_endpoint.tenant_id if spec.public_endpoint else None
    names = approval.azure_context(tenant, spec.target.subscription_id)
    # The recorded one-plan setup took about 12 minutes; Search creation dominates.
    return approval.card(
        what="set up EKG's Azure resources", plan_id=plan_id, changes=writes,
        time=approval.time_text(10, 20),
        cost=approval.cost_text(0.0, search_usd_per_day(spec.search_sku)),
        tenant_id=tenant, tenant_name=names.get("tenant_name"),
        subscription=names.get("subscription") or spec.target.subscription_id,
        resource_group=spec.target.resource_group, new_group=spec.create_resource_group,
        notes=((f"PUBLIC DATA ONLY: no non-public data. Entra-only public endpoints, "
                f"all public IPs; no trusted-service bypass. Expiry: "
                f"{spec.public_data.expires_at} (manual cleanup, not automatic shutdown). "
                "Upload, Build and publish each require separate approval.",)
               if spec.public_data else ()))


def _cmd_plan(args, spec: ProvisioningSpec) -> dict:
    from .access import plain_writes
    reviewed = plan(spec)
    payload = reviewed.to_dict()
    writes = plain_writes(spec, reviewed.operations)
    payload["writes"] = writes
    if spec.public_data is not None:
        from .journal import journal_spec
        payload["spec"] = journal_spec(spec)
    if args.command == "plan":
        payload["summary"] = (
            (f"Here's what I'll create in tenant {spec.public_endpoint.tenant_id}, subscription "
             f"{spec.target.subscription_id}" if spec.public_endpoint else
             f"Planned resources in subscription {spec.target.subscription_id}")
            + f" ({len(writes)} changes):\n" + "\n".join(f"- {line}" for line in writes[:3])
            + (f"\n- ...and {len(writes) - 3} more (--json lists every change)"
               if len(writes) > 3 else ""))
        payload["next_step"] = (
            "Show every change to the user; on approval run `ekg-provision apply` with the "
            f"same flags plus --plan-id {reviewed.plan_id} --confirm-writes."
            if spec.public_endpoint else
            "Deploy with the rendered Bicep (`ekg-provision render`) or use --public-test.")
        if spec.public_endpoint and not reviewed.blocked_by:
            payload["approval_card"] = _provision_card(spec, reviewed.plan_id, writes)
    if args.output:
        parameters, portal = write_artifacts(spec, args.output)
        payload["artifacts"] = {"bicep_parameters": str(parameters), "portal_guide": str(portal)}
    return payload


def _cmd_backend(args, spec: ProvisioningSpec) -> dict:
    backend = AzureSdkBackend(journal_root=args.state_dir,
                              expected_tenant_id=args.tenant_id or args.public_test_tenant_id)
    if args.command == "inspect":
        return backend.inspect(spec)
    if args.command == "verify":
        return backend.verify(spec)
    if args.command == "plan-resume":
        return backend.resume_plan(spec, args.run_id)
    result = (backend.resume_apply(spec, args.run_id, approved_plan_id=args.plan_id,
                                   confirmed_public_test=args.confirm_writes)
              if args.command == "resume-apply" else
              backend.apply(spec, approved_plan_id=args.plan_id,
                            confirmed_public_test=args.confirm_writes if spec.public_test else False,
                            confirmed_public_data=args.confirm_writes if spec.public_data else False))
    payload = {"plan_id": args.plan_id, "completed": result.completed,
               "events": serialize_events(result.events), "run_id": backend.last_run_id,
               "journal_path": (str(backend.journal.path(backend.last_run_id))
                                if backend.last_run_id else None)}
    if not result.completed:
        raise Blocked("PUBLIC_DATA_STOPPED" if spec.public_data else "PROVISION_INCOMPLETE",
                      "provisioning did not complete", result=payload)
    return payload


def _connect_summary(payload: dict) -> dict:
    checks = payload.get("checks") or []
    passed = sum(check.get("status") == "ok" for check in checks)
    lines = [f"Connect: {payload['status']} (tenant {payload['tenant_id']}); "
             f"{passed}/{len(checks)} check(s) passed."]
    setup = payload.get("setup_plan")
    if payload.get("candidates"):
        lines.append("Missing inputs: " + ", ".join(sorted(payload["candidates"])))
    if payload.get("grant"):
        lines.append(f"Setup: {payload['grant']['status']}")
    if payload["status"] == "ready" and payload.get("build_binding"):
        step = ("Pass build_binding.build_args (see --json) to `ekg-build plan`.")
    elif setup and payload["status"] != "blocked":
        writes = setup["writes"]
        lines.append(f"Here's what I'll set up ({len(writes)} change(s)): "
                     + "; ".join(writes[:3])
                     + (f"; ...and {len(writes) - 3} more (--json lists every change)"
                        if len(writes) > 3 else ""))
        step = ("Show the approval card to the user and get explicit approval, then run "
                "`ekg-provision connect-apply` with the same flags plus --plan-id "
                f"{setup['plan_id']} --confirm-writes.")
        if payload.get("approval_card"):
            return {"summary": "\n".join(lines), "next_step": step,
                    "approval_card": payload["approval_card"]}
    elif payload["status"] == "unverified" and any(
        row.get("permission_coverage") is not None and row["status"] != "assigned"
        for row in payload.get("roles", [])
    ):
        step = ("Ask the account owner to verify OpenAI access for you and the Search identity "
                "(role-definition permissions, groups, active PIM, conditions and denies), "
                "then run `ekg-provision connect` again. No missing role or grant is inferred.")
    else:
        step = "Supply the missing inputs, then run `ekg-provision connect` again."
    return {"summary": "\n".join(lines), "next_step": step}


def _connect(args) -> dict:
    from .connect import ConnectSpec, connect, connect_apply, connection_spec, public_payload

    if not (args.tenant_id and args.subscription_id):
        raise _usage("connect requires --tenant-id and --subscription-id")
    for kind in ("search", "storage", "openai"):
        if getattr(args, f"{kind}_name") and getattr(args, f"{kind}_resource_id"):
            raise _usage(f"pass --{kind}-name or --{kind}-resource-id, not both")
    spec = ConnectSpec(
        tenant_id=args.tenant_id, subscription_id=args.subscription_id,
        resource_group=args.resource_group,
        search=args.search_resource_id or args.search_name,
        storage=args.storage_resource_id or args.storage_name,
        openai=args.openai_resource_id or args.openai_name,
        storage_container=args.storage_container,
        embedding_deployment=args.embedding_deployment,
        chat_deployment=args.chat_deployment,
        search_identity_resource_id=args.search_identity_resource_id,
        embedding_dimensions=args.embedding_dimensions, documents=args.documents,
    )
    if args.command in ("connect-apply", "connect-grant"):
        payload = connect_apply(spec, approved_plan_id=args.plan_id,
                                confirmed=args.confirm_writes)
    else:
        raw = connect(spec)
        payload = public_payload(raw)
        provision_spec = connection_spec(raw)
        if provision_spec is not None:
            from ekg_core.models import stable_id
            journal = _journal(args)
            run_id = journal.record_connection(
                provision_spec, plan(provision_spec),
                stable_id("connect-binding", payload["build_binding"]), payload)
            payload.update(run_id=run_id, journal_path=str(journal.path(run_id)))
    if payload["status"] == "blocked":
        raise Blocked("CONNECT_BLOCKED", f"failed checks: {', '.join(payload['blocked_by'])}",
                      result=payload)
    setup = payload.get("setup_plan")
    if args.command == "connect" and setup and setup.get("writes") and payload["status"] != "ready":
        payload["approval_card"] = _connect_card(payload, setup, args.resource_group)
    return payload


def _connect_card(payload: dict, setup: dict, resource_group: str | None) -> str:
    from ekg_core import approval
    if not resource_group:
        for value in (payload.get("resources") or {}).values():
            parts = str(value or "").split("/")
            lowered = [part.lower() for part in parts]
            if "resourcegroups" in lowered and lowered.index("resourcegroups") + 1 < len(parts):
                resource_group = parts[lowered.index("resourcegroups") + 1]
                break
    names = approval.azure_context(payload.get("tenant_id"), payload.get("subscription_id"))
    return approval.card(
        what="finish setup of your existing EKG resources", plan_id=setup["plan_id"],
        changes=setup["writes"], time=approval.time_text(1, 5), cost=approval.cost_text(0.0),
        tenant_id=payload.get("tenant_id"), tenant_name=names.get("tenant_name"),
        subscription=names.get("subscription") or payload.get("subscription_id"),
        resource_group=resource_group)


def _classify(error: Exception, command: str) -> Blocked:
    from ekg_core.az_identity import IdentityError
    from .connect import ConnectError
    text = str(error)
    if isinstance(error, ApprovalRequired):
        return Blocked("APPROVAL_REQUIRED", text, plan_verb=_GATED.get(command, "plan"))
    if isinstance(error, IdentityError):
        return Blocked("AZ_SIGNIN", text)
    for kind, code in ((ConnectError, "CONNECT_BLOCKED"), (SmokeError, "SMOKE_FAILED"),
                       (CapacityError, "CAPACITY_BLOCKED"), (RbacError, "RBAC_BLOCKED"),
                       (ProvisioningError, "PROVISION_FAILED")):
        if isinstance(error, kind):
            return Blocked(code, text)
    if isinstance(error, OSError):
        return Blocked("LOCAL_IO", text)
    if isinstance(error, (ValueError, KeyError)):
        return Blocked("INVALID_INPUT", text)
    return Blocked("PROVISION_INCOMPLETE" if command in _GATED else "AZURE_ERROR", text)


def main(argv: list[str] | None = None) -> None:
    args = parse(_build_parser(), argv, _DEFAULTS)
    if args.command == "doctor":
        from ekg_core import doctor
        doctor.run(PROG, args)
        return
    try:
        result = _run(args)
    except Blocked as blocked:
        report(blocked, prog=PROG, command=args.command)
    except (RuntimeError, ValueError, OSError, KeyError) as error:
        if getattr(args, "public_data_entra", False) and isinstance(error, ProvisioningError):
            report(Blocked("PUBLIC_DATA_STOPPED", str(error)), prog=PROG, command=args.command)
        report(_classify(error, args.command), prog=PROG, command=args.command)
    if not args.json:
        from ekg_core.telemetry import summary_text
        if args.command == "telemetry":
            result = {"summary": summary_text(result)}
        elif args.command in ("connect", "connect-apply", "connect-grant"):
            result = _connect_summary(result)
    say(result, args, prog=PROG)
