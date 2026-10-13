"""Pure checks for the optional grounding index.

A grounding index is an existing Search index that exposes an ``edgeList`` graph profile.
ekg-skills only validates it (read-only) and names it in the Knowledge Source request; it never
creates, modifies or deletes one.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,127}")
PROFILE_KIND = "edgeList"


def name_blocker(name: str) -> str | None:
    if not isinstance(name, str) or NAME_PATTERN.fullmatch(name) is None:
        return ("GROUNDING_INDEX_NAME_INVALID: grounding_index must be a Search index name: "
                "lowercase letters, digits and dashes, starting with a letter or digit, "
                "at most 128 characters")
    return None


def collision_blocker(name: str, owned: Iterable[str]) -> str | None:
    if name.casefold() in {item.casefold() for item in owned}:
        return (f"GROUNDING_INDEX_COLLIDES_OWNED: grounding_index {name} is a name this build "
                "creates; name an existing index it does not own")
    return None


def profile_kind(definition: dict[str, Any] | None) -> str | None:
    profile = (definition or {}).get("graphProfile")
    kind = profile.get("kind") if isinstance(profile, dict) else None
    return kind if isinstance(kind, str) else None


LABEL_PREDICATES = ("rdfs:label", "skos:altLabel")
UNGROUNDED_PREFIX = "ungrounded:"


def plan_block(index: str, graph_name: str, cascade: Iterable[str]) -> dict[str, Any]:
    """What the plan tells the agent about aligning the grounding index before apply."""
    return {
        "index": index, "graph_name": graph_name, "cascade": list(cascade),
        "next_step": (
            f"Before apply, make the rows in index {index} carry graph_name = {graph_name} "
            "(label rows: predicate rdfs:label or skos:altLabel, subject_id the canonical id). "
            "The service only looks up rows whose graph_name matches exactly; if it does not, "
            "nothing is grounded and nothing warns until the build finishes."),
    }


def plan_card_line(block: dict[str, Any]) -> str:
    return (f"Grounding: index {block['index']} must have rows with graph_name "
            f"{block['graph_name']} (label rows included) before you approve.")


def coverage(rows: Iterable[dict[str, Any]], *, subject: str = "subject_id",
             object_: str = "object_id", confidence: str = "edge_confidence") -> dict[str, Any]:
    """Share of edge endpoints the grounding index resolved, and mean edge confidence."""
    edges = grounded_ends = grounded_edges = 0
    confidences: list[float] = []
    for row in rows:
        ends = [bool(isinstance(row.get(key), str) and row[key]
                     and not row[key].startswith(UNGROUNDED_PREFIX))
                for key in (subject, object_)]
        edges += 1
        grounded_ends += sum(ends)
        grounded_edges += all(ends)
        value = row.get(confidence)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            confidences.append(float(value))
    return {
        "edges": edges, "grounded_edges": grounded_edges,
        "edge_share": round(grounded_edges / edges, 4) if edges else 0.0,
        "end_share": round(grounded_ends / (2 * edges), 4) if edges else 0.0,
        "mean_confidence": round(sum(confidences) / len(confidences), 4) if confidences else None,
    }


def coverage_warning(index: str, graph_name: str, report: dict[str, Any]) -> dict[str, str] | None:
    """A warning (never a failure) when a grounding index resolved no endpoint at all."""
    if not report.get("edges") or report.get("end_share"):
        return None
    return {
        "warning": (f"GROUNDING_COVERAGE_ZERO: grounding index {index} resolved 0% of "
                    f"{report['edges']} edge endpoints; every node is ungrounded."),
        "next_step": (f"Usual causes: the index rows' graph_name is not {graph_name} (check "
                      f"`ekg-build doctor --grounding-index {index} --grounding-graph-name "
                      f"{graph_name}`), or the index has no label rows (predicate rdfs:label "
                      "or skos:altLabel with subject_id). Fix the index, then rebuild; the "
                      "build itself is intact and usable ungrounded."),
    }


def classify(name: str, definition: dict[str, Any] | None, *, status: int | None = None,
             profile_returned: bool = True) -> str | None:
    """The blocker for a live index-definition read, or None when the index is usable.

    ``status`` is the HTTP status of a failed read; ``profile_returned`` is False when the
    service or API version does not return graph profiles at all.
    """
    if status == 404 or (status is None and definition is None):
        return (f"GROUNDING_INDEX_NOT_FOUND: index {name} does not exist on the target "
                "Search service")
    if status is not None:
        return (f"GROUNDING_INDEX_UNREADABLE: cannot read index {name} (HTTP {status}); the "
                "build identity needs Search Index Data Reader and Reader on the Search service")
    if not profile_returned:
        return (f"GROUNDING_VALIDATION_UNAVAILABLE: the Search service did not return a graph "
                f"profile for index {name}, so it cannot be validated")
    kind = profile_kind(definition)
    if kind != PROFILE_KIND:
        return (f"GROUNDING_PROFILE_MISSING: index {name} has "
                f"{'graph profile kind ' + kind if kind else 'no graph profile'}; "
                f"grounding needs kind {PROFILE_KIND}")
    return None
