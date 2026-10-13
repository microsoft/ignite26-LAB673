"""JSON-lines transport for offline handoff and read-only descriptor consumption."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import urlsplit

from ekg_consume.adapters import QueryAdapter
from ekg_consume.runtime import CapabilityError, capabilities, require_capability
from ekg_consume.service import (
    GRAPH_ROUND_TRIP_LIMIT, GraphBudgetExceeded, graph_query, retrieve,
)
from ekg_core.descriptors import resolve_current
from ekg_core.telemetry import CONSUME_LOG_ENV, append_consume_event, consume_event
from ekg_core.validation import validate_deployment_descriptor


_CONSUME_OPERATIONS = {
    "ekg.consume.capabilities", "ekg.consume.health", "ekg.consume.query",
    "ekg.consume.graph_query", "ekg.consume.retrieve",
}
_SERVICE_DOMAINS = {
    "search": ("search.windows.net", "search.azure.us", "search.azure.cn"),
    "openai": ("openai.azure.com", "cognitiveservices.azure.com",
               "openai.azure.us", "openai.azure.cn"),
}


def _error(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "code": code, "message": message}


def _endpoint(descriptor: dict[str, Any], name: str) -> bool:
    url = descriptor["endpoints"].get(name)
    if not isinstance(url, str):
        return False
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return False
    return (parsed.scheme == "https" and bool(host)
            and any(host.endswith("." + suffix) for suffix in _SERVICE_DOMAINS[name])
            and port in (None, 443) and parsed.path in ("", "/")
            and not parsed.username and not parsed.password
            and not parsed.query and not parsed.fragment)


def _consume(request: dict[str, Any], adapter: QueryAdapter | None) -> dict[str, Any]:
    operation = request["operation"]
    allowed = {"operation", "descriptor", "descriptor_path"}
    if operation in {"ekg.consume.query", "ekg.consume.retrieve"}:
        allowed |= {"query", "top", "vector"}
    elif operation == "ekg.consume.graph_query":
        allowed |= {"query", "top", "depth", "fanout", "detail"}
    if set(request) - allowed:
        return _error("INVALID_REQUEST", "Unsupported fields for this operation")
    descriptor = request.get("descriptor")
    if descriptor is None:
        path = request.get("descriptor_path")
        if path in (None, ""):
            try:
                path = str(resolve_current())
            except (FileNotFoundError, ValueError) as error:
                return _error("INVALID_DESCRIPTOR", f"no current descriptor: {error}")
        if not isinstance(path, str) or not Path(path).is_absolute():
            return _error("INVALID_DESCRIPTOR", "descriptor_path must be an absolute path")
        try:
            file = Path(path)
            if file.stat().st_size > 1024 * 1024:
                return _error("INVALID_DESCRIPTOR", "descriptor exceeds the 1 MiB limit")
            descriptor = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return _error("INVALID_DESCRIPTOR", "descriptor_path must point to a readable JSON file")
    errors = validate_deployment_descriptor(descriptor)
    if errors:
        safe_errors = [
            "unknown capability in descriptor" if item.startswith("unknown capability:")
            else item for item in errors
        ]
        return _error("INVALID_DESCRIPTOR", "; ".join(safe_errors))
    if operation == "ekg.consume.capabilities":
        return {"ok": True, "result": capabilities(descriptor)}
    if operation == "ekg.consume.health":
        return {"ok": True, "result": {
            "status": "descriptor_validated",
            "deployment_id": descriptor["deployment_id"],
        }}

    query = request.get("query")
    if (not isinstance(query, str) or not query.strip()
            or len(query) > 2048 or any(ord(char) < 32 for char in query)):
        return _error("INVALID_REQUEST", "query must be nonempty text of at most 2048 characters")
    top = request.get("top", 5)
    maximum = 10 if operation == "ekg.consume.graph_query" else 100
    if type(top) is not int or not 1 <= top <= maximum:
        return _error("INVALID_REQUEST", f"top must be an integer in 1..{maximum}")
    if operation == "ekg.consume.graph_query":
        depth, fanout = request.get("depth", 2), request.get("fanout", 20)
        if type(depth) is not int or not 1 <= depth <= 3:
            return _error("INVALID_REQUEST", "depth must be an integer in 1..3")
        if type(fanout) is not int or not 1 <= fanout <= 50:
            return _error("INVALID_REQUEST", "fanout must be an integer in 1..50")
        detail = request.get("detail", "full")
        if detail not in {"compact", "full"}:
            return _error("INVALID_REQUEST", "detail must be compact or full")
        capability = "graph_retrieval"
    else:
        vector = request.get("vector", True)
        if not isinstance(vector, bool):
            return _error("INVALID_REQUEST", "vector must be boolean")
        capability = "document_retrieval"
    try:
        require_capability(descriptor, capability)
    except CapabilityError as error:
        return {"ok": False, **error.to_dict()}

    endpoints = descriptor["endpoints"]
    if not _endpoint(descriptor, "search"):
        return _error("INVALID_DESCRIPTOR", "A credential-free HTTPS search endpoint is required")
    if "openai" in endpoints and not _endpoint(descriptor, "openai"):
        return _error("INVALID_DESCRIPTOR", "OpenAI endpoint must be credential-free HTTPS")
    for index in ("content_index", "graph_index") if operation == "ekg.consume.graph_query" else ("content_index",):
        name = endpoints.get(index)
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", name):
            return _error("INVALID_DESCRIPTOR", f"A valid {index} is required")
    if operation == "ekg.consume.graph_query":
        ontology = descriptor.get("ontology")
        labels = ontology.get("edge_types") if isinstance(ontology, dict) else None
        if (endpoints.get("search_api_version") != "2026-08-01-preview"
                or not isinstance(labels, list) or not 1 <= len(labels) <= 64
                or any(not isinstance(edge, list) or len(edge) != 3
                       or any(not isinstance(part, str) or not part or "`" in part
                              for part in edge) for edge in labels)):
            return _error("INVALID_DESCRIPTOR", "Native graph index and ontology are required")
    elif vector and (not _endpoint(descriptor, "openai")
                     or not isinstance(endpoints.get("embedding_deployment"), str)
                     or not endpoints["embedding_deployment"]):
        return _error("INVALID_DESCRIPTOR", "Vector retrieval requires HTTPS OpenAI and an embedding deployment")

    started = time.time()
    try:
        if operation == "ekg.consume.graph_query":
            result = graph_query(
                descriptor, query, adapter=adapter, top=top, depth=depth, fanout=fanout,
            )
        else:
            result = retrieve(descriptor, query, adapter=adapter, top=top, vector=vector)
    except GraphBudgetExceeded:
        return _error("GRAPH_ROUND_TRIP_LIMIT",
                      f"Graph traversal needed more than {GRAPH_ROUND_TRIP_LIMIT} Search round "
                      "trips (anchors x edge types per hop). Split the question: query depth 2 "
                      "from the named entity, then query again from the intermediate entity it "
                      "returns (for example a project or person name). A smaller top or fanout "
                      "also reduces round trips but may drop paths.")
    except Exception as error:
        print(f"read-only consume backend failed: {type(error).__name__}", file=sys.stderr)
        return _error("CONSUME_BACKEND_ERROR", "Read-only consume backend failed")
    log = os.environ.get(CONSUME_LOG_ENV)
    if log:
        try:
            append_consume_event(log, consume_event(
                "graph_query" if operation == "ekg.consume.graph_query" else "retrieve",
                result, started))
        except OSError as error:
            print(f"consume telemetry log write failed: {type(error).__name__}", file=sys.stderr)
    if operation == "ekg.consume.graph_query" and detail == "compact":
        result = compact_graph_result(result)
    return {"ok": True, "result": result}


_COMPACT_SOURCE_FIELDS = ("source_id", "source", "citation_uri", "version_or_hash", "text")


def compact_graph_result(result: dict[str, Any]) -> dict[str, Any]:
    """Same answer, one provenance entry per source, and edges that reference it by ID.

    Full results repeat every chunk's provenance on each edge and again at the top level,
    which pushes typical multi-hop answers past what an agent reads inline."""
    sources: dict[str, dict[str, Any]] = {}

    def keep(item: Any) -> str | None:
        if not isinstance(item, dict):
            return None
        key = str(item.get("source_id") or item.get("citation_uri") or item.get("source") or "")
        if key and key not in sources:
            sources[key] = {field: item[field] for field in _COMPACT_SOURCE_FIELDS if field in item}
        return key or None

    edges = []
    for edge in result.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        ids = [key for key in (keep(item) for item in edge.get("provenance") or []) if key]
        compact = {key: value for key, value in edge.items() if key != "provenance"}
        compact["source_ids"] = sorted(set(ids))
        edges.append(compact)
    for item in result.get("provenance") or []:
        keep(item)
    return {**result, "edges": edges, "provenance": list(sources.values()), "detail": "compact"}


def dispatch(request: Any, *, adapter: QueryAdapter | None = None) -> dict[str, Any]:
    if not isinstance(request, dict) or not isinstance(request.get("operation"), str):
        return _error("INVALID_REQUEST", "Request must be an object with an operation")
    operation = request["operation"]
    if operation == "health":
        return {"ok": True, "service": "ekg-skills"}
    if operation == "ekg.build.preview_enablement_handoff":
        return _preview_handoff(request)
    if operation in _CONSUME_OPERATIONS:
        return _consume(request, adapter)
    return _error("ADAPTER_BACKEND_REQUIRED", "No backend configured for this operation")


def _preview_handoff(request: dict) -> dict:
    from ekg_build.enablement import preview_enablement_handoff
    from ekg_build.executor import BuildError
    from ekg_core.models import (
        BuildAccessSpec, BuildSpec, ModelDeploymentSpec, NetworkSpec, OntologyMode,
        ProvisioningSpec, PublicTestSpec, Target,
    )

    try:
        build_input = request["build"]
        provision_input = request["provision"]
        build = BuildSpec(
            target=Target(**build_input["target"]),
            corpus_source=build_input["corpus_source"],
            ontology_mode=OntologyMode(build_input["ontology_mode"]),
            **{key: value for key, value in build_input.items()
               if key not in {"target", "corpus_source", "ontology_mode"}},
        )
        provision_options = {
            key: value for key, value in provision_input.items()
            if key not in {"target", "network", "public_test", "model_deployments",
                           "build_access"}
        }
        if provision_input.get("model_deployments"):
            provision_options["model_deployments"] = tuple(
                ModelDeploymentSpec(**item) for item in provision_input["model_deployments"])
        if provision_input.get("build_access") is not None:
            provision_options["build_access"] = BuildAccessSpec(**provision_input["build_access"])
        if provision_input.get("network") is not None:
            provision_options["network"] = NetworkSpec(**provision_input["network"])
        if provision_input.get("public_test") is not None:
            public = provision_input["public_test"]
            provision_options["public_test"] = PublicTestSpec(
                **{**public, "egress_ips": tuple(public["egress_ips"])}
            )
        provision = ProvisioningSpec(
            target=Target(**provision_input["target"]),
            **provision_options,
        )
        return preview_enablement_handoff(
            build, provision, request["provision_verification"],
            tenant_id=request["tenant_id"],
        )
    except (KeyError, TypeError, ValueError, BuildError) as error:
        return {"status": "blocked", "code": "INVALID_PREVIEW_HANDOFF",
                "message": str(error)}


def main(*, adapter: QueryAdapter | None = None,
         input_stream: TextIO | None = None, output_stream: TextIO | None = None) -> None:
    source = input_stream if input_stream is not None else sys.stdin
    target = output_stream if output_stream is not None else sys.stdout
    for line in source:
        try:
            response = dispatch(json.loads(line), adapter=adapter)
        except json.JSONDecodeError:
            response = _error("INVALID_REQUEST", "Request must be valid JSON")
        try:
            output = json.dumps(response)
        except (TypeError, ValueError) as error:
            print(f"read-only consume response failed: {type(error).__name__}", file=sys.stderr)
            output = json.dumps(_error("CONSUME_BACKEND_ERROR",
                                       "Read-only consume backend returned an invalid response"))
        target.write(output + "\n")
        target.flush()


if __name__ == "__main__":
    main()
