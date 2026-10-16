from ekg_core.models import BuildSpec, OntologyMode
from ekg_core.ontology import load_ontology

from .managed_pipeline import (
    EDGE_FIELDS, generated, knowledge_source, ontology_index, ontology_rows,
    search_api_version, uses_inline_jsonld,
)
from .executor import (
    BuildError, _identity_readback_matches, _read_attempt_journal, _source_record,
    _sync_status, corpus_files, generation, hash_json, index_names, plan, source_provenance,
    verification_blockers, _raise_incomplete, staging_prefix,
)

def _coverage_fields(executor, spec, name, resources, indexes) -> dict:
    from . import grounding_report
    return grounding_report.attach({}, grounding_report.measure(
        executor.adapter, spec, name, resources["graphIndex"], indexes["graph"]))


def _verify_source_journal(executor, spec):
        if spec.source_manifest is not None:
            record, _ = _read_attempt_journal(spec)
            expected = _source_record(spec, "attempt_requested")
            if any(record.get(key) != expected[key] for key in (
                "version", "run_id", "plan_id", "scope", "generation",
                "knowledge_source", "create_request_hash",
            )) or record.get("state") not in {
                "attempt_requested", "indexing", "synchronizing", "failed", "verified",
            }:
                raise BuildError("source journal differs from approved run identity")
            executor._source_targets(spec)
            return record
        return None
def _verify_document_index(executor, spec, names):
            content = executor.adapter.get_index(names["content"])
            if not content or (spec.vector_retrieval and not content.get("vectorSearch")):
                raise BuildError("content index or vector configuration is missing")
            count = executor.adapter.count(names["content"])
            if count < len(corpus_files(spec.corpus_source)):
                raise BuildError("content index count is smaller than corpus")
            return {"status": "verified", "counts": {"content": count},
                    "indexes": {"content": content},
                    "created_resources": {"index": names["content"]}}
def _verify_managed(executor, spec, names, record):
        ontology = load_ontology(
            spec.ontology_mode, path=spec.ontology_path,
            schema_org_profile=spec.schema_org_profile,
            schema_org_version=spec.schema_org_version,
            resolve_imports=spec.resolve_imports,
        )
        if ontology is None:
            raise BuildError("managed graph requires an ontology")
        name = names["knowledge_source"]
        live = executor.adapter.get_knowledge_source(name)
        if not live or live.get("name") != name or live.get("kind") != "azureBlob":
            raise BuildError("managed Knowledge Source is missing or incompatible")
        ingestion = (live.get("azureBlobParameters") or {}).get("ingestionParameters") or {}
        graph = ingestion.get("graphExtraction") or {}
        ontology_binding = graph.get("ontology") or {}
        expected_ontology_binding = (
            {"inlineJsonLd": ontology.inline_jsonld}
            if uses_inline_jsonld(spec) else {"indexName": names["ontology"]}
        )
        if graph.get("graphName") != name or ontology_binding != expected_ontology_binding:
            raise BuildError("managed Knowledge Source graph/ontology binding differs")
        if spec.grounding_index and (((graph.get("grounding") or {}).get("index") or {}).get(
                "indexName") != spec.grounding_index):
            raise BuildError("managed Knowledge Source grounding index differs")
        resources = generated(live)
        for key, kind in (("datasource", "datasources"),
                          ("skillset", "skillsets"),
                          ("indexer", "indexers")):
            resource = executor.adapter.get_resource(kind, resources[key])
            if not resource or resource.get("name") != resources[key]:
                raise BuildError(f"managed generated {key} is missing")
        indexes = {"content": executor.adapter.get_index(resources["index"]),
                   "graph": executor.adapter.get_index(resources["graphIndex"])}
        if not uses_inline_jsonld(spec):
            indexes["ontology"] = executor.adapter.get_index(names["ontology"])
        if any(value is None for value in indexes.values()):
            raise BuildError("managed Knowledge Source generated indexes are missing")
        if not uses_inline_jsonld(spec):
            ontology_schema = indexes["ontology"] or {}
            profile = ontology_schema.get("graphProfile")
            if not isinstance(profile, dict):
                raise BuildError("ontology edge-list graph profile is missing")
            mappings = profile.get("fields")
            if (profile.get("kind") != "edgeList" or not isinstance(mappings, dict)
                    or any(mappings.get(key) != value for key, value in EDGE_FIELDS.items())
                    or any(key not in EDGE_FIELDS and
                           (key != "sourceDocumentIdField" or value is not None)
                           for key, value in mappings.items())):
                raise BuildError("ontology edge-list graph profile is missing")
            expected = ontology_index(names["ontology"])
            actual_fields = {field.get("name"): field for field in ontology_schema.get("fields", [])
                             if isinstance(field, dict)}
            if any(
                actual_fields.get(field["name"], {}).get("type") != field["type"]
                for field in expected["fields"]
            ):
                raise BuildError("ontology index field types differ from the managed contract")
        content = indexes["content"] or {}
        content_fields = {
            item.get("name"): item for item in content.get("fields", [])
            if isinstance(item, dict)
        }
        if not content.get("vectorSearch") or not {
            "uid", "snippet", "snippet_vector", "snippet_parent_id", "blob_url"
        }.issubset(content_fields):
            raise BuildError("managed content schema lacks required retrieval fields")
        vector_field = content_fields["snippet_vector"]
        if (vector_field.get("type") != "Collection(Edm.Single)" or
                vector_field.get("dimensions") != spec.embedding_dimensions):
            raise BuildError("managed content vector dimensions differ from the configured model")
        if (indexes["graph"] or {}).get("graphProfile", {}).get("kind") != "edgeList":
            raise BuildError("managed graph index lacks an edge-list graph profile")
        _sync_status(executor.adapter.knowledge_source_status(name)) or (
            _raise_incomplete()
        )
        counts = {"content": executor.adapter.count(resources["index"]),
                  "graph": executor.adapter.count(resources["graphIndex"])}
        if not uses_inline_jsonld(spec):
            counts["ontology"] = executor.adapter.count(names["ontology"])
            if counts["ontology"] != len(ontology_rows(ontology, name)):
                raise BuildError("managed ontology row count differs")
        source_count = spec.source_manifest.document_count if spec.source_manifest else len(
            corpus_files(spec.corpus_source)
        )
        if counts["content"] < source_count or counts["graph"] == 0:
            raise BuildError("managed content or graph index has insufficient documents")
        evidence_sample = None
        if spec.graph_retrieval and ontology.edge_types:
            for domain, predicate, range_name in ontology.edge_types:
                gql = (f"MATCH (s:`{domain}`)-[r:`{predicate}`]->"
                       f"(o:`{range_name}`) RETURN r LIMIT 1")
                result = executor.adapter.graph_search(resources["graphIndex"], gql)
                diagnostics = result.get("@search.graphDiagnostics") or []
                if any(item.get("severity") == "error" for item in diagnostics):
                    raise BuildError("native graph probe returned an error diagnostic")
                for row in result["value"]:
                    proof = row.get("@search.graphProvenance") or {}
                    if any(isinstance(item, dict) and item.get("chunkId")
                           for item in proof.get("evidence") or []):
                        evidence_sample = proof["evidence"]
                        break
                if evidence_sample is not None:
                    break
            if evidence_sample is None:
                raise BuildError("managed graph has no ontology edge with source provenance")
        if spec.source_manifest is not None:
            mapping = source_provenance(spec)
            binding = live.get("azureBlobParameters") or {}
            expected_definition = knowledge_source(
                spec, name=name, ontology_name=names.get("ontology"),
                graph_name=name, prefix=staging_prefix(spec), ontology=ontology,
            )
            expected_binding = expected_definition["azureBlobParameters"]
            expected_identity = expected_binding["ingestionParameters"]["identity"]
            observed_ingestion = binding.get("ingestionParameters")
            if not isinstance(observed_ingestion, dict):
                raise BuildError("SOURCE_MAPPING_UNVERIFIED: managed staging destination differs")
            identities = [(observed_ingestion.get("identity"), expected_identity)]
            for model_name in ("embeddingModel", "chatCompletionModel"):
                model = observed_ingestion.get(model_name)
                expected_model = expected_binding["ingestionParameters"][model_name]
                parameters = model.get("azureOpenAIParameters") if isinstance(model, dict) else None
                expected_parameters = expected_model["azureOpenAIParameters"]
                if (not isinstance(model, dict) or model.get("kind") != expected_model["kind"]
                        or not isinstance(parameters, dict)
                        or any(parameters.get(key) != expected_parameters[key]
                               for key in ("resourceUri", "deploymentId", "modelName"))):
                    raise BuildError("SOURCE_MAPPING_UNVERIFIED: managed model binding differs")
                identities.append((parameters.get("authIdentity"),
                                   expected_parameters["authIdentity"]))
            if any(binding.get(key) != expected_binding[key] for key in (
                "containerName", "folderPath",
            )) or any(not _identity_readback_matches(observed, approved)
                      for observed, approved in identities):
                raise BuildError("SOURCE_MAPPING_UNVERIFIED: managed staging destination differs")
            receipt = record.get("create_receipt")
            if (record.get("create_request_hash") != hash_json(expected_definition)
                    or not isinstance(receipt, dict)
                    or set(receipt) != {"name", "kind", "etag"}
                    or receipt.get("name") != name or receipt.get("kind") != "azureBlob"
                    or not isinstance(receipt.get("etag"), str) or not receipt["etag"].strip()
                    or live.get("@odata.etag") != receipt["etag"]):
                raise BuildError("SOURCE_MAPPING_UNVERIFIED: exact create receipt or live ETag is missing")
            observed_connection = binding.get("connectionString")
            if (observed_connection != expected_binding["connectionString"]
                    and (not isinstance(observed_connection, str)
                         or observed_connection.casefold() != "<redacted>")):
                raise BuildError("SOURCE_MAPPING_UNVERIFIED: managed staging destination differs")
            if not callable(getattr(executor.adapter, "search_page", None)):
                raise BuildError("SOURCE_PAGINATION_REQUIRED: exhaustive readback is unavailable")
            seen_urls: set[str] = set()
            seen_chunks: set[str] = set()
            offset = 0
            while offset < counts["content"]:
                size = min(1000, counts["content"] - offset)
                documents = executor.adapter.search_page(resources["index"], skip=offset, top=size)
                if (not isinstance(documents, list) or not documents
                        or len(documents) > size):
                    raise BuildError("SOURCE_MAPPING_UNVERIFIED: generated content page is incomplete")
                for document in documents:
                    if not isinstance(document, dict):
                        raise BuildError("SOURCE_MAPPING_UNVERIFIED: generated chunk is malformed")
                    url, uid = document.get("blob_url"), document.get("uid")
                    if not isinstance(url, str) or url not in mapping or not isinstance(uid, str) \
                            or not uid or uid in seen_chunks:
                        raise BuildError("SOURCE_MAPPING_UNVERIFIED: chunk lacks an exact staged URI or ID")
                    seen_urls.add(url)
                    seen_chunks.add(uid)
                offset += len(documents)
            if seen_urls != set(mapping) or any(
                not isinstance(item, dict) or item.get("chunkId") not in seen_chunks
                for item in (evidence_sample or [])
            ):
                raise BuildError("SOURCE_MAPPING_UNVERIFIED: original sources or graph chunks are unmatched")
        return {"status": "verified", "counts": counts, "indexes": indexes,
                "created_resources": resources, "knowledge_source": name,
                "graph_provenance_sample_count": len(evidence_sample or []),
                **_coverage_fields(executor, spec, name, resources, indexes),
                **({"source_provenance": mapping, "manifest_digest": spec.source_manifest.digest}
                   if spec.source_manifest else {})}

def verify(executor, spec: BuildSpec) -> dict:
        desired = plan(spec)
        blockers = verification_blockers(desired)
        if blockers:
            raise BuildError("; ".join(blockers))
        if (spec.ontology_mode is not OntologyMode.NONE
                and getattr(executor.adapter, "search_api_version", search_api_version(spec))
                != search_api_version(spec)):
            raise BuildError(f"managed graph requires Search {search_api_version(spec)}")
        record = _verify_source_journal(executor, spec)
        names = index_names(spec)
        if spec.ontology_mode is OntologyMode.NONE:
            return _verify_document_index(executor, spec, names)
        return _verify_managed(executor, spec, names, record)
