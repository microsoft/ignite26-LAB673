from __future__ import annotations

import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ekg_core.telemetry import adapter_http_stats
from ekg_core.validation import validate_deployment_descriptor
from .adapters import AzureQueryAdapter, QueryAdapter
from .runtime import require_capability

_PARALLEL_READS = 8
GRAPH_ROUND_TRIP_LIMIT = 128
SEARCH_API_VERSION = "2026-08-01-preview"
INLINE_JSONLD_API_VERSION = "2026-11-01-preview"


class GraphBudgetExceeded(RuntimeError):
    """The traversal needed more Search round trips than one query may use."""


def _stats(client: Any) -> dict[str, int] | None:
    stats = adapter_http_stats(client)
    return stats.snapshot() if stats is not None else None


def _request_telemetry(client: Any, before: dict[str, int] | None) -> dict[str, Any]:
    after = _stats(client)
    if before is None or after is None:
        return {}
    delta = {key: after[key] - before.get(key, 0) for key in after}
    result: dict[str, Any] = {"requests": delta["requests"], "retries": delta["retries"],
                              "throttles": delta["throttles"]}
    if delta.get("total_tokens"):
        result["tokens"] = {"prompt": delta["prompt_tokens"], "total": delta["total_tokens"]}
    return result


def _validate_query(query: str) -> None:
    if (not isinstance(query, str) or not query.strip() or len(query) > 2048
            or any(ord(char) < 32 for char in query)):
        raise ValueError("query must be nonempty text of at most 2048 characters")


def _adapter(descriptor: dict[str, Any], injected: QueryAdapter | None) -> QueryAdapter:
    if injected is not None:
        return injected
    endpoints = descriptor.get("endpoints") or {}
    search = endpoints.get("search")
    if not isinstance(search, str) or not search.startswith("https://"):
        raise ValueError("deployment descriptor requires a Search endpoint")
    return AzureQueryAdapter(
        search, openai_endpoint=endpoints.get("openai"),
        embedding_deployment=endpoints.get("embedding_deployment"),
        search_api_version=endpoints.get("search_api_version", "2024-07-01"),
    )


def _managed_search_api_version(descriptor: dict[str, Any]) -> str | None:
    endpoints = descriptor.get("endpoints") or {}
    version = endpoints.get("search_api_version")
    ontology = descriptor.get("ontology") or {}
    mode = ontology.get("mode")
    if mode == "inline_jsonld":
        expected = INLINE_JSONLD_API_VERSION
    elif mode in {"owl_file", "schema_org"}:
        expected = SEARCH_API_VERSION
    else:
        return version if version == SEARCH_API_VERSION else None
    if version != expected:
        raise ValueError(f"{mode} ontology requires Search {expected}")
    return version


def _index(descriptor: dict[str, Any], kind: str) -> str:
    name = (descriptor.get("endpoints") or {}).get(f"{kind}_index")
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", name):
        raise ValueError(f"deployment descriptor requires a valid {kind}_index")
    return name


def _original(descriptor: dict[str, Any], staged: Any) -> dict[str, str] | None:
    provenance = descriptor.get("source_provenance")
    if provenance is None:
        if (descriptor.get("endpoints") or {}).get("source_manifest_digest"):
            raise RuntimeError("SOURCE_MAPPING_UNVERIFIED: source descriptor lacks original mapping")
        return None
    if validate_deployment_descriptor(descriptor):
        raise RuntimeError("SOURCE_MAPPING_UNVERIFIED: descriptor provenance is invalid")
    item = provenance["staged"].get(staged) if isinstance(staged, str) else None
    if item is None:
        raise RuntimeError("SOURCE_MAPPING_UNVERIFIED: observed staged URI has no exact original")
    return item


def _source(doc: dict[str, Any], descriptor: dict[str, Any]) -> dict[str, Any]:
    provenance = doc.get("provenance") or "{}"
    if not isinstance(provenance, str):
        raise ValueError("document provenance must be serialized JSON")
    evidence = json.loads(provenance)
    staged = doc.get("blob_url") if (descriptor.get("endpoints") or {}).get(
        "source_manifest_digest"
    ) else (
        doc.get("blob_url") or doc.get("source")
    )
    original = _original(descriptor, staged)
    return {
        "source": original["original_uri"] if original else staged,
        **({"citation_uri": original["citation_uri"], "source_id": original["source_id"],
            "version_or_hash": original["version_or_hash"]}
           if original else {}),
        "chunk_id": doc.get("uid") or doc.get("id"),
        "parent_id": doc.get("snippet_parent_id"),
        "text": doc.get("snippet") or doc.get("text"),
        "score": doc.get("@search.score"),
        "evidence": evidence,
    }


def retrieve(descriptor: dict[str, Any], query: str, method: str = "document_retrieval",
             *, adapter: QueryAdapter | None = None, top: int = 5,
             vector: bool = True) -> dict[str, Any]:
    require_capability(descriptor, method)
    if method != "document_retrieval":
        raise ValueError("agentic retrieval is not implemented")
    _validate_query(query)
    if type(top) is not int or not 1 <= top <= 100:
        raise ValueError("top must be an integer in 1..100")
    if ("source_provenance" in descriptor or
            (descriptor.get("endpoints") or {}).get("source_manifest_digest")) and (
            validate_deployment_descriptor(descriptor)):
        raise RuntimeError("SOURCE_MAPPING_UNVERIFIED: descriptor provenance is invalid")
    started = time.perf_counter()
    client = _adapter(descriptor, adapter)
    before = _stats(client)
    managed = _managed_search_api_version(descriptor) is not None
    embedding_ms = 0.0
    embedding = None
    if vector:
        embedding_started = time.perf_counter()
        embedding = client.embed(query)
        embedding_ms = round((time.perf_counter() - embedding_started) * 1000, 3)
    search_started = time.perf_counter()
    hits = client.search(_index(descriptor, "content"), query, top=top, vector=embedding,
                         vector_field="snippet_vector" if managed else "embedding")
    search_ms = round((time.perf_counter() - search_started) * 1000, 3)
    return {
        "result_schema_version": 1,
        "query": query, "answer": None,
        "provenance": [_source(hit, descriptor) for hit in hits],
        "telemetry": {
            "method": "hybrid" if vector else "lexical",
            "embedding_ms": embedding_ms, "search_ms": search_ms,
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            **_request_telemetry(client, before),
        },
        "capabilities_used": [method],
    }


def _literal(value: str) -> str:
    return value.replace("'", "''")


def _node_name(value: Any) -> str:
    name = value.get("name") if isinstance(value, dict) else value
    if not isinstance(name, str) or not name:
        raise RuntimeError("native graph row has an unknown node shape")
    return name


def _canonical(value: Any) -> str | None:
    if isinstance(value, str) and value and not value.startswith("ungrounded:"):
        return value
    return None


def _anchor(node: dict[str, Any]) -> tuple[str, str]:
    canon = node.get("canonical_id")
    return ("id", canon) if canon else ("name", node["name"])


def _labels(descriptor: dict[str, Any]) -> list[tuple[str, str, str]]:
    raw = (descriptor.get("ontology") or {}).get("edge_types")
    if not isinstance(raw, list) or not raw:
        raise ValueError("native graph query requires published ontology edge types")
    labels = []
    for relation in raw:
        if not isinstance(relation, list) or len(relation) != 3 or any(
            not isinstance(part, str) or not part or "`" in part for part in relation
        ):
            raise ValueError("published ontology contains an invalid graph label")
        labels.append((relation[0], relation[1], relation[2]))
    return labels


def graph_query(descriptor: dict[str, Any], query: str, *,
                adapter: QueryAdapter | None = None, depth: int = 2,
                top: int = 5, fanout: int = 20) -> dict[str, Any]:
    require_capability(descriptor, "graph_retrieval")
    _validate_query(query)
    if (type(depth) is not int or not 1 <= depth <= 3
            or type(top) is not int or not 1 <= top <= 10
            or type(fanout) is not int or not 1 <= fanout <= 50):
        raise ValueError("depth must be 1..3, top 1..10, and fanout 1..50")
    if _managed_search_api_version(descriptor) is None:
        raise ValueError("native graph query requires a managed ontology and supported Search API version")
    if ("source_provenance" in descriptor or
            (descriptor.get("endpoints") or {}).get("source_manifest_digest")) and (
            validate_deployment_descriptor(descriptor)):
        raise RuntimeError("SOURCE_MAPPING_UNVERIFIED: descriptor provenance is invalid")
    started = time.perf_counter()
    client = _adapter(descriptor, adapter)
    before = _stats(client)
    index = _index(descriptor, "graph")
    labels = _labels(descriptor)
    if len(labels) > 64:
        raise ValueError("ontology has too many edge types for bounded graph traversal")
    words = re.findall(r"[\w.'-]+", query)
    stop = {"who", "what", "which", "where", "when", "how", "does", "do",
            "did", "is", "are", "the", "a", "an", "of", "for", "with"}
    seed = next((word for word in words if word[:1].isupper()
                 and word.casefold() not in stop), query.strip())
    paths: list[list[str]] = []
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    provenance: dict[tuple[str, str], dict[str, Any]] = {}
    round_trips = 0
    anchors_skipped = 0
    graph_ms = 0.0
    frontier: list[list[str]] = []
    seed_ids: list[str] = []

    # Step 0 anchors on the question's name. Step 1 (grounded builds only) re-queries by the
    # canonical ids that name resolved to, so every alias of the entity is traversed too.
    for step in range(depth + 1):
        hop = max(0, step - 1)
        resolve = step == 1
        if resolve and not seed_ids:
            continue
        next_frontier: list[list[str]] = []
        queued: list[tuple[tuple[str, str], str, str, str, str]] = []
        if resolve:
            anchors = [("id", value) for value in seed_ids[:top]]
        elif hop == 0:
            anchors = [("name", seed)]
        else:
            anchors = list(dict.fromkeys(_anchor(nodes[path[-1]]) for path in frontier))
        if not anchors:
            break
        # Past hop 0 a row only extends a path when one endpoint is a frontier node,
        # so labels touching none of the frontier types cannot add results.
        frontier_types = {nodes[path[-1]]["type"] for path in frontier}
        hop_labels = labels if hop == 0 else [
            label for label in labels
            if label[0] in frontier_types or label[2] in frontier_types]
        anchors = anchors[:top * fanout]
        if (hop or resolve) and hop_labels:
            # Later hops expand the earliest-found anchors that fit the remaining budget
            # rather than failing the whole traversal.
            fits = max(0, GRAPH_ROUND_TRIP_LIMIT - round_trips) // len(hop_labels)
            anchors_skipped += max(0, len(anchors) - fits)
            anchors = anchors[:fits]
        for anchor in anchors:
            for source_type, predicate, target_type in hop_labels:
                if round_trips >= GRAPH_ROUND_TRIP_LIMIT:
                    raise GraphBudgetExceeded(
                        f"native graph traversal exceeded {GRAPH_ROUND_TRIP_LIMIT} Search round trips")
                pattern = (f"(a:`{source_type}`)-[r:`{predicate}`]->"
                           f"(b:`{target_type}`)")
                kind, value = anchor
                text = _literal(value)
                condition = (f"a.id = '{text}' OR b.id = '{text}'" if kind == "id" else
                             f"a.name CONTAINS '{text}' OR b.name CONTAINS '{text}'")
                gql = (f"MATCH {pattern} WHERE {condition} RETURN a.name AS a, a.id AS a_id, "
                       f"r.confidence AS c, b.name AS b, b.id AS b_id LIMIT {fanout}")
                queued.append((anchor, source_type, predicate, target_type, gql))
                round_trips += 1
        call_started = time.perf_counter()
        # Independent read-only queries are fetched concurrently and processed in queue order.
        with ThreadPoolExecutor(max_workers=_PARALLEL_READS) as pool:
            results = list(pool.map(
                lambda item: client.graph_search(index, item[4], provenance="ids"), queued))
        graph_ms += (time.perf_counter() - call_started) * 1000
        for (anchor, source_type, predicate, target_type, _), result in zip(queued, results):
            diagnostics = result.get("@search.graphDiagnostics") or []
            if any(item.get("severity") == "error" for item in diagnostics):
                raise RuntimeError("native graph query reported an error")
            rows = result.get("value")
            if not isinstance(rows, list):
                raise RuntimeError("native graph query returned malformed rows")
            for row in rows:
                if not isinstance(row, dict):
                    raise RuntimeError("native graph row has an unknown node shape")
                left, right = _node_name(row.get("a")), _node_name(row.get("b"))
                left_canon, right_canon = _canonical(row.get("a_id")), _canonical(row.get("b_id"))
                kind, value = anchor
                if kind == "id":
                    left_hit, right_hit = left_canon == value, right_canon == value
                else:
                    left_hit, right_hit = value in left, value in right
                if not left_hit and not right_hit:
                    continue
                a_id = left_canon or f"{source_type}:{left}"
                b_id = right_canon or f"{target_type}:{right}"
                if hop == 0:
                    origin, neighbor = (a_id, b_id) if left_hit else (b_id, a_id)
                    if origin == neighbor:
                        continue
                    path = [origin, neighbor]
                else:
                    matching = [path for path in frontier if path[-1] in (a_id, b_id)]
                    if not matching:
                        continue
                    prior = matching[0]
                    neighbor = b_id if prior[-1] == a_id else a_id
                    if neighbor in prior:
                        continue
                    path = [*prior, neighbor]
                proof = row.get("@search.graphProvenance") or {}
                if not isinstance(proof.get("evidence"), list) or not proof["evidence"]:
                    raise RuntimeError("native graph row lacks source provenance IDs")
                for item in proof["evidence"]:
                    if not isinstance(item, dict) or not item.get("chunkId"):
                        raise RuntimeError("native graph provenance lacks a chunk ID")
                for key, name, canon, node_type in ((a_id, left, left_canon, source_type),
                                                    (b_id, right, right_canon, target_type)):
                    node = nodes.setdefault(key, {
                        "id": key, "name": name, "type": node_type,
                        **({"canonical_id": canon} if canon else {}), "_names": []})
                    if name not in node["_names"]:
                        node["_names"].append(name)
                if hop == 0 and kind == "name":
                    for key, canon, hit in ((a_id, left_canon, left_hit), (b_id, right_canon, right_hit)):
                        if hit and canon and canon not in seed_ids:
                            seed_ids.append(canon)
                edge_id = f"{a_id}|{predicate}|{b_id}"
                if edge_id not in edges:
                    edges[edge_id] = {"id": edge_id, "from_id": a_id,
                                      "predicate": predicate, "to_id": b_id,
                                      "provenance": []}
                confidence = row.get("c")
                if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
                    edges[edge_id]["confidence"] = max(confidence, edges[edge_id].get("confidence", confidence))
                known = {(str(seen.get("edgeId")), seen["chunkId"])
                         for seen in edges[edge_id]["provenance"]}
                edges[edge_id]["provenance"].extend(
                    item for item in proof["evidence"]
                    if (str(item.get("edgeId")), item["chunkId"]) not in known)
                for item in proof["evidence"]:
                    provenance[(str(item.get("edgeId")), item["chunkId"])] = item
                if path not in paths:
                    paths.append(path)
                if path not in next_frontier:
                    next_frontier.append(path)
        if resolve:
            frontier = [*frontier, *(path for path in next_frontier if path not in frontier)]
        else:
            frontier = next_frontier
        frontier = frontier[:top * fanout]
    hydrate_started = time.perf_counter()
    content_index = _index(descriptor, "content")
    with ThreadPoolExecutor(max_workers=_PARALLEL_READS) as pool:
        chunks = list(pool.map(lambda item: client.lookup_chunk(content_index, item["chunkId"]),
                               provenance.values()))
    stale: set[tuple[str, str]] = set()
    for key, item, chunk in zip(list(provenance), list(provenance.values()), chunks):
        if chunk is None:
            # A content update removes chunks before the graph refresh catches up; skip, don't fail.
            stale.add(key)
            del provenance[key]
            continue
        if (not isinstance(chunk.get("blob_url"), str) or not chunk["blob_url"]
                or descriptor.get("source_provenance") is not None
                and chunk.get("uid") != item["chunkId"]):
            raise RuntimeError("native graph provenance chunk has no source document")
        original = _original(descriptor, chunk["blob_url"])
        item.update({
            "source": original["original_uri"] if original else chunk["blob_url"],
            **({"citation_uri": original["citation_uri"], "source_id": original["source_id"],
                "version_or_hash": original["version_or_hash"]} if original else {}),
            "text": chunk.get("snippet"),
            "parent_id": chunk.get("snippet_parent_id"),
        })
    for edge_id, edge in list(edges.items()):
        edge["provenance"] = [
            provenance[(str(item.get("edgeId")), item["chunkId"])]
            for item in edge["provenance"]
            if (str(item.get("edgeId")), item["chunkId"]) not in stale
        ]
        if not edge["provenance"]:
            del edges[edge_id]
    if stale:
        linked = {frozenset((edge["from_id"], edge["to_id"])) for edge in edges.values()}
        paths = [path for path in paths
                 if all(frozenset(pair) in linked for pair in zip(path, path[1:]))]
        kept = {node for edge in edges.values() for node in (edge["from_id"], edge["to_id"])}
        nodes = {key: node for key, node in nodes.items() if key in kept}
    warnings = []
    for node in nodes.values():
        names = node.pop("_names")
        if len(names) > 1:
            node["aliases"] = sorted(name for name in names if name != node["name"])
    if stale:
        warnings.append(f"skipped {len(stale)} graph fact(s) whose source chunk is gone; "
                        "a content update is still settling")
    if anchors_skipped:
        warnings.append(f"did not expand {anchors_skipped} intermediate entities to stay within "
                        f"{GRAPH_ROUND_TRIP_LIMIT} Search round trips; query again from an "
                        "intermediate entity to go deeper")
    hydrate_ms = round((time.perf_counter() - hydrate_started) * 1000, 3)
    elapsed = round((time.perf_counter() - started) * 1000, 3)
    return {
        "result_schema_version": 1,
        "query": query, "answer": None, "nodes": list(nodes.values()),
        "edges": list(edges.values()), "paths": paths,
        "provenance": list(provenance.values()),
        "telemetry": {
            "method": "graph", "search_ms": round(graph_ms, 3),
            "search_round_trips": round_trips,
            "chunk_lookups": len(provenance) + len(stale), "hydrate_ms": hydrate_ms,
            "stale_facts_skipped": len(stale),
            "anchors_skipped": anchors_skipped,
            "traversal_ms": round(max(0, elapsed - graph_ms - hydrate_ms), 3),
            "latency_ms": elapsed,
            **_request_telemetry(client, before),
        },
        "capabilities_used": ["graph_retrieval"],
        **({"warnings": warnings} if warnings else {}),
    }


def compact_graph_result(result: dict[str, Any]) -> dict[str, Any]:
    """Keep distinct evidence once, with document and evidence links on each edge."""
    evidence: dict[str, dict[str, Any]] = {}

    def keep(item: Any) -> tuple[str, str] | None:
        if not isinstance(item, dict):
            return None
        source_id = str(item.get("source_id") or item.get("citation_uri") or item.get("source") or "")
        if not source_id:
            return None
        identity = json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        evidence_id = "evidence-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
        evidence.setdefault(evidence_id, {**item, "evidence_id": evidence_id})
        return source_id, evidence_id

    edges = []
    for edge in result.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        links = [link for item in edge.get("provenance") or [] if (link := keep(item))]
        compact = {key: value for key, value in edge.items() if key != "provenance"}
        compact["source_ids"] = sorted({source_id for source_id, _ in links})
        compact["evidence_ids"] = sorted({evidence_id for _, evidence_id in links})
        edges.append(compact)
    for item in result.get("provenance") or []:
        keep(item)
    return {**result, "edges": edges, "provenance": list(evidence.values()), "detail": "compact"}
