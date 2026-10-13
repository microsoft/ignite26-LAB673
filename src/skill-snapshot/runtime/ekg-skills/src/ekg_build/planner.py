from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from ekg_core import grounding
from ekg_core.models import BuildSpec, Operation, Plan, OntologyMode, SourceKind, stable_id
from ekg_core.ontology import load_ontology
from .estimates import plan_estimates
from .preflight import route, scope, target_blockers
from .preview import PREVIEW_ENTITLEMENT_UNVERIFIABLE, probe_error


def plan(spec: BuildSpec) -> Plan:
    if (spec.graph_retrieval and spec.ontology_mode is OntologyMode.NONE
            and spec.requested_outcome is None):
        raise ValueError("graph_retrieval requires an ontology")
    if spec.ontology_mode is OntologyMode.OWL_FILE and not spec.ontology_path:
        raise ValueError("owl_file mode requires ontology_path")
    if spec.agentic_retrieval and spec.requested_outcome is None:
        raise ValueError("agentic Knowledge Base build is not yet supported")
    decision = route(spec) if (spec.source is not None or spec.requested_outcome is not None
                               or spec.knowledge_source_kind is not None) else None
    ontology = load_ontology(
        spec.ontology_mode,
        path=spec.ontology_path,
        schema_org_profile=spec.schema_org_profile,
        schema_org_version=spec.schema_org_version,
        resolve_imports=spec.resolve_imports,
    )
    operations = [
        Operation(
            id="stage-corpus", plane="build", action="synchronize",
            resource="blob_corpus", name=spec.source.source_id if spec.source else spec.corpus_source,
            risk="data_upload", reversible=True, requires_approval=True,
            evidence=("source_count", "uploaded_count"),
        ),
    ]
    if not ontology:
        operations.append(Operation(
            id="ensure-content-index", plane="build", action="ensure",
            resource="search_index", name="content",
            risk="remote_mutation", reversible=True, requires_approval=True,
            evidence=("schema_hash", "document_count"),
        ))
    if ontology:
        operations.extend([
            Operation(
                id="ensure-ontology-index", plane="build", action="ensure",
                resource="search_index", name="ontology",
                risk="remote_mutation", reversible=True, requires_approval=True,
                evidence=("schema_id", "document_count"),
            ),
            Operation(
                id="create-managed-knowledge-source", plane="build", action="create",
                resource="knowledge_source", name="managed-blob",
                risk="remote_mutation", reversible=True, requires_approval=True,
                evidence=("knowledge_source_id", "created_resources"),
            ),
            Operation(
                id="verify-managed-synchronization", plane="build", action="verify",
                resource="knowledge_source", name="managed-blob",
                risk="read_only", evidence=("document_count", "graph_document_count",
                                              "serving_state"),
            ),
        ])
    if spec.readers:
        operations.append(Operation(
            id="grant-readers", plane="build", action="grant", resource="role_assignment",
            name=f"{len(spec.readers)} reader(s)", risk="remote_mutation", reversible=True,
            requires_approval=True, evidence=("granted", "missing"),
        ))
    if decision and decision.capability != "verified_path":
        operations = [Operation(
            id="preflight-source-route", plane="build", action="inspect",
            resource="source_route", name=spec.source.source_id if spec.source else "legacy",
            evidence=("source_kind", "requested_outcome", "knowledge_source_kind",
                      "manifest_digest"),
        )]
    if ontology is None:
        warnings = ("graph capability disabled because ontology mode is none",)
    else:
        warnings = ()
    if spec.source is None and Path(spec.corpus_source).exists():
        from .executor import generation
        content_generation = generation(spec)
    else:
        content_generation = None
    blockers = []
    if decision:
        blockers.extend(decision.blocked_by)
    blockers.extend(target_blockers(spec))
    if spec.source_manifest and not spec.source_manifest.items:
        blockers.append("EMPTY_MANIFEST: source manifest has no eligible documents")
    if spec.source is not None and spec.source.kind is SourceKind.LOCAL_PATH and (
        spec.corpus_source and spec.source.reference != spec.corpus_source
    ):
        blockers.append("SOURCE_MISMATCH: local source differs from legacy corpus_source")
    if (spec.target.storage_resource_id or spec.target.openai_resource_id) and spec.source is None:
        blockers.append("TARGET_VERIFICATION_NOT_INTEGRATED: Build does not verify explicit Storage/OpenAI ARM identities")
    if spec.source_manifest and decision and decision.capability == "verified_path":
        if not all((spec.target.search_resource_id, spec.target.storage_resource_id,
                    spec.target.openai_resource_id)):
            blockers.append("TARGET_ID_REQUIRED: source graph builds need exact Search, Storage and OpenAI ARM IDs")
        if spec.source_manifest.transform_config_id != "identity" or any(
            item.transform_id is not None or item.transform_version is not None
            or item.materialized_blob_path is not None
            for item in spec.source_manifest.items
        ):
            blockers.append("SOURCE_TRANSFORM_UNSUPPORTED: only original identity bytes may be staged")
        if spec.source.kind not in {SourceKind.LOCAL_PATH, SourceKind.ZIP_ARCHIVE,
                                    SourceKind.BLOB_PREFIX}:
            blockers.append("UNSUPPORTED_GRAPH_ROUTE: source kind cannot be staged")
        if (spec.source.kind is SourceKind.BLOB_PREFIX
                and spec.source.resource_id.casefold() ==
                    (spec.target.storage_resource_id or "").casefold()
                and spec.source.container == spec.storage_container):
            from .executor import staging_prefix
            if staging_prefix(spec).startswith(spec.source.prefix):
                blockers.append("SOURCE_DESTINATION_OVERLAP: staging would write inside the caller-owned prefix")
    if spec.readers and not (ontology and spec.source_manifest
                             and spec.target.search_resource_id):
        blockers.append("READERS_UNSUPPORTED: reader grants need a managed source build "
                        "with --search-resource-id")
    if spec.agentic_retrieval and decision:
        blockers.append("KB_HANDOFF_NOT_IMPLEMENTED: agentic KB Build is not available")
    if spec.trial is not None and not ontology:
        blockers.append("TRIAL_NEEDS_ONTOLOGY: a trial build measures graph extraction; "
                        "choose --ontology owl_file or schema_org")
    blockers.extend(grounding_blockers(spec, ontology is not None))
    if ontology:
        evidence_error = probe_error(spec)
        if evidence_error:
            blockers.append(evidence_error)
        if not all((spec.embedding_deployment, spec.embedding_model, spec.embedding_dimensions,
                    spec.chat_deployment, spec.chat_model, spec.search_identity_resource_id)):
            blockers.append("managed graph needs explicit models, dimensions and Search identity")
        if not spec.build_journal:
            blockers.append("managed graph needs a durable build journal path")
        if not all((spec.search_sku, spec.target.location, spec.target.subscription_id, spec.target.resource_group,
                    spec.target.search_endpoint, spec.target.storage_endpoint,
                    spec.target.openai_endpoint)):
            blockers.append("managed graph needs explicit Search SKU, region, Storage and OpenAI targets")
    identity = {"spec": spec, "generation": content_generation}
    if spec.source is not None:
        bound_spec = asdict(spec)
        bound_spec.pop("readers")
        if spec.trial is None:
            bound_spec.pop("trial")
        if spec.grounding_index is None:
            bound_spec.pop("grounding_index")
        bound_spec["source"] = spec.source.source_id
        bound_spec["source_manifest"] = (
            spec.source_manifest.digest if spec.source_manifest else None
        )
        identity = {
            "spec": bound_spec, "generation": None,
            "ontology_schema_id": ontology.schema_id if ontology else None,
        }
    if ontology:
        from .managed_pipeline import extraction_settings
        identity["managed_extraction"] = extraction_settings(spec)
    if spec.readers:
        identity["readers"] = list(spec.readers)
    return Plan(
        plan_id=stable_id("build-plan", identity),
        operations=tuple(operations),
        warnings=warnings + ((
            f"{PREVIEW_ENTITLEMENT_UNVERIFIABLE} Explicit approval permits one exact-service "
            "journaled attempt; 400/403 or timeout must not be retried automatically.",
        ) if ontology and not blockers else ()) + ((
            f"Grants read access to {len(spec.readers)} "
            f"{'identity' if len(spec.readers) == 1 else 'identities'} on the new build "
            "(Search Index Data Reader on its content and graph indexes). The Build "
            "identity needs Microsoft.Authorization/roleAssignments/write for that.",
        ) if spec.readers else ()) + ((
            f"Grounding index {spec.grounding_index} is checked read-only when plan is given "
            "--search-endpoint, and again before apply; ekg-build never creates it.",
        ) if spec.grounding_index and not blockers else ()),
        blocked_by=tuple(blockers),
        route=decision,
        scope={**scope(spec, decision),
               "ontology_schema_id": ontology.schema_id if ontology else None,
               **({"trial": trial_scope(spec)} if spec.trial else {})}
        if decision else {},
        estimates=plan_estimates(spec) if ontology else {},
        grounding=grounding_block(spec) if ontology else {},
    )


def grounding_block(spec: BuildSpec) -> dict:
    """The exact graph_name the service will filter grounding rows on, with the next step."""
    if not spec.grounding_index or grounding.name_blocker(spec.grounding_index):
        return {}
    from .executor import index_names
    from .managed_pipeline import GROUNDING_CASCADE
    try:
        graph_name = index_names(spec)["knowledge_source"]
    except (ValueError, OSError):
        return {}
    return grounding.plan_block(spec.grounding_index, graph_name, GROUNDING_CASCADE)


def grounding_blockers(spec: BuildSpec, graph_extraction: bool) -> list[str]:
    """Offline checks on the optional grounding index; the live check runs separately."""
    name = spec.grounding_index
    if name is None:
        return []
    if not graph_extraction:
        return ["GROUNDING_REQUIRES_GRAPH_EXTRACTION: grounding_index needs an ontology; "
                "choose --ontology owl_file or schema_org"]
    invalid = grounding.name_blocker(name)
    if invalid:
        return [invalid]
    if spec.source is None and not Path(spec.corpus_source).exists():
        return []
    from .executor import index_names
    owned = index_names(spec)
    source = owned["knowledge_source"]
    collision = grounding.collision_blocker(
        name, (*owned.values(), f"{source}-index", f"{source}-graph-index"))
    return [collision] if collision else []


def trial_scope(spec: BuildSpec) -> dict:
    from .executor import staging_prefix
    trial = spec.trial
    return {"sample_documents": trial.size, "corpus_documents": trial.corpus_documents,
            "corpus_digest": trial.corpus_digest, "selection": trial.selection,
            "staging_prefix": staging_prefix(spec),
            "source_ids": [item.source_id for item in spec.source_manifest.items]}


def verification_blockers(desired: Plan) -> tuple[str, ...]:
    if desired.route is not None:
        return desired.blocked_by
    return tuple(reason for reason in desired.blocked_by
                 if reason.startswith(("TARGET_", "SOURCE_")))
