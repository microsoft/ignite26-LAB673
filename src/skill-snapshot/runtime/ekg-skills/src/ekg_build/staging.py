import json, time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any
from ekg_core.execution import ApplyResult
from ekg_core.models import BuildSpec, Event, OntologyMode, stable_id
from ekg_core.ontology import load_ontology
from ekg_core.telemetry import TelemetryRecorder, adapter_http_stats
from .adapters import SearchRequestError
from .managed_pipeline import (generated, grounding_live_blocker,
                               knowledge_source, ontology_index, ontology_rows,
                               search_api_version, uses_inline_jsonld)
from .executor import (
    BuildError, _await_index_count, _complete_journal, _create_source_journal, _document_schema, _failure_detail,
    _journal, _read_attempt_journal, _source_bytes, _source_record, _advance_source_journal,
    _verify_managed_target, _sync_status, _synchronization_event, corpus_files, generation, hash_json,
    index_names, plan, source_provenance, staging_prefix,
)
def _source_inputs(executor, spec):
        if plan(spec).blocked_by:
            raise BuildError("; ".join(plan(spec).blocked_by))
        if not callable(getattr(executor.adapter, "search_page", None)):
            raise BuildError("SOURCE_PAGINATION_REQUIRED: exhaustive generated content readback is unavailable")
        service = executor._source_targets(spec)
        if getattr(executor.adapter, "search_api_version", search_api_version(spec)) != search_api_version(spec):
            raise BuildError(f"managed graph requires exact Search {search_api_version(spec)} API version")
        names = index_names(spec)
        prefix = staging_prefix(spec)
        mapping = source_provenance(spec)
        ontology = load_ontology(
            spec.ontology_mode, path=spec.ontology_path,
            schema_org_profile=spec.schema_org_profile,
            schema_org_version=spec.schema_org_version,
            resolve_imports=spec.resolve_imports,
        )
        if ontology is None:
            raise BuildError("managed graph requires an ontology")
        rows = [] if uses_inline_jsonld(spec) else ontology_rows(
            ontology, names["knowledge_source"])
        definition = knowledge_source(
            spec, name=names["knowledge_source"], ontology_name=names.get("ontology"),
            graph_name=names["knowledge_source"], prefix=prefix, ontology=ontology,
        )
        if Path(spec.build_journal or "").exists():
            raise BuildError("managed build journal exists; reconcile the recorded attempt, or "
                             "plan another build with a new --build-journal path")
        statistics = executor.adapter.service_statistics()
        capacity = (statistics.get("counters") or {}).get("indexesCount") or {}
        required_index_headroom = 2 if uses_inline_jsonld(spec) else 3
        if not isinstance(capacity.get("usage"), int) or not isinstance(
            capacity.get("quota"), int
        ) or capacity["quota"] - capacity["usage"] < required_index_headroom:
            raise BuildError(
                f"Search index headroom is unknown or less than {required_index_headroom} indexes")
        expected_indexes = [f"{names['knowledge_source']}-index",
                            f"{names['knowledge_source']}-graph-index"]
        if not uses_inline_jsonld(spec):
            expected_indexes.append(names["ontology"])
        if any(executor.adapter.get_index(name) is not None for name in expected_indexes) \
                or executor.adapter.get_knowledge_source(names["knowledge_source"]) is not None:
            raise BuildError("managed generation already exists; refusing to overwrite")
        # The final complete in-memory snapshot is checked immediately before the first write.
        contents = _source_bytes(spec, executor.blob_reader)
        if len(contents) != len(mapping):
            raise BuildError("SOURCE_DRIFT: source byte count differs from approved manifest")
        original = _create_source_journal(spec)
        return service, names, prefix, mapping, ontology, rows, definition, contents, original
def stage_all(adapter, container: str, items, *, concurrency: int = 16) -> int:
    """Stage (blob name, bytes) pairs with bounded concurrency; return the count staged.

    On the first failure no new uploads start; in-flight ones finish, and the error says
    how many were staged. A rerun re-stages the same bytes idempotently.
    """
    items = list(items)
    if concurrency < 1:
        raise BuildError("upload concurrency must be at least 1")
    staged, failure = 0, None
    with ThreadPoolExecutor(max_workers=min(concurrency, max(1, len(items)))) as pool:
        pending = iter(items)
        running = set()

        def submit() -> bool:
            item = next(pending, None)
            if item is None:
                return False
            running.add(pool.submit(adapter.stage, container, item[0], item[1]))
            return True

        for _ in range(concurrency):
            if not submit():
                break
        while running:
            done, _ = wait(running, return_when=FIRST_COMPLETED)
            for future in done:
                running.discard(future)
                error = future.exception()
                if error is None:
                    staged += 1
                elif failure is None:
                    failure = error
                if failure is None:
                    submit()
    if failure is not None:
        status = getattr(failure, "status", None)
        cause = type(failure).__name__ + (f" HTTP {status}" if isinstance(status, int) else "")
        # The cause's text can carry request details; name only its type and status.
        raise BuildError(f"STAGING_PARTIAL: {staged} of {len(items)} document(s) staged before "
                         f"an upload failed ({cause}); plan another build with a new "
                         "--build-journal path") from failure
    return staged


def _stage_source(executor, spec, mapping, contents, original, timings, events, recorder):
            started = time.perf_counter()
            with recorder.span("stage") as span:
                executor.adapter.ensure_container(spec.storage_container)
                names = []
                for (url, _), data in zip(mapping.items(), contents):
                    name = url.removeprefix(f"{spec.target.storage_endpoint}/{spec.storage_container}/")
                    if name == url:
                        raise BuildError("SOURCE_MAPPING_AMBIGUOUS: staged destination is not exact")
                    names.append((name, data))
                stage_all(executor.adapter, spec.storage_container, names,
                          concurrency=executor.upload_concurrency)
                span["counts"]["documents"] = len(contents)
                span["counts"]["upload_concurrency"] = executor.upload_concurrency
                span["bytes"] = sum(len(data) for data in contents)
            timings["stage_ms"] = round((time.perf_counter() - started) * 1000, 3)
            original = _advance_source_journal(
                spec, original, state="indexing",
                counts={"source": len(contents), "staged": len(contents)}, timings_ms=timings,
                telemetry=recorder.events,
            )
            events.append(Event("stage-corpus", "verified", "approved source bytes staged", {
                "source_count": len(contents), "uploaded_count": len(contents),
                "latency_ms": timings["stage_ms"], "evidence_origin": "approved_source_snapshot",
            }))
            return original
def _index_source_ontology(executor, spec, names, ontology, rows, contents, original, timings, events, recorder):
            if uses_inline_jsonld(spec):
                return _advance_source_journal(
                    spec, original, state="synchronizing",
                    counts={"source": len(contents), "staged": len(contents)},
                    timings_ms=timings, telemetry=recorder.events,
                )
            started = time.perf_counter()
            schema = ontology_index(names["ontology"])
            with recorder.span("ontology_index") as span:
                executor.adapter.create_index(schema)
                executor.adapter.upload(names["ontology"], rows)
                _await_index_count(executor.adapter, names["ontology"], len(rows))
                span["counts"]["rows"] = len(rows)
            timings["ontology_ms"] = round((time.perf_counter() - started) * 1000, 3)
            original = _advance_source_journal(
                spec, original, state="synchronizing",
                counts={"source": len(contents), "staged": len(contents),
                        "ontology": len(rows)}, timings_ms=timings,
                telemetry=recorder.events,
            )
            events.append(Event("ensure-ontology-index", "verified", "ontology indexed", {
                "schema_id": ontology.schema_id, "document_count": len(rows),
                "schema_hash": hash_json(schema), "latency_ms": timings["ontology_ms"],
            }))
            return original
def _grant_readers(executor, spec, resources, original, recorder):
    """Grant carried-forward readers once the generated indexes exist. A failure is
    journaled rather than raised: the build is still good, and publish names the fix."""
    from . import readers
    indexes = [resources["index"], resources["graphIndex"]]
    with recorder.span("grant_readers", resource="role_assignment") as span:
        try:
            grants = readers.grant(executor.adapter, spec.target.search_resource_id, indexes,
                                   spec.readers, spec.tenant_id)
        except RuntimeError as error:
            grants = {"readers": len(spec.readers), "indexes": indexes, "granted": 0,
                      "error": str(error)[:200]}
        span["counts"]["granted"] = grants["granted"]
    return _advance_source_journal(spec, original, reader_grants=grants)


def _create_source_knowledge_source(executor, spec, names, prefix, definition, original, timings, events, recorder):
            started = time.perf_counter()
            with recorder.span("create_knowledge_source"):
                receipt = executor.adapter.create_knowledge_source(definition)
                if (not isinstance(receipt, dict)
                        or receipt.get("name") != names["knowledge_source"]
                        or receipt.get("kind") != "azureBlob"
                        or not isinstance(receipt.get("etag"), str)
                        or not receipt["etag"].strip()):
                    raise BuildError("SOURCE_MAPPING_UNVERIFIED: Knowledge Source create receipt is missing")
                original = _advance_source_journal(
                    spec, original, create_receipt={
                        "name": receipt["name"], "kind": receipt["kind"], "etag": receipt["etag"],
                    },
                )
                live = executor.adapter.get_knowledge_source(names["knowledge_source"])
                if not live or live.get("kind") != "azureBlob" or live.get("name") != names["knowledge_source"]:
                    raise BuildError("managed Knowledge Source could not be verified")
                resources = generated(live)
            create_ms = round((time.perf_counter() - started) * 1000, 3)
            if spec.readers:
                original = _grant_readers(executor, spec, resources, original, recorder)
            original = _advance_source_journal(spec, original, telemetry=recorder.events)
            events.append(Event("create-managed-knowledge-source", "verified",
                                "managed Knowledge Source accepted; service-side synchronization started", {
                                    "knowledge_source_id": names["knowledge_source"],
                                    "created_resources": resources, "latency_ms": create_ms,
                                    "evidence_origin": "knowledge_source_create_receipt",
                                }))
            submitted = Event("build", "submitted", "SYNCHRONIZATION_STARTED", {
                "run_id": f"build-{prefix}", "plan_id": plan(spec).plan_id,
                "phase": "synchronizing", "timings_ms": {**timings, "create_ms": create_ms},
                "evidence_origin": "knowledge_source_create_receipt",
                "uncertainty": ["Generated indexes and graph are unverified until reconcile succeeds."],
                "next_action": ("Optionally watch with `ekg-build progress`; run `ekg-build reconcile` "
                                "read-only after synchronization finishes. Do not rerun apply."),
            })
            return original, submitted, started
def _finish_source_apply(executor, spec, names, prefix, service, contents, original, submitted, timings, events, recorder, started_total, started):
            with recorder.span("wait_for_synchronization") as span:
                for polls in range(1, 61):
                    last = _sync_status(executor.adapter.knowledge_source_status(names["knowledge_source"]))
                    if last:
                        break
                    time.sleep(5)
                span["counts"]["polls"] = polls
            if not last:
                original = _advance_source_journal(spec, original, telemetry=recorder.events)
                return original, ApplyResult(tuple(events + [submitted]), True)
            recorder.add(_synchronization_event(last))
            timings["synchronization_ms"] = round((time.perf_counter() - started) * 1000, 3)
            started = time.perf_counter()
            with recorder.span("verify"):
                verified = executor.verify(spec)
            timings["verify_ms"] = round((time.perf_counter() - started) * 1000, 3)
            timings["time_to_build_ms"] = round((time.perf_counter() - started_total) * 1000, 3)
            original = _advance_source_journal(
                spec, original, state="verified",
                counts={"source": len(contents), "staged": len(contents), **verified["counts"]},
                timings_ms=timings, telemetry=recorder.events,
            )
            events.append(Event("verify-managed-synchronization", "verified",
                                "generated indexes, graph and original provenance verified", {
                                    "document_count": verified["counts"]["content"],
                                    "graph_document_count": verified["counts"]["graph"],
                                    "serving_state": "verified", "latency_ms": timings["verify_ms"],
                                }))
            events.append(Event("build", "completed", "approved source generation verified", {
                "run_id": f"build-{prefix}", "plan_id": plan(spec).plan_id,
                "counts": {"source": len(contents), "staged": len(contents), **verified["counts"]},
                "phase_latency_ms": timings, "evidence_origin": "read_only_generated_index_checks",
                "next_action": "Publish after fresh read-only verification of the exact generation.",
                "target_verification": service,
            }))
            return original, ApplyResult(tuple(events), True)
def _apply_source(executor, spec: BuildSpec, *, wait_for_sync: bool = True) -> ApplyResult:
        service, names, prefix, mapping, ontology, rows, definition, contents, original = _source_inputs(executor, spec)
        events: list[Event] = []
        timings: dict[str, float] = {}
        recorder = TelemetryRecorder("build", adapter_http_stats(executor.adapter))
        started_total = time.perf_counter()
        phase = "staging"
        try:
            original = _stage_source(executor, spec, mapping, contents, original, timings, events, recorder)
            phase = "indexing"
            original = _index_source_ontology(executor, spec, names, ontology, rows, contents, original, timings, events, recorder)
            phase = "synchronizing"
            original, submitted, started = _create_source_knowledge_source(executor, spec, names, prefix, definition, original, timings, events, recorder)
            if not wait_for_sync:
                return ApplyResult(tuple(events + [submitted]), True)
            original, result = _finish_source_apply(executor, spec, names, prefix, service, contents, original, submitted, timings, events, recorder, started_total, started)
            return result
        except Exception as error:
            code = ("SOURCE_DRIFT" if "SOURCE_DRIFT" in str(error) else
                    "REMOTE_OUTCOME_UNVERIFIED" if phase == "synchronizing" else
                    "BUILD_ATTEMPT_FAILED")
            timings["time_to_build_ms"] = round((time.perf_counter() - started_total) * 1000, 3)
            _advance_source_journal(spec, original, state="failed", error_code=code,
                                    timings_ms=timings, telemetry=recorder.events)
            events.append(Event("build", "failed", code, {
                "run_id": f"build-{prefix}", "phase": phase, "timings_ms": timings,
                **_failure_detail(error),
                "evidence_origin": "local_build_journal",
                "uncertainty": ["Remote mutation may have completed; no automatic retry is safe."],
                "next_action": "Reconcile this exact attempt read-only; never retry its writes automatically.",
            }))
            return ApplyResult(tuple(events), False)
def _apply_managed(executor, spec: BuildSpec) -> ApplyResult:
        if plan(spec).blocked_by:
            raise BuildError("; ".join(plan(spec).blocked_by))
        service_evidence = _verify_managed_target(spec, executor.adapter)
        version = getattr(executor.adapter, "search_api_version", search_api_version(spec))
        if version != search_api_version(spec):
            raise BuildError(f"managed graph requires Search {search_api_version(spec)}")
        grounding_blocker = grounding_live_blocker(executor.adapter, spec)
        if grounding_blocker:
            raise BuildError(grounding_blocker)
        names = index_names(spec)
        ontology = load_ontology(
            spec.ontology_mode, path=spec.ontology_path,
            schema_org_profile=spec.schema_org_profile,
            schema_org_version=spec.schema_org_version,
            resolve_imports=spec.resolve_imports,
        )
        if ontology is None:
            raise BuildError("managed graph requires an ontology")
        prefix = staging_prefix(spec)
        graph_name = names["knowledge_source"]
        rows = [] if uses_inline_jsonld(spec) else ontology_rows(ontology, graph_name)
        definition = knowledge_source(
            spec, name=graph_name, ontology_name=names.get("ontology"),
            graph_name=graph_name, prefix=prefix, ontology=ontology,
        )
        if Path(spec.build_journal or "").exists():
            raise BuildError("managed build journal exists; reconcile the recorded attempt, or "
                             "plan another build with a new --build-journal path")
        try:
            statistics = executor.adapter.service_statistics()
        except SearchRequestError as error:
            if error.status == 400:
                raise BuildError(
                    f"Search does not accept required {search_api_version(spec)} API") from error
            raise
        counters = statistics.get("counters") or {}
        capacity = counters.get("indexesCount") or {}
        required_index_headroom = 2 if uses_inline_jsonld(spec) else 3
        if not isinstance(capacity.get("usage"), int) or not isinstance(
            capacity.get("quota"), int
        ) or capacity["quota"] - capacity["usage"] < required_index_headroom:
            raise BuildError(
                f"Search index headroom is unknown or less than {required_index_headroom} indexes")
        expected_indexes = [f"{graph_name}-index", f"{graph_name}-graph-index"]
        if not uses_inline_jsonld(spec):
            expected_indexes.append(names["ontology"])
        if (any(executor.adapter.get_index(index_name) is not None
                for index_name in expected_indexes) or
                executor.adapter.get_knowledge_source(graph_name) is not None):
            raise BuildError("managed generation already exists; refusing to overwrite")
        timings: dict[str, float] = {}
        events: list[Event] = []
        started_total = time.perf_counter()
        original = _journal(spec, {"generation": prefix, "knowledge_source": graph_name,
                                   "plan_id": plan(spec).plan_id,
                                   "search_resource_id": service_evidence["resource_id"],
                                   "tenant_id": spec.tenant_id,
                                   "state": "attempt_requested"})
        try:
            started = time.perf_counter()
            files = corpus_files(spec.corpus_source)
            executor.adapter.ensure_container(spec.storage_container)
            stage_all(executor.adapter, spec.storage_container,
                      [(f"{prefix}/{name}", data) for name, data in files],
                      concurrency=executor.upload_concurrency)
            timings["stage_ms"] = round((time.perf_counter() - started) * 1000, 3)
            events.append(Event("stage-corpus", "verified", "corpus staged", {
                "source_count": len(files), "uploaded_count": len(files),
                "latency_ms": timings["stage_ms"],
            }))
            started = time.perf_counter()
            if not uses_inline_jsonld(spec):
                schema = ontology_index(names["ontology"])
                executor.adapter.create_index(schema)
                executor.adapter.upload(names["ontology"], rows)
                _await_index_count(executor.adapter, names["ontology"], len(rows))
                timings["ontology_ms"] = round((time.perf_counter() - started) * 1000, 3)
                events.append(Event("ensure-ontology-index", "verified", "ontology indexed", {
                    "schema_id": ontology.schema_id, "document_count": len(rows),
                    "schema_hash": hash_json(schema), "latency_ms": timings["ontology_ms"],
                }))
            started = time.perf_counter()
            try:
                executor.adapter.create_knowledge_source(definition)
            except SearchRequestError as error:
                if error.status in {400, 403}:
                    raise BuildError(
                        f"Search rejected the managed Knowledge Source request (HTTP {error.status}); "
                        "inspect the API version, request contract and model/identity configuration"
                    ) from error
                raise
            timings["create_ms"] = round((time.perf_counter() - started) * 1000, 3)
            live = executor.adapter.get_knowledge_source(graph_name)
            if not live or live.get("name") != graph_name or live.get("kind") != "azureBlob":
                raise BuildError("managed Knowledge Source could not be verified after creation")
            resources = generated(live)
            events.append(Event("create-managed-knowledge-source", "verified",
                                "managed Knowledge Source created", {
                                    "knowledge_source_id": graph_name,
                                    "created_resources": resources,
                                    "latency_ms": timings["create_ms"],
                                }))
            started = time.perf_counter()
            for _ in range(60):
                state = _sync_status(executor.adapter.knowledge_source_status(graph_name))
                if state is not None:
                    break
                time.sleep(5)
            else:
                raise BuildError("managed synchronization did not finish within five minutes")
            timings["synchronization_ms"] = round((time.perf_counter() - started) * 1000, 3)
            started = time.perf_counter()
            verified = executor.verify(spec)
            timings["verify_ms"] = round((time.perf_counter() - started) * 1000, 3)
            evidence = {
                "document_count": verified["counts"]["content"],
                **({"ontology_document_count": len(rows)}
                   if not uses_inline_jsonld(spec) else {}),
                "graph_document_count": verified["counts"]["graph"],
                "graph_provenance_sample_count": verified["graph_provenance_sample_count"],
                "edge_count": None,
                "schema_id": ontology.schema_id,
                "schema_hash": hash_json(verified["indexes"]["graph"]),
                "phase_latency_ms": timings,
                "time_to_build_ms": round((time.perf_counter() - started_total) * 1000, 3),
                "indexes": verified["created_resources"],
                "knowledge_source": graph_name,
            }
            events.append(Event("verify-managed-synchronization", "verified",
                                "generated indexes and synchronization verified", {
                                    "document_count": evidence["document_count"],
                                    "graph_document_count": evidence["graph_document_count"],
                                    "serving_state": "verified",
                                    "latency_ms": timings["synchronization_ms"] + timings["verify_ms"],
                                }))
            _complete_journal(spec, graph_name, original)
            events.append(Event("build", "completed", "managed generation verified", evidence))
            return ApplyResult(tuple(events), True)
        except Exception as error:
            events.append(Event("build", "failed", f"{type(error).__name__}: {error}",
                                {"phase_latency_ms": timings}))
            return ApplyResult(tuple(events), False)
def _apply_documents(executor, spec: BuildSpec) -> ApplyResult:
        if plan(spec).blocked_by:
            raise BuildError("; ".join(plan(spec).blocked_by))
        name = index_names(spec)["content"]
        if executor.adapter.get_index(name) is not None:
            raise BuildError("generation already exists")
        timings: dict[str, float] = {}
        events: list[Event] = []
        recorder = TelemetryRecorder("build", adapter_http_stats(executor.adapter))
        started_total = time.perf_counter()
        try:
            started = time.perf_counter()
            files = corpus_files(spec.corpus_source)
            with recorder.span("stage") as span:
                executor.adapter.ensure_container(spec.storage_container)
                for filename, data in files:
                    executor.adapter.stage(spec.storage_container, f"{generation(spec)}/{filename}", data)
                span["counts"]["documents"] = len(files)
                span["bytes"] = sum(len(data) for _, data in files)
            timings["stage_ms"] = round((time.perf_counter() - started) * 1000, 3)
            events.append(Event("stage-corpus", "verified", "corpus staged", {
                "source_count": len(files), "uploaded_count": len(files),
                "latency_ms": timings["stage_ms"],
            }))
            started = time.perf_counter()
            with recorder.span("embed_and_index") as span:
                documents = []
                for filename, data in files:
                    source = f"{spec.storage_container}/{generation(spec)}/{filename}"
                    for number, offset in enumerate(range(0, len(data.decode("utf-8")), 2000)):
                        chunk = data.decode("utf-8")[offset:offset + 2000]
                        doc: dict[str, Any] = {
                            "id": stable_id("doc", [source, number]), "name": filename,
                            "text": chunk, "source": source,
                            "provenance": json.dumps({"source": source, "chunk": number}),
                        }
                        if spec.vector_retrieval:
                            doc["embedding"] = executor.adapter.embed(chunk)
                            if not doc["embedding"]:
                                raise BuildError("embedding service returned an empty vector")
                        documents.append(doc)
                if not documents:
                    raise BuildError("corpus contains no nonempty text chunks")
                dims = len(documents[0]["embedding"]) if spec.vector_retrieval else None
                if dims and any(len(doc["embedding"]) != dims for doc in documents):
                    raise BuildError("embedding dimension changed across chunks")
                schema = _document_schema(name, dims)
                executor.adapter.create_index(schema)
                span["counts"]["chunks"] = len(documents)
            timings["index_ms"] = round((time.perf_counter() - started) * 1000, 3)
            started = time.perf_counter()
            with recorder.span("populate"):
                executor.adapter.upload(name, documents)
                if executor.adapter.count(name) != len(documents):
                    raise BuildError("content index count differs from uploaded documents")
            timings["populate_ms"] = round((time.perf_counter() - started) * 1000, 3)
            evidence = {
                "document_count": len(documents), "edge_count": 0,
                "schema_hash": hash_json(schema), "phase_latency_ms": timings,
                "time_to_build_ms": round((time.perf_counter() - started_total) * 1000, 3),
                "indexes": {"content": name},
            }
            events.append(Event("ensure-content-index", "verified", "content indexed", evidence))
            events.append(Event("build", "completed", "document generation built",
                                {**evidence, "telemetry": recorder.events}))
            return ApplyResult(tuple(events), True)
        except Exception as error:
            events.append(Event("build", "failed", f"{type(error).__name__}: {error}",
                                {"phase_latency_ms": timings, "telemetry": recorder.events}))
            return ApplyResult(tuple(events), False)