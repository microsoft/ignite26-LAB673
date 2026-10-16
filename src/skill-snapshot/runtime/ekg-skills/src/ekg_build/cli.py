from __future__ import annotations
import argparse
import json
import shlex
import sys
from dataclasses import asdict
from pathlib import Path
from ekg_core import grounding, package_version
from ekg_core.cli import Blocked, add_command, new_parser, parse, report, say
from ekg_core.models import (
    BuildSpec, KnowledgeSourceKind, OntologyMode, RequestedOutcome,
    SourceKind, SourceLocator, SourceManifest, Target, manifest_item_from_json,
)
from .adapters import AzureDataPlane
from .deployment import descriptor, publish
from .executor import BuildExecutor
from .managed_pipeline import SEARCH_API_VERSION, search_api_version
from .planner import plan
from .preflight import preflight
from .status import read_build_status

PROG = "ekg-build"
DEFAULT_SAMPLE = 50
_DEFAULTS = {
    "reader": [], "descriptor": [], "generation": [], "plan_id": None, "confirm_writes": False,
    "wait": False, "output": None, "chat_capacity": None, "trial_report": None, "upload_concurrency": 16, "consume_log": None, "run_id": None,
    "build_journal": None, "tenant_id": None, "search_endpoint": None, "sample": None,
    "storage_endpoint": None, "search_resource_id": None, "storage_resource_id": None,
}
# The review verb each gated verb's approval comes from.
_PLAN_VERB = {"apply": "plan", "retire": "plan-retire", "update": "plan-update"}


def _spec_arguments() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--corpus", help="legacy local corpus path; cannot be combined with "
                        "any --source-* option (use --source-kind, --source-reference and "
                        "--source-manifest for explicit sources)")
    parser.add_argument("--source-kind", choices=[kind.value for kind in SourceKind])
    parser.add_argument("--source-reference")
    parser.add_argument("--source-resource-id")
    parser.add_argument("--source-container")
    parser.add_argument("--source-prefix")
    parser.add_argument("--source-library-id")
    parser.add_argument("--requested-outcome", choices=[item.value for item in RequestedOutcome])
    parser.add_argument("--knowledge-source-kind",
                        choices=[item.value for item in KnowledgeSourceKind])
    parser.add_argument("--ontology", choices=[mode.value for mode in OntologyMode],
                        default="none")
    parser.add_argument("--ontology-path")
    parser.add_argument("--graph", action="store_true")
    parser.add_argument("--agentic", action="store_true")
    parser.add_argument("--search-endpoint")
    parser.add_argument("--storage-endpoint")
    parser.add_argument("--openai-endpoint")
    parser.add_argument("--search-resource-id")
    parser.add_argument("--storage-resource-id")
    parser.add_argument("--openai-resource-id")
    parser.add_argument("--embedding-deployment")
    parser.add_argument("--embedding-model")
    parser.add_argument("--embedding-dimensions", type=int)
    parser.add_argument("--chat-deployment")
    parser.add_argument("--chat-model")
    parser.add_argument("--search-identity-resource-id")
    parser.add_argument("--location")
    parser.add_argument("--tenant-id")
    parser.add_argument("--extraction-parallelism", type=int,
                        help="concurrent managed graph-extraction model calls (1..256)")
    parser.add_argument("--extraction-reasoning-effort",
                        choices=("minimal", "low", "medium", "high"),
                        help="reasoning effort for managed graph extraction (default low)")
    parser.add_argument("--ingestion-interval",
                        help="Knowledge Source indexer schedule, PT5M..P1D (default: the "
                             "service's P1D); set PT5M so a build longer than one 2-hour "
                             "indexer run continues unattended")
    parser.add_argument("--grounding-index",
                        help="name of an existing Search index with an edgeList graph profile "
                             "to ground extraction against; validated read-only, never created")
    parser.add_argument("--search-sku")
    parser.add_argument("--build-journal")
    parser.add_argument("--subscription-id")
    parser.add_argument("--resource-group")
    parser.add_argument("--storage-container", default="source-documents")
    parser.add_argument("--source-manifest")
    parser.add_argument("--sample", type=int, nargs="?", const=DEFAULT_SAMPLE, default=None,
                        metavar="N",
                        help=f"trial build: stage only N documents of --source-manifest "
                             f"(default {DEFAULT_SAMPLE}), chosen deterministically, under a "
                             "trial prefix; never publishable")
    parser.add_argument("--run-id")
    parser.add_argument("--descriptor", action="append", default=[],
                        help="the published descriptor: plan/apply carry its index readers "
                             "forward; publish proposes cleanup against it; plan-update/update "
                             "update it in place")
    parser.add_argument("--reader", action="append", default=[],
                        help="<object-id>:User|ServicePrincipal|Group to grant Search Index "
                             "Data Reader on the new generation's indexes (repeatable); "
                             "index-scoped readers of --descriptor carry forward")
    return parser


def _generation_arguments() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--search-endpoint", required=True)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--descriptor", action="append", default=[],
                        help="serving descriptor whose generation is protected (repeatable)")
    parser.add_argument("--storage-endpoint")
    parser.add_argument("--storage-resource-id")
    parser.add_argument("--search-resource-id")
    return parser


def _gate(parser: argparse.ArgumentParser, what: str) -> None:
    parser.add_argument("--plan-id", help=f"the approved {what} plan ID")
    parser.add_argument("--confirm-writes", action="store_true",
                        help="confirm the Azure writes of the approved plan")


def _parser():
    parser, commands = new_parser(PROG, "Plan, apply, publish and maintain an EKG build.",
                                  package_version())
    spec = _spec_arguments()
    generation = _generation_arguments()
    from ekg_core import doctor
    doctor.add_arguments(add_command(
        commands, "doctor", "Check this operator environment (read-only, no Azure writes)."),
        build=True)
    capacity = argparse.ArgumentParser(add_help=False)
    capacity.add_argument(
        "--chat-capacity", type=int,
        help="chat deployment capacity in thousands of TPM, for estimates only "
             "(not part of the plan ID)")
    capacity.add_argument(
        "--trial-report",
        help="a GO `ekg-build trial-report --json` result for this corpus; its measured time "
             "and cost replace the plan-time estimate (not part of the plan ID)")
    capacity.add_argument(
        "--upload-concurrency", type=int, default=16,
        help="parallel blob uploads while staging the corpus (default 16; not part of the "
             "plan ID)")
    add_command(commands, "plan", "Review the build plan and its plan ID (read-only).",
                [spec, capacity])
    for name, text in (("preflight", "Check the build inputs (read-only)."),
                       ("descriptor", "Show the descriptor this build would publish."),
                       ("inspect", "Inspect the live target (read-only)."),
                       ("verify", "Verify the built indexes (read-only)."),
                       ("reconcile", "Settle an unknown-outcome build from the journal."),
                       ("progress", "Show managed synchronization progress (read-only)."),
                       ("plan-update", "Review an in-place update of a published build.")):
        add_command(commands, name, text, [spec])
    # Same --chat-capacity as plan and apply, so a plan's flags can be reused verbatim.
    chat = argparse.ArgumentParser(add_help=False)
    chat.add_argument("--chat-capacity", type=int,
                      help="chat deployment capacity in thousands of TPM; accepted for parity "
                           "with plan and apply (the report uses measured rates)")
    add_command(commands, "attribution", "Report model usage attribution (read-only).",
                [spec, chat])
    add_command(commands, "trial-report", "Report a verified trial build: populated and "
                                          "zero-hit classes and relationships, the full-build "
                                          "extrapolation and go/no-go (read-only).",
                [spec, chat])
    add_command(commands, "inventory", "Inventory the source into a manifest (read-only).",
                [spec]).add_argument("--output", help="write the manifest to this new file")
    apply = add_command(commands, "apply", "Apply the approved build plan.", [spec, capacity])
    _gate(apply, "build")
    apply.add_argument("--wait", action="store_true",
                       help="poll managed synchronization for up to five minutes and verify")
    publish_cmd = add_command(commands, "publish", "Publish the verified build's descriptor.", [spec])
    publish_cmd.add_argument(
        "--output", help="write the descriptor to this file and update the current pointer; "
                         "omit to write <EKG home>/descriptors/<name>.json")
    publish_cmd.add_argument(
        "--keep-current", action="store_true",
        help="leave the current pointer on the previously published descriptor, for example "
             "to publish a second graph side by side")
    _gate(add_command(commands, "update", "Apply the approved in-place update plan.", [spec]),
          "update")
    status = add_command(commands, "status", "Read one run from the build journal.")
    status.add_argument("--build-journal", required=True)
    status.add_argument("--run-id", required=True)
    telemetry = add_command(commands, "telemetry", "Summarize build and consume timings.")
    telemetry.add_argument("--build-journal")
    telemetry.add_argument("--run-id")
    telemetry.add_argument("--consume-log", help="Consume JSONL log to summarize (read-only)")
    add_command(commands, "generations", "List EKG generations and what protects them.",
                [generation])
    add_command(commands, "plan-retire", "Review retiring generations (read-only).",
                [generation]).add_argument(
        "--generation", action="append", required=True,
        help="16-hex generation to delete (repeatable)")
    retire = add_command(commands, "retire", "Apply the approved retire plan.", [generation])
    retire.add_argument("--generation", action="append", required=True,
                        help="16-hex generation to delete (repeatable)")
    _gate(retire, "retire")
    return parser


def _staged_storage(args):
    if not args.storage_endpoint or not args.storage_resource_id:
        return None
    from . import generations as gen
    from .blob_sources import AzureBlobReader
    return gen.StagedStorage(AzureBlobReader(tenant_id=args.tenant_id),
                             args.storage_endpoint.rstrip("/"), args.storage_resource_id)


def _index_grants(args, adapter):
    if not args.search_resource_id or not args.tenant_id:
        return None
    from . import generations as gen
    return gen.IndexGrants(adapter, args.search_resource_id, args.tenant_id)


def _check_tenant(adapter, tenant_id: str) -> None:
    from ekg_core import az_identity
    token = adapter.credential.get_token("https://search.azure.com/.default").token
    if not az_identity.token_in_tenant(token, tenant_id):
        raise Blocked("TENANT_MISMATCH", "the signed-in Search credential is not in --tenant-id")


def _telemetry_summary(report: dict) -> dict:
    from ekg_core.telemetry import summary_text
    return {"summary": summary_text(report)}


def _handle_telemetry(args) -> dict:
    if not args.build_journal and not args.consume_log:
        raise Blocked("USAGE", "telemetry requires --build-journal and/or --consume-log")
    from .telemetry import build_telemetry
    try:
        return build_telemetry(args.build_journal, args.run_id, consume_log=args.consume_log)
    except ValueError as error:
        raise Blocked("INVALID_INPUT", str(error)) from error


def _handle_generations(args) -> dict:
    from ekg_core import az_identity
    from . import generations as gen
    adapter = AzureDataPlane(search_endpoint=args.search_endpoint,
                             credential=az_identity.cli_credential(args.tenant_id),
                             search_api_version=SEARCH_API_VERSION)
    _check_tenant(adapter, args.tenant_id)
    scope = {"descriptors": tuple(args.descriptor), "search_endpoint": args.search_endpoint}
    storage = _staged_storage(args)
    grants = _index_grants(args, adapter)
    if args.command == "generations":
        return gen.list_generations(adapter, scope["descriptors"])
    if args.command == "plan-retire":
        review = gen.retire_plan(adapter, tuple(args.generation), **scope, storage=storage,
                                 grants=grants)
        if not review["blockers"]:
            review["approval_card"] = _retire_card(args, review)
        return review
    result = gen.retire(adapter, tuple(args.generation), **scope, storage=storage,
                        grants=grants, approved_plan_id=args.plan_id or "",
                        confirmed=args.confirm_writes)
    if result.get("status") == "stopped":
        raise Blocked("RETIRE_STOPPED", result["error"], result=result)
    return result


def _card_context(args) -> dict:
    from ekg_core import approval
    return approval.azure_context(args.tenant_id, None,
                                  approval.search_service_name(args.search_endpoint))


_RESOURCE_NAMES = {"knowledgesources": "Knowledge Source", "knowledgebases": "knowledge base",
                   "indexes": "index", "indexers": "indexer", "skillsets": "skillset",
                   "datasources": "data source"}
_REMOVED_ORDER = ("indexer", "skillset", "data source", "content index", "graph index")


def _removed_label(op: dict) -> str:
    if op["kind"] == "indexes":
        return "graph index" if op["name"].endswith("graph-index") else "content index"
    return _RESOURCE_NAMES.get(op["kind"], op["kind"])


def _retire_card(args, review: dict) -> str:
    from ekg_core import approval
    changes = []
    for op in review["operations"]:
        if op["kind"] == "blobs" or op["action"] != "delete":
            continue
        if op["kind"] == "roleassignments":
            changes.append(f"Remove {op['role']} for {op['principal']} on index {op['index']}")
            continue
        text = f"Delete {_RESOURCE_NAMES.get(op['kind'], op['kind'])} {op['name']}"
        removed = [_removed_label(o) for o in review["operations"]
                   if o["action"] == "await_removal" and o["generation"] == op["generation"]]
        if op["kind"] == "knowledgesources" and removed:
            labels = sorted(set(removed), key=lambda label: (
                _REMOVED_ORDER.index(label) if label in _REMOVED_ORDER else 99, label))
            listed = (", ".join(labels[:-1]) + " and " + labels[-1]) if len(labels) > 1 \
                else labels[0]
            text += (f" (its generated {listed} are removed with it;"
                     " a scheduled Knowledge Source stops polling)")
        changes.append(text)
    for prefix in review["write"]["blob_prefixes"]:
        count = sum(1 for op in review["operations"] if op["kind"] == "blobs"
                    and f"{op['container']}/{op.get('prefix', op['generation'] + '/')}" == prefix)
        changes.append(f"Delete {count} staged blob(s) under {prefix}")
    names = _card_context(args)
    return approval.card(
        what=f"retire {len(dict.fromkeys(args.generation))} generation(s)",
        plan_id=review["plan_id"], changes=changes, time=approval.time_text(1, 5),
        cost=approval.cost_text(0.0), tenant_id=args.tenant_id,
        tenant_name=names.get("tenant_name"), subscription=names.get("subscription"),
        resource_group=names.get("resource_group"))


def _update_card(args, spec, review: dict) -> str:
    from ekg_core import approval
    from .estimates import extraction_estimate
    write, stale = review["write"], review["stale"]
    changes = [text for text, count in (
        (f"Upload {write['stage']} new or changed document(s)", write["stage"]),
        (f"Stop serving {write['remove']} removed document(s)", write["remove"]),
        (f"Delete {len(stale['chunks'])} stale chunk(s) and {len(stale['triples'])} stale "
         "graph fact(s)", write["document_deletes"]),
        ("Run the Knowledge Source indexer once", write["indexer_runs"]),
    ) if count]
    changes.append("Rewrite the local descriptor with the new source mapping")
    estimate = extraction_estimate(spec, write["stage"])
    cost = estimate.get("extraction_cost_usd")
    wall = estimate.get("minimum_wall_seconds") or 0
    names = _card_context(args)
    return approval.card(
        what=f"update published generation {review['generation']}",
        plan_id=review["plan_id"], changes=changes,
        time=approval.time_text(wall / 60 + 2, wall / 60 * 1.5 + 10),
        cost=approval.cost_text((cost["low"], cost["high"]) if cost else 0.0),
        tenant_id=args.tenant_id, tenant_name=names.get("tenant_name"),
        subscription=names.get("subscription"), resource_group=names.get("resource_group"))


def _handle_inventory(args, source) -> dict:
    if source is None:
        raise Blocked("USAGE", "inventory requires an explicit source")
    if source.kind in {SourceKind.LOCAL_PATH, SourceKind.ZIP_ARCHIVE}:
        from .local_sources import inventory_local_source
        manifest = inventory_local_source(source)
    elif source.kind is SourceKind.BLOB_PREFIX:
        if not args.tenant_id:
            raise Blocked("USAGE", "Blob inventory requires --tenant-id")
        from .blob_sources import AzureBlobReader, inventory_blob_prefix
        manifest = inventory_blob_prefix(
            source, AzureBlobReader(tenant_id=args.tenant_id),
            tenant_id=args.tenant_id,
        ).manifest
    else:
        raise Blocked("USAGE", "no inventory adapter exists for this source kind")
    body = {"manifest": asdict(manifest), "digest": manifest.digest}
    if args.output:
        try:
            with open(args.output, "x", encoding="utf-8") as handle:
                json.dump(body, handle, indent=2)
        except FileExistsError as error:
            raise Blocked("USAGE", "--output must be a new file") from error
    elif not args.json:
        raise Blocked("USAGE", "inventory needs --output <new-file> (or --json to print the "
                      "manifest)")
    return {"summary": f"Inventoried {len(manifest.items)} source item(s)"
                       + (f" into {args.output}." if args.output else "."),
            **body,
            "next_step": "Pass the manifest file as --source-manifest to `ekg-build plan`."}


_UPDATE_BLOCKS = {"waiting": "UPDATE_WAITING", "stopped": "UPDATE_STOPPED",
                  "inconsistent": "UPDATE_INCONSISTENT"}


def _handle_update(args, spec) -> dict:
    if len(args.descriptor) != 1 or not spec.source_manifest:
        raise Blocked("USAGE", f"{args.command} requires one --descriptor and --source-manifest")
    if not args.search_endpoint or not args.storage_endpoint or not args.tenant_id:
        raise Blocked("USAGE", f"{args.command} requires --search-endpoint, --storage-endpoint "
                      "and --tenant-id")
    from ekg_core import az_identity
    from . import update as content
    adapter = AzureDataPlane(search_endpoint=args.search_endpoint,
                             storage_endpoint=args.storage_endpoint,
                             credential=az_identity.cli_credential(args.tenant_id),
                             search_api_version=search_api_version(spec))
    _check_tenant(adapter, args.tenant_id)
    if args.command == "plan-update":
        review = content.update_plan(adapter, spec, args.descriptor[0])
        if not review["blockers"]:
            review["approval_card"] = _update_card(args, spec, review)
        return review
    reader = None
    if spec.source.kind is SourceKind.BLOB_PREFIX:
        from .blob_sources import AzureBlobReader
        reader = AzureBlobReader(tenant_id=spec.tenant_id)
    result = content.update(adapter, spec, args.descriptor[0], reader=reader,
                            approved_plan_id=args.plan_id or "",
                            confirmed=args.confirm_writes)
    if result["status"] != "updated":
        raise Blocked(_UPDATE_BLOCKS.get(result["status"], "UPDATE_STOPPED"),
                      result["summary"], result=result)
    return result


def _propose_cleanup(args, spec, published: dict) -> dict | None:
    """Publish only proposes cleanup; it never deletes."""
    if len(args.descriptor) != 1 or not spec.tenant_id:
        raise Blocked("USAGE", "publish takes one --descriptor (the previous serving "
                      "descriptor) and --tenant-id to propose cleanup")
    from ekg_core import az_identity
    from . import generations as gen
    adapter = AzureDataPlane(search_endpoint=args.search_endpoint,
                             credential=az_identity.cli_credential(spec.tenant_id),
                             search_api_version=SEARCH_API_VERSION)
    try:
        return gen.cleanup_proposal(adapter, published, args.descriptor[0],
                                    search_endpoint=args.search_endpoint,
                                    storage=_staged_storage(args),
                                    grants=_index_grants(args, adapter))
    except (ValueError, RuntimeError) as error:
        return {"summary": f"Cleanup proposal unavailable: {error}.",
                "retire_plan_id": None,
                "next_step": "Run `ekg-build generations` to review."}


def _arm(args):
    from ekg_core import az_identity
    return AzureDataPlane(search_endpoint=args.search_endpoint or "https://unused",
                          credential=az_identity.cli_credential(args.tenant_id))


def _journaled_readers(args) -> tuple[str, ...] | None:
    try:
        record = json.loads(Path(args.build_journal).read_text(encoding="utf-8"))
    except (TypeError, OSError, ValueError):
        return None
    found = record.get("readers") if isinstance(record, dict) else None
    return tuple(found) if isinstance(found, list) else None


def _readers(args) -> tuple[str, ...]:
    """--reader plus the index-scoped readers of the published descriptor (read-only).
    Once a run is journaled its approved reader set is fixed: re-detecting would move the
    plan ID whenever a reader changes on the old indexes, or after publish."""
    from . import readers
    try:
        found = readers.parse(args.reader)
        journaled = _journaled_readers(args) if args.command != "plan" else None
        if journaled is not None:
            if args.reader and set(found) - set(journaled):
                raise ValueError("this run's reader set is fixed by its approved plan; "
                                 "plan a new build to change it")
            return journaled
        if (args.command in ("plan", "apply") and len(args.descriptor) == 1
                and args.search_resource_id and args.tenant_id):
            published = json.loads(Path(args.descriptor[0]).read_text(encoding="utf-8"))
            carried = readers.published(_arm(args), args.search_resource_id, published,
                                        args.tenant_id)
            print(f"Index-scoped readers on the published generation: "
                  f"{', '.join(carried) or 'none'}", file=sys.stderr)
            found = readers.parse(found + carried)
    except (OSError, ValueError, RuntimeError) as error:
        raise Blocked("INVALID_INPUT", f"readers: {error}") from error
    return found


def _check_grant_permission(args, spec, desired):
    """Block the plan up front rather than fail after an expensive apply."""
    if not spec.readers or not spec.target.search_resource_id or args.command not in (
            "plan", "apply"):
        return desired
    from dataclasses import replace
    from . import readers
    if readers.can_grant(_arm(args), spec.target.search_resource_id, spec.tenant_id):
        return desired
    return replace(desired, blocked_by=(*desired.blocked_by, (
        "READER_GRANT_DENIED: the signed-in identity cannot write role assignments on the "
        "Search service, so it cannot grant the readers. Next: build as an identity with "
        "Role Based Access Control Administrator (or Owner) on the service, or drop --reader "
        "and grant the reader role yourself after the build.")))


_LIVE = ("inspect", "apply", "verify", "reconcile", "publish", "progress", "attribution",
         "trial-report")


def _publish(args, spec, executor) -> dict:
    from .update import updated_in_place
    when = updated_in_place(spec)
    if when:
        return {"status": "current",
                "summary": f"Already published: this generation was updated in place on {when}, "
                           "so its descriptor is current. Nothing to do."}
    published = publish(spec, executor).to_dict()
    from . import grounding_report
    covered = (getattr(executor, "last_verified", None) or {}).get("grounding_coverage")
    from .browse import write_descriptor
    try:
        result = write_descriptor(published, args.output, args.descriptor, spec.tenant_id,
                                  set_current=not args.keep_current)
    except ValueError as error:
        raise Blocked("USAGE", str(error)) from error
    if args.descriptor:
        proposal = _propose_cleanup(args, spec, published)
        result["cleanup_proposal"] = proposal
        result["next_step"] = proposal["next_step"]
    return grounding_report.attach(result, covered)


def _build_changes(spec, desired) -> list[str]:
    from .executor import staging_prefix
    documents = len(spec.source_manifest.items) if spec.source_manifest else None
    count = f"{documents} document(s)" if documents is not None else "the corpus"
    text = {
        "stage-corpus": (f"Upload {count} to Blob container {spec.storage_container} under "
                         f"{staging_prefix(spec)}/"),
        "ensure-content-index": "Create the content search index",
        "ensure-ontology-index": f"Create the ontology index ({spec.ontology_mode.value})",
        "create-managed-knowledge-source": (
            "Create one Knowledge Source; Azure AI Search then creates its indexer, skillset "
            "and graph index and extracts the graph with your chat deployment"),
        "grant-readers": f"Grant Search Index Data Reader to {len(spec.readers)} reader(s)",
    }
    return [text.get(op.id, f"{op.action} {op.resource} {op.name}")
            for op in desired.operations if op.requires_approval]


def _build_card(spec, desired) -> str | None:
    from ekg_core import approval
    changes = _build_changes(spec, desired)
    if desired.blocked_by or not changes:
        return None
    extraction = (desired.estimates or {}).get("extraction") or {}
    wall = extraction.get("minimum_wall_seconds")
    measured = extraction.get("wall_minutes")
    # Measured rates give the extraction floor; staging and indexer scheduling add minutes.
    no_rate = (f"no measured rate for reasoning effort {extraction['reasoning_effort']}"
               if extraction.get("reasoning_effort") and spec.source_manifest is not None
               else "no source manifest")
    time = (approval.time_text(measured["low"] + 3, measured["high"] + 10) if measured
            else approval.time_text(wall / 60 + 3, wall / 60 * 1.5 + 10) if wall is not None
            else f"unknown ({no_rate})")
    if measured and (extraction.get("indexer_runs") or 1) > 1:
        time += (f", across about {extraction['indexer_runs']} indexer runs "
                 "(elapsed may be longer)")
    cost = extraction.get("extraction_cost_usd")
    one_time = (cost["low"], cost["high"]) if cost else (0.0 if not desired.estimates else None)
    parts = str(spec.target.search_resource_id or "").split("/")
    lowered = [part.lower() for part in parts]
    group = (parts[lowered.index("resourcegroups") + 1]
             if "resourcegroups" in lowered[:-1] else None)
    subscription = parts[2] if len(parts) > 2 and lowered[1:2] == ["subscriptions"] else None
    names = approval.azure_context(
        spec.tenant_id, subscription,
        None if group else approval.search_service_name(spec.target.search_endpoint))
    what = (f"run a trial build on {spec.trial.size} of {spec.trial.corpus_documents} documents"
            if spec.trial is not None else "build the knowledge graph")
    return approval.card(
        what=what, plan_id=desired.plan_id, changes=changes, time=time,
        cost=approval.cost_text(
            one_time, unknown_reason="model price not listed" if measured or wall is not None
            else no_rate),
        tenant_id=spec.tenant_id,
        tenant_name=names.get("tenant_name"),
        subscription=names.get("subscription") or subscription,
        resource_group=group or names.get("resource_group"),
        notes=[grounding.plan_card_line(desired.grounding)] if desired.grounding else [])


def _handle_result(args, spec, desired):
    if args.command in ("plan-update", "update"):
        return _handle_update(args, spec)
    if args.command == "plan":
        result = desired.to_dict()
        card = _build_card(spec, desired)
        if card:
            result["approval_card"] = card
        return result
    if args.command in ("descriptor", "preflight"):
        return (preflight(spec).to_dict() if args.command == "preflight" else
                descriptor(spec).to_dict())
    if desired.blocked_by and (
        desired.route is not None or spec.ontology_mode is not OntologyMode.NONE
    ) and args.command in _LIVE:
        raise Blocked("BUILD_BLOCKED", desired.blocked_by[0],
                      result={"plan_id": desired.plan_id, "blocked_by": list(desired.blocked_by)})
    if not args.search_endpoint or not args.storage_endpoint:
        raise Blocked("USAGE", "live commands require --search-endpoint and --storage-endpoint")
    adapter = AzureDataPlane(search_endpoint=args.search_endpoint,
                             storage_endpoint=args.storage_endpoint,
                             openai_endpoint=args.openai_endpoint,
                             embedding_deployment=args.embedding_deployment,
                             search_api_version=(search_api_version(spec)
                                                 if spec.ontology_mode is not OntologyMode.NONE
                                                 else "2024-07-01"))
    if spec.source_manifest:
        from .target_reader import AzureTargetReader
        from .blob_sources import AzureBlobReader
        executor = BuildExecutor(
            adapter, target_reader=AzureTargetReader(tenant_id=spec.tenant_id),
            blob_reader=(AzureBlobReader(tenant_id=spec.tenant_id)
                         if spec.source.kind is SourceKind.BLOB_PREFIX else None),
        )
    else:
        executor = BuildExecutor(adapter)
    executor.upload_concurrency = getattr(args, "upload_concurrency", 16)
    if args.command == "inspect":
        return executor.inspect(spec)
    if args.command == "verify":
        return executor.verify(spec)
    if args.command == "reconcile":
        return executor.reconcile(spec)
    if args.command == "progress":
        return executor.progress(spec)
    if args.command == "attribution":
        from .attribution import collect
        from .executor import index_names as managed_names
        return collect(adapter, managed_names(spec)["knowledge_source"],
                       openai_resource_id=spec.target.openai_resource_id,
                       search_resource_id=spec.target.search_resource_id,
                       tenant_id=spec.tenant_id)
    if args.command == "publish":
        return _publish(args, spec, executor)
    if args.command == "trial-report":
        from . import trial
        return trial.collect(executor, spec)
    applied = executor.apply(spec, approved_plan_id=args.plan_id or "",
                             approved=args.confirm_writes, wait_for_sync=args.wait)
    result = {"plan_id": desired.plan_id, "completed": applied.completed,
              "events": [asdict(e) for e in applied.events]}
    if not applied.completed:
        raise Blocked("APPLY_INCOMPLETE", "the build did not complete", result=result)
    from . import grounding_report
    return grounding_report.attach(result, grounding_report.for_build(adapter, spec))


def _source(args):
    if not args.corpus and not args.source_kind:
        raise Blocked("USAGE", "--corpus or --source-kind is required")
    if bool(args.source_kind) != bool(args.source_reference):
        raise Blocked("USAGE", "--source-kind and --source-reference must be supplied together")
    try:
        return SourceLocator(
            kind=SourceKind(args.source_kind), reference=args.source_reference,
            resource_id=args.source_resource_id, container=args.source_container,
            prefix=args.source_prefix, library_id=args.source_library_id,
        ) if args.source_kind else None
    except ValueError as error:
        raise Blocked("USAGE", str(error)) from error


_EXPLICIT_SOURCE_FLAGS = {
    "--source-kind", "--source-reference", "--source-resource-id", "--source-container",
    "--source-prefix", "--source-library-id", "--source-manifest",
}


def _check_source_flags(args, argv: list[str]) -> None:
    conflicts = sorted(flag for flag in _EXPLICIT_SOURCE_FLAGS
                       if getattr(args, flag[2:].replace("-", "_"), None) is not None)
    if getattr(args, "corpus", None) is None or not conflicts:
        return
    corrected = []
    index = 0
    while index < len(argv):
        part = argv[index]
        option = part.split("=", 1)[0]
        if option.startswith("--") and "--corpus".startswith(option):
            index += 1 if "=" in part else 2
        else:
            corrected.append(part)
            index += 1
    command = shlex.join([PROG, *corrected])
    raise Blocked(
        "USAGE", f"--corpus is legacy-only and cannot be combined with {', '.join(conflicts)}. "
        f"Use explicit sources by removing --corpus (POSIX shell): {command}. "
        "Complete any missing source flags, then review a fresh plan before writes.",
        result={"conflicting_flags": ["--corpus", *conflicts],
                "corrected_args": [PROG, *corrected], "corrected_command": command,
                "corrected_command_shell": "posix"},
    )


def _manifest(args, source):
    if not args.source_manifest:
        if args.sample is not None:
            raise Blocked("USAGE", "--sample needs --source-manifest (run `ekg-build "
                          "inventory` first)")
        return None, None
    try:
        raw = json.loads(Path(args.source_manifest).read_text(encoding="utf-8"))
        payload = raw.get("manifest", raw)
        manifest = SourceManifest(
            version=payload["version"], source=source,
            observed_at=payload["observed_at"],
            items=tuple(manifest_item_from_json(item) for item in payload["items"]),
            transform_config_id=payload.get("transform_config_id", "identity"),
        )
        if raw.get("digest", manifest.digest) != manifest.digest:
            raise ValueError("source manifest digest differs from its contents")
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise Blocked("INVALID_INPUT", f"invalid source manifest: {error}") from error
    if args.sample is None:
        return manifest, None
    from .trial import sample_manifest
    try:
        return sample_manifest(manifest, args.sample)
    except ValueError as error:
        raise Blocked("USAGE", str(error)) from error


def _spec(args, source, manifest, trial=None) -> BuildSpec:
    return BuildSpec(
        target=Target(subscription_id=args.subscription_id,
                      resource_group=args.resource_group,
                      location=args.location,
                      search_endpoint=args.search_endpoint,
                      storage_endpoint=args.storage_endpoint,
                      openai_endpoint=args.openai_endpoint,
                      search_resource_id=args.search_resource_id,
                      storage_resource_id=args.storage_resource_id,
                      openai_resource_id=args.openai_resource_id),
        corpus_source=args.corpus or "",
        ontology_mode=OntologyMode(args.ontology),
        ontology_path=args.ontology_path,
        graph_retrieval=args.graph,
        agentic_retrieval=args.agentic,
        embedding_deployment=args.embedding_deployment,
        embedding_model=args.embedding_model,
        embedding_dimensions=args.embedding_dimensions,
        chat_deployment=args.chat_deployment,
        chat_model=args.chat_model,
        search_identity_resource_id=args.search_identity_resource_id,
        tenant_id=args.tenant_id,
        extraction_parallelism=args.extraction_parallelism,
        extraction_reasoning_effort=args.extraction_reasoning_effort,
        ingestion_interval=args.ingestion_interval,
        grounding_index=args.grounding_index,
        search_sku=args.search_sku,
        build_journal=args.build_journal,
        storage_container=args.storage_container,
        source=source,
        source_manifest=manifest,
        requested_outcome=(RequestedOutcome(args.requested_outcome)
                           if args.requested_outcome else None),
        knowledge_source_kind=(KnowledgeSourceKind(args.knowledge_source_kind)
                               if args.knowledge_source_kind else None),
        readers=_readers(args),
        trial=trial,
    )


def _run(args) -> dict:
    if args.command == "status":
        return read_build_status(args.build_journal, args.run_id)
    if args.command == "telemetry":
        return _handle_telemetry(args)
    if args.command in ("generations", "plan-retire", "retire"):
        return _handle_generations(args)
    source = _source(args)
    if args.command == "inventory":
        return _handle_inventory(args, source)
    spec = _spec(args, source, *_manifest(args, source))
    if spec.trial is not None and args.command in ("publish", "plan-update", "update"):
        raise Blocked("BUILD_BLOCKED", "TRIAL_NOT_PUBLISHABLE: a trial build is for measurement "
                      "only; run `ekg-build trial-report`, then plan the full build without "
                      "--sample")
    if spec.trial is None and args.command == "trial-report":
        raise Blocked("USAGE", "trial-report reads a trial build: pass the same flags as its "
                      "plan, including --sample")
    desired = _check_grant_permission(args, spec, plan(spec))
    if args.chat_capacity is not None:
        if args.chat_capacity < 1:
            raise Blocked("USAGE", "--chat-capacity is a positive estimate input")
        if desired.estimates:
            from dataclasses import replace
            from .estimates import plan_estimates
            desired = replace(desired, estimates=plan_estimates(
                spec, chat_capacity_k_tpm=args.chat_capacity))
    if getattr(args, "trial_report", None) and desired.estimates:
        from dataclasses import replace
        from .estimates import trial_estimate
        try:
            report = json.loads(Path(args.trial_report).read_text(encoding="utf-8"))
            measured = trial_estimate(spec, report)
        except (OSError, ValueError) as error:
            raise Blocked("USAGE", str(error)) from error
        desired = replace(desired, estimates={**desired.estimates, "extraction": measured})
    if (args.command == "plan" and spec.ontology_mode is not OntologyMode.NONE
            and spec.build_journal and Path(spec.build_journal).exists()):
        from dataclasses import replace
        desired = replace(desired, blocked_by=(*desired.blocked_by, (
            f"BUILD_JOURNAL_IN_USE: {spec.build_journal} already records a build attempt. "
            "Reconcile that attempt with the same flags, or pass a new --build-journal path "
            "for another build (for example, the full build after a trial).")))
    if (args.command == "plan" and spec.grounding_index and spec.target.search_endpoint
            and not desired.blocked_by):
        from dataclasses import replace
        from .managed_pipeline import grounding_live_blocker
        found = grounding_live_blocker(
            AzureDataPlane(search_endpoint=spec.target.search_endpoint,
                           search_api_version=search_api_version(spec)), spec)
        if found:
            desired = replace(desired, blocked_by=(*desired.blocked_by, found))
    return _handle_result(args, spec, desired)


def _classify(error: Exception, command: str) -> Blocked:
    from ekg_core.az_identity import IdentityError
    from ekg_core.execution import ApprovalRequired
    from .blob_sources import BlobSourceError
    from .sharepoint_sources import SharePointReadError, SharePointSourceError
    from .executor import BuildError
    from .generations import RetireError
    from .update import UpdateError
    text = str(error)
    if isinstance(error, ApprovalRequired):
        return Blocked("APPROVAL_REQUIRED", text, plan_verb=_PLAN_VERB.get(command, "plan"))
    if isinstance(error, IdentityError):
        return Blocked("AZ_SIGNIN", text)
    if isinstance(error, RetireError):
        return Blocked("RETIRE_BLOCKED", text)
    if isinstance(error, UpdateError):
        return Blocked("UPDATE_BLOCKED", text)
    if isinstance(error, BuildError):
        return Blocked("BUILD_BLOCKED", text)
    if isinstance(error, (SharePointSourceError, SharePointReadError, BlobSourceError)):
        return Blocked("SOURCE_UNAVAILABLE", text)
    if isinstance(error, OSError):
        return Blocked("LOCAL_IO", text)
    if isinstance(error, ValueError):
        return Blocked("INVALID_INPUT", text)
    # An Azure failure part-way through a write leaves an unknown outcome: settle it first.
    return Blocked({"apply": "APPLY_INCOMPLETE", "update": "UPDATE_STOPPED",
                    "retire": "RETIRE_STOPPED"}.get(command, "AZURE_ERROR"), text)


def _say(result, args) -> None:
    if args.command == "telemetry" and not args.json:
        result = _telemetry_summary(result)
    say(result, args, prog=PROG)


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = parse(_parser(), argv, _DEFAULTS)
    if args.command == "doctor":
        from ekg_core import doctor
        doctor.run(PROG, args)
        return
    try:
        _check_source_flags(args, argv)
        result = _run(args)
    except Blocked as blocked:
        report(blocked, prog=PROG, command=args.command)
    except (RuntimeError, ValueError, OSError) as error:
        report(_classify(error, args.command), prog=PROG, command=args.command)
    _say(result, args)
