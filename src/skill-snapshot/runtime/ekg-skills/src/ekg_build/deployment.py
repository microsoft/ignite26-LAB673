from __future__ import annotations

from ekg_core.models import BuildSpec, DeploymentDescriptor, OntologyMode, stable_id
from ekg_core.ontology import load_ontology
from .executor import (BuildError, BuildExecutor, _verify_managed_target, generation,
                       hash_json, index_names, source_provenance)
from .managed_pipeline import search_api_version
from .planner import plan, verification_blockers
from .status import build_status
from .target_validation import graph_input_error


def descriptor(spec: BuildSpec, *, endpoints: dict[str, str] | None = None,
               verified: dict | None = None) -> DeploymentDescriptor:
    blockers = verification_blockers(plan(spec))
    if blockers:
        raise BuildError("; ".join(blockers))
    if spec.ontology_mode is not OntologyMode.NONE and verified is not None:
        reason = graph_input_error(spec)
        if reason:
            raise BuildError(reason)
    provenance = None
    if spec.source_manifest is not None:
        if build_status(spec)["code"] != "JOURNAL_VERIFIED":
            raise BuildError("SOURCE_MAPPING_UNVERIFIED: approved source run is not journaled as verified")
        if not verified or verified.get("status") != "verified" or (
            verified.get("manifest_digest") != spec.source_manifest.digest
        ) or verified.get("source_provenance") != source_provenance(spec):
            raise BuildError("SOURCE_MAPPING_UNVERIFIED: publish needs exact verified provenance")
        provenance = {
            "manifest_digest": spec.source_manifest.digest,
            "staged": verified["source_provenance"],
        }
        provenance["mapping_digest"] = hash_json(provenance)
    ontology = load_ontology(
        spec.ontology_mode,
        path=spec.ontology_path,
        schema_org_profile=spec.schema_org_profile,
        schema_org_version=spec.schema_org_version,
        resolve_imports=spec.resolve_imports,
    )
    ontology_data = None
    if ontology:
        ontology_data = {
            "mode": ontology.source_kind,
            "schema_id": ontology.schema_id,
            "source_reference": ontology.source_reference,
            "edge_types": [list(edge) for edge in ontology.edge_types],
        }
    resolved = dict(endpoints or {})
    if spec.target.search_endpoint:
        resolved["search"] = spec.target.search_endpoint
    if spec.source_manifest is not None:
        if not spec.target.storage_endpoint:
            raise BuildError("SOURCE_MAPPING_UNVERIFIED: destination endpoint is missing")
        resolved["storage"] = spec.target.storage_endpoint
        resolved["source_manifest_digest"] = spec.source_manifest.digest
    if spec.target.openai_endpoint:
        resolved["openai"] = spec.target.openai_endpoint
    if spec.embedding_deployment:
        resolved["embedding_deployment"] = spec.embedding_deployment
    if spec.grounding_index:
        resolved["grounding_index"] = spec.grounding_index
    if ontology and verified:
        resources = verified["created_resources"]
        resolved["content_index"] = resources["index"]
        resolved["graph_index"] = resources["graphIndex"]
        resolved["knowledge_source"] = verified["knowledge_source"]
        resolved["search_api_version"] = search_api_version(spec)
    elif not ontology:
        try:
            resolved["content_index"] = index_names(spec)["content"]
        except ValueError:
            pass
    return DeploymentDescriptor(
        deployment_id=stable_id("deployment", spec),
        build_id=(f"build-{generation(spec)}" if "content_index" in resolved
                  else stable_id("build", spec)),
        ontology=ontology_data,
        capabilities={
            "document_retrieval": spec.vector_retrieval and
                                  (not ontology or verified is not None),
            "graph_retrieval": bool(
                ontology and ontology.edge_types and spec.graph_retrieval and verified
            ),
            "agentic_retrieval": False,
        },
        endpoints=resolved,
        source_provenance=provenance,
    )


def publish(spec: BuildSpec, executor: BuildExecutor) -> DeploymentDescriptor:
    """Only publish a serving descriptor after read-only remote verification."""
    if spec.ontology_mode is not OntologyMode.NONE and spec.source_manifest is None:
        _verify_managed_target(spec, executor.adapter)
    verified = executor.verify(spec)
    executor.last_verified = verified
    published = descriptor(spec, verified=verified)
    if spec.readers:
        from . import readers
        created = verified["created_resources"]
        missing = readers.missing(executor.adapter, spec.target.search_resource_id,
                                  [created["index"], created["graphIndex"]], spec.readers,
                                  spec.tenant_id)
        if missing:
            raise BuildError(
                f"READERS_MISSING: {len(missing)} reader grant(s) are missing on the new "
                "generation, so those consumers would get HTTP 403. Run these, then publish "
                "again: " + "; ".join(missing))
    return published
