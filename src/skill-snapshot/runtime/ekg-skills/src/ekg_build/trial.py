"""Trial build: extract a deterministic sample before committing to the full corpus.

A trial stages N of M approved documents under ``trial/<generation>`` and builds one
Knowledge Source from them. ``trial-report`` is read-only: it counts populated classes and
relationship types in the trial graph, lists those with zero hits, and extrapolates the
full-build time and dollar cost from this trial's measured wall time and tokens.
"""
from __future__ import annotations

import hashlib
import math
from typing import Any

from ekg_core.models import BuildSpec, Ontology, SourceManifest, TrialSample
from ekg_core.pricing import PRICE_BASIS, dollar_range, token_cost_usd

from .estimates import MAX_RUN_SECONDS, schedule_note

EDGE_LIMIT = 1000
RANGE = (0.8, 1.3)  # spread applied to the linear extrapolation
MIN_POPULATED_SHARE = 0.5


def _rank(item) -> str:
    return hashlib.sha256(f"{item.source_id}\n{item.version_or_hash}".encode()).hexdigest()


def sample_manifest(manifest: SourceManifest, size: int) -> tuple[SourceManifest, TrialSample]:
    """The N items with the lowest sha256(source_id, version) rank, in manifest order.
    The same manifest and N always give the same sample, on any machine."""
    total = len(manifest.items)
    if not 1 <= size < total:
        raise ValueError(f"--sample must be between 1 and {total - 1} for this "
                         f"{total}-document manifest; omit --sample to build everything")
    chosen = {id(item) for item in sorted(manifest.items, key=_rank)[:size]}
    sampled = SourceManifest(
        version=manifest.version, source=manifest.source, observed_at=manifest.observed_at,
        items=tuple(item for item in manifest.items if id(item) in chosen),
        transform_config_id=manifest.transform_config_id,
    )
    return sampled, TrialSample(size=size, corpus_documents=total,
                                corpus_digest=manifest.digest)


def _node(value: Any) -> str | None:
    name = value.get("name") if isinstance(value, dict) else value
    return name if isinstance(name, str) and name else None


def _minutes(ms: float) -> int:
    return max(1, round(ms / 60_000))


def _extrapolate(spec: BuildSpec, attribution: dict[str, Any] | None) -> dict[str, Any]:
    trial = spec.trial
    scale = trial.corpus_documents / trial.size
    window = (attribution or {}).get("window") or {}
    models = (attribution or {}).get("models") or {}
    notes: list[str] = []
    result: dict[str, Any] = {
        "basis": {
            "sample_documents": trial.size, "corpus_documents": trial.corpus_documents,
            "scale": round(scale, 3), "measured_wall_ms": window.get("processing_ms"),
            "items_processed": window.get("items_processed"),
            "items_failed": window.get("items_failed"),
            "tokens": {}, "price_basis": PRICE_BASIS,
            "method": f"linear in document count, range {RANGE[0]}x–{RANGE[1]}x",
        },
        "wall_minutes": None, "indexer_runs": None, "cost_usd": None, "notes": notes,
    }
    wall = window.get("processing_ms")
    if wall:
        full = wall * scale
        result["wall_minutes"] = {"low": _minutes(full * RANGE[0]),
                                  "high": _minutes(full * RANGE[1])}
        result["indexer_runs"] = max(1, math.ceil(full * RANGE[1] / 1000 / MAX_RUN_SECONDS))
        result["schedule"] = schedule_note(spec, result["indexer_runs"])
        if result["indexer_runs"] > 1:
            notes.append(result["schedule"]["note"])
    else:
        notes.append("The trial indexer has no finished execution, so wall time is unknown.")
    total = 0.0
    for role, entry in models.items():
        metrics = entry.get("metrics") or {}
        prompt, generated = metrics.get("prompt_tokens"), metrics.get("generated_tokens")
        if prompt is None:
            continue
        result["basis"]["tokens"][role] = {"model": entry.get("model"),
                                           "prompt_tokens": prompt,
                                           "generated_tokens": generated or 0}
        cost = token_cost_usd(entry.get("model"), prompt, generated or 0)
        if cost is None:
            notes.append(f"No list price for {role} model {entry.get('model')}; its cost "
                         "is left out.")
            continue
        total += cost * scale
    if result["basis"]["tokens"]:
        result["cost_usd"] = {"low": round(total * RANGE[0], 4),
                              "high": round(total * RANGE[1], 4)}
    else:
        notes.append("Model token metrics were not read, so cost is unknown. Pass "
                     "--tenant-id and --openai-resource-id.")
    return result


def report(spec: BuildSpec, ontology: Ontology, rows: dict[tuple[str, str, str], list],
           attribution: dict[str, Any] | None) -> dict[str, Any]:
    """Pure: ``rows`` maps each ontology edge type to the graph rows it matched."""
    trial = spec.trial
    predicates: dict[str, dict[str, Any]] = {}
    entities: dict[str, set[str]] = {name: set() for name in ontology.node_types}
    for (domain, predicate, range_name) in ontology.edge_types:
        found = rows.get((domain, predicate, range_name)) or []
        row = predicates.setdefault(predicate, {"edges": 0, "capped": False, "types": []})
        row["edges"] += len(found)
        row["capped"] = row["capped"] or len(found) >= EDGE_LIMIT
        row["types"].append({"domain": domain, "range": range_name, "edges": len(found)})
        for item in found:
            for label, key in ((domain, "a"), (range_name, "b")):
                name = _node(item.get(key))
                if name:
                    entities.setdefault(label, set()).add(name)
    classes = {name: len(found) for name, found in sorted(entities.items())}
    zero_predicates = sorted(name for name, row in predicates.items() if not row["edges"])
    zero_classes = sorted(name for name, count in classes.items() if not count)
    populated = len(predicates) - len(zero_predicates)
    edges = sum(row["edges"] for row in predicates.values())
    extrapolation = _extrapolate(spec, attribution)
    reasons = []
    if not edges:
        reasons.append("the trial graph has no relationships")
    elif populated < MIN_POPULATED_SHARE * len(predicates):
        reasons.append(f"only {populated} of {len(predicates)} relationship types were "
                       "extracted")
    failed = extrapolation["basis"]["items_failed"] or 0
    if failed > 0.1 * trial.size:
        reasons.append(f"{failed} of {trial.size} sample documents failed")
    go = not reasons
    wall, cost = extrapolation["wall_minutes"], extrapolation["cost_usd"]
    schedule = extrapolation.get("schedule")
    schedule_line = ([f"Schedule: {schedule['note']}"]
                     if schedule and not schedule["unattended"] else [])
    time_text = f"about {wall['low']}–{wall['high']} min" if wall else "time unknown"
    cost_text = (f"about {dollar_range(cost['low'], cost['high'])}" if cost
                 else "cost unknown")
    coverage = (f"{populated}/{len(predicates)} relationship types, "
                f"{len(classes) - len(zero_classes)}/{len(classes)} classes populated on "
                f"{trial.size} of {trial.corpus_documents:,} docs")
    decision = (f"GO: {coverage}; full build {time_text}, {cost_text}." if go else
                f"NO-GO: {'; '.join(reasons)} ({coverage}). Revise the ontology or "
                "documents and run another trial before the full build.")
    return {
        "status": "go" if go else "no_go",
        "summary": "\n".join([
            f"Trial on {trial.size} of {trial.corpus_documents:,} documents: {edges} "
            f"relationship(s) extracted.",
            f"Zero hits: relationships {', '.join(zero_predicates) or 'none'}; classes "
            f"{', '.join(zero_classes) or 'none'}.",
            *schedule_line,
            decision,
        ]),
        "sample": {"documents": trial.size, "corpus_documents": trial.corpus_documents,
                   "corpus_digest": trial.corpus_digest, "selection": trial.selection},
        "predicates": dict(sorted(predicates.items())),
        "classes": classes,
        "zero_hit": {"predicates": zero_predicates, "classes": zero_classes},
        "extrapolation": extrapolation,
        "decision": decision,
        "caveats": [
            "Counts come from relationships only: a class that appears only as an isolated "
            "entity counts as zero.",
            f"A {trial.size}-document sample undercounts rare classes and relationships; a "
            "zero here can still appear in the full corpus.",
            f"Edge counts stop at {EDGE_LIMIT} per relationship type (marked capped).",
        ],
        "next_step": ("Plan the full build without --sample, and clean up the trial with "
                      "`ekg-build plan-retire --generation <trial generation>`." if go else
                      "Clean up the trial with `ekg-build plan-retire --generation <trial "
                      "generation>`, adjust, then plan a new trial."),
    }


def collect(executor: Any, spec: BuildSpec) -> dict[str, Any]:
    """Read-only: verify the trial, query each edge type, read attribution."""
    from ekg_core.ontology import load_ontology
    from .attribution import collect as attribution
    from .executor import BuildError, generation, index_names
    from .managed_pipeline import generated

    if spec.trial is None:
        raise BuildError("TRIAL_REQUIRED: trial-report reads a trial build; plan it with --sample")
    executor.verify(spec)
    ontology = load_ontology(spec.ontology_mode, path=spec.ontology_path,
                             schema_org_profile=spec.schema_org_profile,
                             schema_org_version=spec.schema_org_version,
                             resolve_imports=spec.resolve_imports)
    name = index_names(spec)["knowledge_source"]
    graph_index = generated(executor.adapter.get_knowledge_source(name))["graphIndex"]
    rows = {}
    for domain, predicate, range_name in ontology.edge_types:
        result = executor.adapter.graph_search(
            graph_index, f"MATCH (a:`{domain}`)-[r:`{predicate}`]->(b:`{range_name}`) "
                         f"RETURN a, r, b LIMIT {EDGE_LIMIT}")
        if any(item.get("severity") == "error"
               for item in result.get("@search.graphDiagnostics") or []):
            raise BuildError(f"graph query for {predicate} returned an error diagnostic")
        rows[(domain, predicate, range_name)] = result["value"]
    measured = attribution(executor.adapter, name,
                           openai_resource_id=spec.target.openai_resource_id,
                           search_resource_id=spec.target.search_resource_id,
                           tenant_id=spec.tenant_id)
    result = report(spec, ontology, rows, measured)
    result["generation"] = generation(spec)
    result["next_step"] = result["next_step"].replace("<trial generation>",
                                                      result["generation"])
    return result
