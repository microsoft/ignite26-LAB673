"""Deterministic hierarchy sampling and shard packing.

Two phases so the plan can be priced without reading corpus text:
`select()` at plan time (no text; shards packed assuming `excerpt_chars` per passage) and
`attach_excerpts()` at propose time.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import replace
from fractions import Fraction

from ontology_build.grz_reader import EvidenceText, Membership, Representative
from ontology_core import hashing
from ontology_core.errors import Blocked
from ontology_core.model import Passage, Sample, Shard

MIN_COMMUNITIES_FOR_LEVEL = 20
MIN_PASSAGES = 120
MAX_PASSAGES = 800
PASSAGES_PER_COMMUNITY = 4
DEFAULT_EXCERPT_CHARS = 1200
DEFAULT_SHARD_CHARS = 60000
CITED_EXCERPT_CHARS = 400


def levels(representatives: list[Representative]) -> dict[int, int]:
    """`{level: community count}`, ascending by level."""
    counts = Counter(r.level for r in representatives)
    return {level: counts[level] for level in sorted(counts)}


def default_level(representatives: list[Representative]) -> int:
    """Coarsest level with >= `MIN_COMMUNITIES_FOR_LEVEL` communities, else the finest (0)."""
    counts = levels(representatives)
    eligible = [level for level, n in counts.items() if n >= MIN_COMMUNITIES_FOR_LEVEL]
    if eligible:
        return max(eligible)
    return min(counts) if counts else 0


def default_passages(communities_at_level: int, available_chunks: int) -> int:
    """`min(clamp(4n, 120, 800), available_chunks)`: the plan's clamp, capped at the chunks that exist."""
    clamped = max(MIN_PASSAGES, min(MAX_PASSAGES, PASSAGES_PER_COMMUNITY * communities_at_level))
    return max(0, min(clamped, available_chunks))


def evidence_id(chunk_id: str, *, taken: set[str] | None = None) -> str:
    """`"E" + sha256(chunk_id)[:10]`, or `[:12]` if that collides with `taken`."""
    short = hashing.evidence_id(chunk_id)
    if taken and short in taken:
        return hashing.evidence_id(chunk_id, 12)
    return short


def _leaf_order(chunks: list[str], seed: str) -> list[str]:
    return sorted(set(chunks), key=lambda c: (hashing.sha256_text(seed + c), c))


def _allocate(total: int, communities: list[Representative], capacity: dict[str, int]) -> dict[str, int]:
    """One passage per community with chunks, then the rest by largest remainder on `member_count`
    (ties to the smaller `community_id`), never above a community's chunk capacity. Spill-over from
    full communities is re-split the same way among the rest."""
    alloc = {r.community_id: min(1, capacity[r.community_id]) for r in communities}
    weight = {r.community_id: max(r.member_count, 0) for r in communities}
    while True:
        remaining = total - sum(alloc.values())
        open_ids = sorted(c for c in alloc if alloc[c] < capacity[c])
        if remaining <= 0 or not open_ids:
            return alloc
        weights = {c: weight[c] for c in open_ids}
        if sum(weights.values()) == 0:
            weights = {c: 1 for c in open_ids}
        denom = sum(weights.values())
        quota = {c: Fraction(remaining * weights[c], denom) for c in open_ids}
        given = 0
        for c in open_ids:
            add = min(int(quota[c]), capacity[c] - alloc[c])
            alloc[c] += add
            given += add
        leftover = remaining - given
        ranked = sorted(open_ids, key=lambda c: (-(quota[c] - int(quota[c])), c))
        for c in ranked:
            if leftover <= 0:
                break
            if alloc[c] < capacity[c]:
                alloc[c] += 1
                leftover -= 1


def select(representatives: list[Representative], members: list[Membership], *, plan_id_seed: str,
           level: int | None, passages: int | None, excerpt_chars: int = DEFAULT_EXCERPT_CHARS,
           shard_chars: int = DEFAULT_SHARD_CHARS) -> Sample:
    """Runs the sampling steps. Returns a `Sample` with `plan_id=""`, passages without `source_id`/`excerpt`,
    and shards packed by `excerpt_chars` per passage. Only level-0 rows of `members` are used.

    An explicit `passages` above the chunks available is capped (with a warning). A community whose
    passages exceed one shard keeps only the passages that fit, with a warning.

    Raises:
        Blocked("LEVEL_OUT_OF_RANGE"): explicit `level` has no communities.
        Blocked("PASSAGE_BUDGET_TOO_SMALL", n=<communities>): explicit `passages` < communities at level.
    """
    if excerpt_chars < 1 or shard_chars < 1:
        raise ValueError("excerpt_chars and shard_chars must be >= 1")
    counts = levels(representatives)
    if level is None:
        level = default_level(representatives)
    elif level not in counts:
        raise Blocked("LEVEL_OUT_OF_RANGE",
                      f"level {level} has no communities; levels are "
                      + (", ".join(f"{lv} ({n})" for lv, n in counts.items()) or "none"),
                      details={"levels": {str(k): v for k, v in counts.items()}})
    warnings: list[str] = []

    # 1. The tree: children by parent, leaf chunks from level-0 memberships.
    children: dict[str, list[Representative]] = defaultdict(list)
    for rep in representatives:
        if rep.parent_id is not None:
            children[rep.parent_id].append(rep)
    leaf_chunks: dict[str, list[str]] = defaultdict(list)
    for m in members:
        if m.level == 0:
            leaf_chunks[m.community_id].append(m.chunk_id)

    order_cache: dict[str, list[str]] = {}

    def order(rep: Representative) -> list[str]:
        """Every chunk under `rep` in pick order: hashed at a leaf, recursive round-robin above."""
        if rep.community_id in order_cache:
            return order_cache[rep.community_id]
        if rep.level == 0:
            result = _leaf_order(leaf_chunks.get(rep.community_id, []), plan_id_seed)
        else:
            kids = sorted(children.get(rep.community_id, []), key=lambda r: (-r.member_count, r.community_id))
            lists = [order(k) for k in kids]
            result, seen = [], set()
            for i in range(max((len(x) for x in lists), default=0)):
                for lst in lists:
                    if i < len(lst) and lst[i] not in seen:
                        seen.add(lst[i])
                        result.append(lst[i])
        order_cache[rep.community_id] = result
        return result

    # 2-3. The level's communities and the passage budget.
    at_level = sorted((r for r in representatives if r.level == level), key=lambda r: r.community_id)
    n = len(at_level)
    capacity = {r.community_id: len(order(r)) for r in at_level}
    available = sum(capacity.values())
    if passages is None:
        passages = default_passages(n, available)
    else:
        if passages < n:
            raise Blocked("PASSAGE_BUDGET_TOO_SMALL",
                          f"{passages} passages cannot cover the {n} communities at level {level}", n=n)
        if passages > available:
            warnings.append(f"passages capped at the {available} chunks available (asked for {passages})")
            passages = available
    empty = [c for c, cap in capacity.items() if cap == 0]
    if empty:
        warnings.append(f"{len(empty)} communities at level {level} have no level-0 members and get no passages")

    # 4-5. Allocate, then take each community's first k chunks in pick order.
    alloc = _allocate(passages, at_level, capacity)

    # 7. Pack whole communities into shards; a community over one shard is truncated at a passage boundary.
    per_shard = max(1, shard_chars // excerpt_chars)
    picked: list[tuple[str, list[str]]] = []
    for rep in at_level:
        k = alloc[rep.community_id]
        if k == 0:
            continue
        if k > per_shard:
            warnings.append(f"community {rep.community_id} truncated from {k} to {per_shard} passages "
                            f"to fit one shard of {shard_chars} chars")
            k = per_shard
        picked.append((rep.community_id, order(rep)[:k]))

    # 6. Evidence IDs, stable in passage order.
    taken: set[str] = set()
    eid_of: dict[str, str] = {}
    out_passages: list[Passage] = []
    for community_id, chunks in picked:
        for chunk in chunks:
            if chunk in eid_of:
                continue
            eid = evidence_id(chunk, taken=taken)
            taken.add(eid)
            eid_of[chunk] = eid
            out_passages.append(Passage(evidence_id=eid, chunk_id=chunk, community_id=community_id, level=level))

    shards: list[Shard] = []
    current: Shard | None = None
    used = 0
    for community_id, chunks in picked:
        eids = [p.evidence_id for p in out_passages if p.community_id == community_id]
        if not eids:
            continue
        size = len(eids) * excerpt_chars
        if current is None or used + size > shard_chars:
            current = Shard(index=len(shards), community_ids=[], evidence_ids=[])
            shards.append(current)
            used = 0
        current.community_ids.append(community_id)
        current.evidence_ids.extend(eids)
        used += size

    return Sample(plan_id="", level=level, excerpt_chars=excerpt_chars, shard_chars=shard_chars,
                  passages=out_passages, shards=shards, warnings=warnings)


def excerpt(text: str, excerpt_chars: int) -> str:
    """First `excerpt_chars` chars, cut back to the last whitespace, whitespace-collapsed."""
    if len(text) > excerpt_chars:
        head = text[:excerpt_chars]
        if not text[excerpt_chars].isspace():
            cut = max((i for i, ch in enumerate(head) if ch.isspace()), default=-1)
            if cut > 0:
                head = head[:cut]
        text = head
    return " ".join(text.split())


def attach_excerpts(sample: Sample, evidence: dict[str, EvidenceText], *, plan_id: str) -> Sample:
    """Copy of `sample` with `plan_id` set and `source_id`/`excerpt` filled for every passage.

    Raises:
        Blocked("GRZ_COUNTS_MISMATCH"): a sampled chunk is missing from `evidence`.
    """
    missing = [p.chunk_id for p in sample.passages if p.chunk_id not in evidence]
    if missing:
        raise Blocked("GRZ_COUNTS_MISMATCH",
                      f"{len(missing)} sampled chunks have no evidence text in the GRZ sidecar",
                      details={"missing": missing[:20]})
    passages = [replace(p, source_id=evidence[p.chunk_id].source_id,
                        excerpt=excerpt(evidence[p.chunk_id].text, sample.excerpt_chars))
                for p in sample.passages]
    shards = [Shard(index=s.index, community_ids=list(s.community_ids), evidence_ids=list(s.evidence_ids))
              for s in sample.shards]
    return Sample(plan_id=plan_id, level=sample.level, excerpt_chars=sample.excerpt_chars,
                  shard_chars=sample.shard_chars, passages=passages, shards=shards, warnings=list(sample.warnings))


def estimate_input_chars(sample: Sample, *, audit_mode: str = "full") -> dict[str, int]:
    """Upper-bound excerpt chars per call: `{"shard-0": n, ..., "audit": n}` (audit per plan audit_mode).

    A passage counts `len(excerpt)` once text is attached, else `excerpt_chars`. `audit_mode="full"` counts
    every passage; `"cited"` counts at most `CITED_EXCERPT_CHARS` per passage (any passage may be cited).
    """
    if audit_mode not in ("full", "cited"):
        raise ValueError(f"unknown audit_mode {audit_mode!r}")
    size = {p.evidence_id: len(p.excerpt) if p.excerpt is not None else sample.excerpt_chars for p in sample.passages}
    out = {f"shard-{s.index}": sum(size.get(e, sample.excerpt_chars) for e in s.evidence_ids) for s in sample.shards}
    cap = CITED_EXCERPT_CHARS if audit_mode == "cited" else None
    out["audit"] = sum(v if cap is None else min(v, cap) for v in size.values())
    return out
