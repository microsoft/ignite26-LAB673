"""Shared CLI output: a short summary by default, the full JSON with --json, one next step per error."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Callable

NEXT_STEPS = {
    # Operator environment (doctor)
    "PYTHON_TOO_OLD": "install Python 3.12 or newer (uv python install 3.12), then run doctor again.",
    "UV_MISSING": "install uv (https://docs.astral.sh/uv/getting-started/installation/), then run doctor again.",
    "AZ_CLI_MISSING": "install the Azure CLI, then run doctor again with --tenant-id.",
    "AZ_SIGNIN_REQUIRED": "sign in to the tenant passed in --tenant-id (az login --tenant ...), then run doctor again.",
    "STATE_DIR_NOT_WRITABLE": "pass a writable --state-dir, or fix permissions on this one.",
    "NAMING_DEPLOYMENT_UNREACHABLE": "check --naming-endpoint and --naming-deployment, and that this identity can read the Azure OpenAI resource.",
    "MCP_SELF_TEST_FAILED": "reinstall the plugin (uv tool install --force), then run grz-mcp --self-test.",
    "CLI_ERROR": "run doctor, fix the first failed check, then retry.",
    # Arguments and inputs
    "INPUT_INVALID": "check the flags and input files named in the error, then retry.",
    "ARGS_INVALID": "pass tool arguments as a JSON object with only the listed properties.",
    "TOOL_NOT_FOUND": "call tools/list to see the available grz_ tools.",
    "AUTH_UNSUPPORTED": "set --auth (or GRZ_SEARCH_AUTH) to query-key or entra.",
    "AZURE_LIVE_ARGS_REQUIRED": "add the missing flags listed above.",
    "COMMAND_UNSUPPORTED": "run a supported Azure command; see --help.",
    "DATASET_INVALID": "pass --dataset as a lowercase slug (letters, digits, hyphens).",
    "SEARCH_SERVICE_INVALID": "pass --search-service as the service name, not a URL.",
    "ENDPOINT_INVALID": "pass an https:// Search endpoint.",
    "NAMING_ARGS_REQUIRED": "add the missing naming flags listed above, or drop --naming-deployment.",
    "NAMING_ENDPOINT_INVALID": "pass --naming-endpoint as an https:// Azure OpenAI endpoint.",
    "PROFILE_NOT_FOUND": "pass --profile as a JSON file path or one of the bundled profile names.",
    "BUILD_PROFILE_INVALID": "fix the build profile named in the error, then run plan again.",
    "READER_INVALID": "pass --reader as a principal object ID (GUID).",
    "SOURCE_REQUIRED": "pass --endpoint (or GRZ_SEARCH_ENDPOINT).",
    "DESCRIPTOR_REQUIRED": "publish a build from this account, or pass --descriptor (or set GRZ_DESCRIPTOR) with the file the builder gave you.",
    "CURRENT_INVALID": "publish the build again, or pass --descriptor (or set GRZ_DESCRIPTOR) to skip the record.",
    "DESCRIPTOR_INVALID": "ask the builder for a fresh descriptor from apply or verify.",
    "QUERY_INVALID": "check the query arguments named in the error, then retry.",
    "FASTEMBED_MISSING": "install the embed extra in this environment, then retry.",
    "QUESTION_EMBEDDER_UNSUPPORTED": "pass a precomputed vector with --question-vector / question_vector.",
    "QUESTION_INVALID": "pass nonempty question text of 2000 characters or fewer.",
    "QUERY_VECTOR_INVALID": "pass a finite vector with the dimension shown in status.",
    "MEMBER_RANKING_UNAVAILABLE": "rebuild the generation, or list members without a question.",
    "LIMIT_INVALID": "pass a limit between 1 and 100.",
    "PAGE_SIZE_INVALID": "pass --page-size between 1 and 1000.",
    "CURSOR_INVALID": "drop the cursor and start from the first page.",
    "LEVEL_INVALID": "run status to see the levels this generation has.",
    "LEVEL_NOT_FOUND": "run status to see the levels this generation has.",
    "COMMUNITY_NOT_FOUND": "run list-communities to see valid community IDs.",
    "CHUNK_NOT_FOUND": "run list-members to see chunk IDs in a community.",
    "EMBEDDING_MODEL_MISMATCH": "embed the query with the model named in status.",
    # Source snapshot and inspection
    "INPUT_COUNT_MISMATCH": "re-export the snapshot; its manifest count does not match the files.",
    "INPUT_DUPLICATE_ID": "re-export the snapshot with unique chunk IDs.",
    "INPUT_HASH_MISMATCH": "re-export the snapshot; a file changed after its checksum was recorded.",
    "INPUT_ID_MISMATCH": "re-export the snapshot so rows and vectors share IDs.",
    "INPUT_MALFORMED": "re-export the snapshot as valid JSONL.",
    "INPUT_VECTOR_INVALID": "re-export the snapshot with finite vectors of one dimension.",
    "SOURCE_IDENTITY_INVALID": "re-export the snapshot with a complete source identity.",
    "SOURCE_IDENTITY_MISSING": "run plan and apply again so the source contract is saved.",
    "VISIBILITY_UNSUPPORTED": "use public or synthetic data only; map every --security-field and confirm it reads public.",
    "OWNER_APPROVAL_REQUIRED": "pass --owner-approval, --frozen-evidence and --security-inspection.",
    "SOURCE_APPROVAL_REQUIRED": "pass --owner-approval, --frozen-evidence and --security-inspection.",
    "SOURCE_APPROVAL_MISMATCH": "pass approvals that name this tenant, service and source index.",
    "SOURCE_TARGET_MISMATCH": "pass approvals that name this Search service and source index.",
    "SOURCE_FIELDS_INVALID": "map distinct, retrievable key, text, source and vector fields.",
    "SOURCE_KEY_INVALID": "pass --key-field as the source index key.",
    "SOURCE_SCAN_UNSUPPORTED": "use a source index with a stable, supported scan key.",
    "SOURCE_VECTORS_NOT_RETRIEVABLE": "use a source index with retrievable stored vectors.",
    "SOURCE_SECURITY_UNINSPECTED": "pass --security-field for every security-bearing field.",
    "SOURCE_VISIBILITY_UNVERIFIED": "map the visibility field with --security-field; if the index has none and every document is public, ask the source owner to confirm, then pass --source-visibility public-attested.",
    "SOURCE_VISIBILITY_MISMATCH": "pass the same --source-visibility the plan was made with, or re-plan.",
    "SOURCE_VISIBILITY_INVALID": "use --source-visibility public-attested only with --backend azure.",
    "SOURCE_VECTOR_INVALID": "check --vector-field names a vector field with a positive dimension.",
    "SOURCE_ROW_INVALID": "fix the source rows missing text or a source reference, then run plan again.",
    "SOURCE_PAGE_INVALID": "use a page size between 1 and 1000.",
    "SOURCE_PAGE_INCOMPLETE": "wait until the source is frozen, then run plan again.",
    "SOURCE_SCAN_UNSTABLE": "wait until the source is frozen, then run plan again.",
    "SOURCE_SCAN_FAILED": "run doctor to check reader access, then run plan again.",
    "SOURCE_COUNT_UNAVAILABLE": "run doctor to check reader access on the source index.",
    "SOURCE_INSPECT_FAILED": "run doctor to check reader access on the source index.",
    "SOURCE_CHANGED": "the source changed; wait until it is frozen, then run plan again.",
    "SNAPSHOT_DESTINATION_NOT_EMPTY": "pass an empty export destination.",
    # Build
    "PLAN_CHANGED": "run plan again and approve the new plan ID.",
    "PLAN_ID_MISMATCH": "pass the plan ID printed by the plan you approved.",
    "PLAN_NOT_FOUND": "run plan first, or pass --plan-file.",
    "PLAN_BOUND_FLAG": "drop those flags from apply; to change them, run plan again and approve the new plan ID.",
    "BUDGET_APPROVAL_REQUIRED": "get approval for an --approved-budget-bytes at least the byte count the error reports.",
    "WRITE_CONFIRMATION_REQUIRED": "add --confirm-writes once the plan is approved.",
    "MODEL_APPROVAL_REQUIRED": "add --approve-model-calls once the naming budget is approved.",
    "MODEL_CALLS_NOT_APPROVED": "add --approve-model-calls once the naming budget is approved.",
    "NAMING_BUDGET_REQUIRED": "pass positive --naming-max-calls, --naming-max-tokens, --naming-max-spend-usd and --naming-timeout-seconds.",
    "NAMING_BUDGET_EXCEEDED": "run reconcile, then plan again with a larger approved naming budget.",
    "NAMING_PROVIDER_REQUIRED": "pass the same --naming-* flags used at plan time.",
    "NAMING_ACCESS_DENIED": "ask for Cognitive Services OpenAI User on the naming resource, then run doctor.",
    "NAMING_DEPLOYMENT_NOT_FOUND": "fix --naming-deployment to a deployment on the Azure OpenAI account, then run doctor again.",
    "NAMING_DEPLOYMENT_NOT_READY": "wait for the naming deployment to finish provisioning, or fix --naming-deployment.",
    "NAMING_MODEL_RETIRED": "deploy a GenerallyAvailable chat model, then plan again with its --naming-deployment and --naming-model.",
    "NAMING_ACCOUNT_NOT_FOUND": "check --subscription-id, --naming-resource-group and the account in --naming-endpoint.",
    "NAMING_ARM_ACCESS_DENIED": "ask for Reader on the Azure OpenAI account, or omit --subscription-id to skip the deployment check.",
    "MEMORY_BUDGET_EXCEEDED": "use a smaller snapshot or a profile with a larger memory budget.",
    "DEPENDENCY_UNAVAILABLE": "reinstall the plugin so its pinned dependencies are present, then run doctor.",
    "AZURE_DEPENDENCY_MISSING": "reinstall the plugin with its azure extra, then run doctor.",
    "GRAPH_INVALID": "re-export the snapshot with unique chunk IDs, then run plan again.",
    "HIERARCHY_INVALID": "use a snapshot with at least one chunk, then run plan again.",
    "CENTROID_INVALID": "re-export the snapshot with nonzero finite vectors.",
    "COMMUNITY_ID_COLLISION": "run plan again with a different profile; report this collision.",
    "DUPLICATE_MEMBER": "run plan again; report this as a build bug.",
    "GENERATION_INVALID": "pass a full 64-character generation ID from apply or generations.",
    "GENERATION_CHANGED": "run plan again; the saved generation no longer matches.",
    "GENERATION_EXISTS": "run verify on the existing generation instead of apply.",
    "GENERATION_REQUIRED": "pass --generation-id with the ID that apply or verify printed.",
    "GENERATION_UNKNOWN": "run apply first, or pass --generation-id from its output; if apply stopped, run status and reconcile before any retry.",
    "REPRODUCIBILITY_DEVIATION": "run reconcile; do not publish this generation.",
    "RECONCILE_REQUIRED": "run reconcile, review it, then apply again with --resume-after-reconcile.",
    "RECONCILE_UNSUPPORTED": "run plan again; reconcile needs a plan with a target index.",
    "STATE_INVALID": "point --state-dir at the directory this plan was made in, or run plan again.",
    "PUBLISHER_BUSY": "wait for the other publish to finish, then run status.",
    "BUILD_FAILED": "run grz-build status to see where apply stopped, then reconcile before any retry.",
    "WRITE_FAILED": "run reconcile before any retry; never repeat an unknown-outcome write.",
    "UPLOAD_FAILED": "run reconcile before any retry; never repeat an unknown-outcome write.",
    "READBACK_MISMATCH": "run reconcile, then verify.",
    "READBACK_NOT_SETTLED": "wait a minute for Search to finish indexing, then run reconcile and verify.",
    # Search service and publication
    "TENANT_REQUIRED": "pass --tenant-id for the tenant that owns the Search service.",
    "TENANT_MISMATCH": "sign in to the tenant passed in --tenant-id (az login --tenant ...).",
    "TOKEN_INVALID": "sign in again (az login --tenant ...), then run doctor.",
    "ARM_REQUEST_FAILED": "run doctor, then check --subscription-id and --resource-group.",
    "SEARCH_REQUEST_FAILED": "run doctor to check sign-in and Search reader access.",
    "SEARCH_SERVICE_NOT_FOUND": "check --subscription-id, --resource-group and --search-service.",
    "SEARCH_SERVICE_MISMATCH": "check --search-service names the service in this resource group.",
    "SEARCH_HEADROOM_INSUFFICIENT": "free an index slot (generations, then plan-retire) or use a larger service.",
    "PLACEMENT_UNSUPPORTED": "publish into the same Search service and tenant as the source.",
    "INDEX_COLLISION": "run plan again; the target index already exists.",
    "INDEX_EXISTS": "run verify on the existing generation instead of apply.",
    "INDEX_INVALID": "use the generation index name printed by plan.",
    "INDEX_MISSING": "run status; the generation index is gone, so run plan and apply again.",
    "SCHEMA_UNSUPPORTED": "upgrade the plugin; this sidecar schema is not supported.",
    "SIDECAR_SCHEMA_UNAVAILABLE": "reinstall the plugin; its sidecar schema file is missing.",
    "SIDECAR_SCHEMA_MISMATCH": "run reconcile; the target index does not match the sidecar schema.",
    "SIDECAR_DOCUMENT_INVALID": "run plan again; report this as a build bug.",
    "DOCUMENT_INVALID": "run plan again; report this as a build bug.",
    "DUPLICATE_DOCUMENT": "run reconcile; never overwrite another document.",
    "VECTOR_DIMENSION_INVALID": "run plan again with a snapshot of one vector dimension.",
    "VECTOR_PROBE_FAILED": "run verify again; if it repeats, run reconcile.",
    "PUBLICATION_APPROVAL_REQUIRED": "pass every approval flag named in the error.",
    "PUBLICATION_BATCH_INVALID": "use an upload batch size between 1 and 1000.",
    "PUBLICATION_PERMISSION_DENIED": "ask for Search Service Contributor and Search Index Data Contributor, then run doctor.",
    "PUBLICATION_READBACK_FAILED": "run doctor to check reader access, then verify.",
    "PUBLICATION_RESULT_INCOMPLETE": "run reconcile before any retry.",
    "PUBLICATION_TARGET_INVALID": "pass --dataset as a lowercase slug.",
    "PUBLICATION_TARGET_MISMATCH": "run plan again; the target index must belong to --dataset.",
    "PUBLICATION_UPLOAD_FAILED": "run reconcile before any retry; never repeat an unknown-outcome write.",
    "PUBLICATION_VERIFY_FAILED": "run reconcile, then verify.",
    "PUBLICATION_VERIFY_REQUIRED": "run verify first.",
    # Native binary runner and adapters
    "NATIVE_ARTIFACTS_MISSING": "check that the native binary completed and wrote all output artifacts to the artifact directory.",
    "NATIVE_ARTIFACTS_INVALID": "check native build logs and ensure output artifacts are complete and valid.",
    "NATIVE_BINARY_NOT_FOUND": "configure GRZ_NATIVE_BINARY or pass --native-binary pointing to the GRZBuildPoc binary for your platform.",
    "NATIVE_PLATFORM_UNSUPPORTED": "use Windows x64, Linux x64/ARM64, or macOS x64/ARM64.",
    "NATIVE_BINARY_CHECKSUM_REQUIRED": "supply a trusted expected_sha256 to NativeRunner for this platform.",
    "NATIVE_BINARY_UNREADABLE": "check that the native binary file is readable.",
    "NATIVE_BINARY_NOT_EXECUTABLE": "grant execute permission to the native binary with chmod +x.",
    "BINARY_HASH_MISMATCH": "ensure GRZBuildPoc matches the approved SHA-256 hash for your platform or update the pinned digest.",
    "CONFIG_INVALID": "fix the invalid configuration keys or values in the native build config.",
    "NATIVE_CLI_PROTOCOL_ERROR": "ensure the native CLI outputs a valid grz-cli-v1 JSON envelope on stdout.",
    "NATIVE_COMMAND_UNSUPPORTED": "use a supported native CLI command (validate, plan, or execute).",
    "NATIVE_EXECUTION_TIMEOUT": "increase native CLI execution timeout or reduce dataset size.",
    "NATIVE_EXECUTION_FAILED": "check native CLI error logs and stderr output for failure details.",
    "UNASSIGNED_CHUNK_LABELED": "verify that post-clustering enrichment only labels assigned communities, not unassigned chunks.",
    "PUBLISH_APPROVAL_REQUIRED": "add --approve-cutover once the cutover is approved.",
    "CUTOVER_APPROVAL_REQUIRED": "add --approve-cutover once the cutover is approved.",
    "PUBLISH_BINDING_MISMATCH": "pass the same --alias, --source-index and --vector-field used at plan time.",
    "ALIAS_CHANGED": "someone else published; run status, then plan again.",
    "ALIAS_FOREIGN": "choose a grz- alias with --alias; this one serves a non-GRZ index.",
    "ALIAS_INVALID": "pass --alias, or a --vector-field that yields a nonempty alias.",
    "ALIAS_UNAVAILABLE": "run doctor to check sign-in and Search rights on the alias.",
    "ALIAS_VERIFY_FAILED": "run status to see where the alias points before any retry.",
    "QUERY_ONLY_VIOLATION": "use the descriptor from verify; it binds one physical index.",
    "READ_ACCESS_DENIED": "ask the builder to grant Search Index Data Reader on the sidecar, then run doctor.",
    "READERS_MISSING": "run plan with --reader for each listed reader (or --drop-reader), then apply.",
    "READER_GRANTS_FORBIDDEN": "ask an owner of the Search service to run this, or drop --reader.",
    "READER_GRANTS_UNREADABLE": "ask for rights to read role assignments on the Search service, then plan again.",
    "READER_GRANTS_UNSUPPORTED": "drop --reader and --drop-reader; this backend has no role assignments.",
    "READER_GRANT_FAILED": "run reconcile before any retry.",
    "READER_REVOKE_FAILED": "remove the listed read grant by hand, then run generations.",
    # Retire
    "RETIRE_BINDING_MISMATCH": "run plan-retire again with the same service, dataset and alias.",
    "RETIRE_PLAN_STALE": "run plan-retire again and approve the new plan.",
    "RETIRE_TARGET_PROTECTED": "run generations; only superseded generations can be retired.",
    "RETIRE_TARGET_UNKNOWN": "run generations to see the retirable indexes.",
    "RETIRE_DELETE_FAILED": "run generations before any retry; never repeat an unknown-outcome delete.",
    "RETIRE_READBACK_FAILED": "run generations to see where the index and alias stand.",
    # Consume
    "SIDECAR_INTEGRITY_FAILED": "ask the builder to run verify on this generation.",
}


def add_json_option(parser: argparse.ArgumentParser, *, subcommand: bool = False) -> None:
    """Accept --json before or after the subcommand; SUPPRESS keeps a subparser from resetting it."""
    parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS if subcommand else False,
                        help="Print the full JSON result instead of a short summary")


def add_version_option(parser: argparse.ArgumentParser) -> None:
    from importlib.metadata import PackageNotFoundError, version
    try:
        installed = version("grz-skills")
    except PackageNotFoundError:
        installed = "unknown"
    parser.add_argument("--version", action="version", version=f"%(prog)s {installed}")


def next_step(code: str) -> str:
    return NEXT_STEPS.get(code) or NEXT_STEPS["CLI_ERROR"]


def error_body(exc: BaseException, default_code: str) -> dict[str, str]:
    """The one blocked envelope: status, UPPER_SNAKE code, message, exactly one next step."""
    code = getattr(exc, "code", None) or default_code
    message = str(exc)
    if message.startswith(f"{code}: "):
        message = message[len(code) + 2:]
    embedded = None
    if "Next step:" in message:
        message, embedded = (part.strip() for part in message.split("Next step:", 1))
    step = getattr(exc, "next_step", None) or embedded or next_step(code)
    return {"status": "blocked", "error_code": code, "error": message, "next_step": step}


def emit(result: Any, as_json: bool, summary: Callable[[Any], str] | None, *, compact: bool = True) -> None:
    if as_json or summary is None:
        print(json.dumps(result, sort_keys=True, ensure_ascii=False, allow_nan=False,
                         separators=(",", ":") if compact else None))
    else:
        print(summary(result))


def emit_error(exc: BaseException, as_json: bool, default_code: str) -> int:
    body = error_body(exc, default_code)
    if as_json:
        print(json.dumps(body, sort_keys=True, ensure_ascii=False), file=sys.stderr)
    else:
        print(f"Blocked. {body['error_code']}: {body['error']}\nNext step: {body['next_step']}", file=sys.stderr)
    return 2


def mb(value: Any) -> str:
    size = int(value or 0)
    return f"{size / 1_000_000:.1f} MB" if size >= 100_000 else f"{size / 1_000:.1f} KB"
