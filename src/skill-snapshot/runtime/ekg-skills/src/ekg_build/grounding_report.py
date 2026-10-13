"""Read-only grounding coverage of a finished build's graph index (a warning, never a gate)."""

from __future__ import annotations

from typing import Any

from ekg_core import grounding
from ekg_core.models import BuildSpec, OntologyMode


def measure(adapter, spec: BuildSpec, graph_name: str, graph_index: str,
            definition: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Coverage of the build's graph index; None when no grounding index was set."""
    if not spec.grounding_index:
        return None
    base = {"index": spec.grounding_index, "graph_name": graph_name, "graph_index": graph_index}
    try:
        definition = definition if definition is not None else adapter.get_index(graph_index)
        fields = ((definition or {}).get("graphProfile") or {}).get("fields") or {}
        keys = {"id": fields.get("assertionIdField") or "id",
                "subject": fields.get("subjectIdField") or "subject_id",
                "object": fields.get("objectIdField") or "object_id",
                "confidence": fields.get("confidenceField") or "edge_confidence"}
        rows = adapter.scan(graph_index, ",".join(dict.fromkeys(keys.values())), keys["id"])
    except (AttributeError, KeyError, RuntimeError, ValueError, OSError) as error:
        return {**base, "status": "unavailable",
                "detail": f"could not read graph index {graph_index}: {error}"}
    result = {**base, "status": "measured", **grounding.coverage(
        rows, subject=keys["subject"], object_=keys["object"], confidence=keys["confidence"])}
    result.update(grounding.coverage_warning(spec.grounding_index, graph_name, result) or {})
    return result


def for_build(adapter, spec: BuildSpec) -> dict[str, Any] | None:
    """Look up the build's generated graph index, then measure it."""
    if not spec.grounding_index or spec.ontology_mode is OntologyMode.NONE:
        return None
    from .executor import index_names
    from .managed_pipeline import generated
    name = index_names(spec)["knowledge_source"]
    try:
        live = adapter.get_knowledge_source(name)
        graph_index = generated(live)["graphIndex"]
    except (AttributeError, KeyError, TypeError, RuntimeError, ValueError, OSError) as error:
        return {"index": spec.grounding_index, "graph_name": name, "status": "unavailable",
                "detail": f"could not locate the graph index: {error}"}
    return measure(adapter, spec, name, graph_index)


def attach(result: dict[str, Any], report: dict[str, Any] | None) -> dict[str, Any]:
    """Add the coverage report, and its warning at the top level for the summary."""
    if report is None:
        return result
    result["grounding_coverage"] = report
    if report.get("warning"):
        result["warning"] = report["warning"]
        previous = result.get("next_step")
        result["next_step"] = report["next_step"] + (f" Then: {previous}" if previous else "")
    return result
