"""Prompt templates.

`prompt_sha256()` hashes both system templates before seed rendering; it is part of the plan ID and is
pinned in tests/test_prompts.py, so any prompt edit must update that pin in the same PR.
"""

from __future__ import annotations

import json
from typing import Literal

from ontology_core import hashing
from ontology_core.model import Ontology, Passage, Shard

PROPOSAL_SYSTEM = """\
You design a compact domain ontology for a document corpus. You see passages grouped by topic community. Each passage has an evidence ID like E1a2b3c4d5e.

Propose the entity classes and relationships a knowledge graph over this corpus needs to answer multi-hop questions (who did what, where, when, for whom, as part of what).

Rules:
- Class names: PascalCase singular nouns (Person, Organization, Project). Property names: lowerCamelCase verbs or verb phrases (worksFor, locatedIn, startDate).
- Every class and property cites 1-5 evidence IDs from the passages that show it. Cite only IDs you were given.
- Object properties connect two classes you define (domain, range). Datatype properties have range String, Double, Boolean or DateTime.
- Prefer types that recur across communities over one-off types. Prefer 10-40 classes.
- Do not create classes for documents, passages, sections, pages, tables or files. Do not create classes that are individual named entities (a specific company, person or place).
- Descriptions: one sentence, under 200 characters, defining the type for someone who has not seen the corpus.
{SEED_BLOCK}
Return only JSON:
{"classes":[{"name":"","description":"","evidence":[""]}],
 "properties":[{"name":"","kind":"object|datatype","domain":"","range":"","description":"","evidence":[""]}]}
"""
"""The proposal system prompt verbatim, with a `{SEED_BLOCK}` placeholder."""

AUDIT_SYSTEM = """\
You audit and merge candidate ontology fragments proposed from different parts of one corpus.

Produce one consolidated ontology:
- Merge synonyms and near-duplicates into one type; keep the clearer name; union their evidence IDs.
- Remove types that are too generic (Thing, Entity, Item, Document), too specific (a single named entity), or document-structure types.
- Make every object property's domain and range a class in your output; fix or drop dangling ones.
- Keep a type only if it has at least one evidence ID from the candidates. Do not invent evidence IDs.
- Keep 10-40 classes unless the corpus clearly needs fewer.
{SEED_BLOCK}
Return only JSON in the same shape as the candidates.
"""
"""The audit system prompt verbatim, with a `{SEED_BLOCK}` placeholder."""

AUDIT_FULL_MAX_TOKENS = 100_000
CITED_EXCERPT_CHARS = 400
AuditMode = Literal["full", "cited"]
Message = dict[str, str]
"""`{"role": "system"|"user", "content": str}`."""


def prompt_sha256() -> str:
    """sha256 hex of `PROPOSAL_SYSTEM + "\\n" + AUDIT_SYSTEM` (unrendered)."""
    return hashing.sha256_text(PROPOSAL_SYSTEM + "\n" + AUDIT_SYSTEM)


def seed_block(seed: Ontology | None) -> str:
    """The existing-types block, or `""` without a seed."""
    if seed is None or not (seed.classes or seed.properties):
        return ""
    lines = ["Existing types (keep them; reuse them as domain/range; do not redefine them):"]
    lines += [f"- Class {c.name}: {c.description}" for c in sorted(seed.classes, key=lambda c: c.name)]
    lines += [f"- Property {p.name} ({p.domain} -> {p.range}): {p.description}"
              for p in sorted(seed.properties, key=lambda p: (p.name, p.domain, p.range))]
    lines.append("Add new types only where the passages show something the existing types do not cover.")
    return "\n".join(lines)


def _system(template: str, seed: Ontology | None) -> str:
    # `.replace`, not `.format`: the templates contain literal JSON braces
    return template.replace("{SEED_BLOCK}", seed_block(seed))


def proposal_messages(shard: Shard, passages: list[Passage], *, seed: Ontology | None,
                      labels: dict[str, str] | None = None, member_counts: dict[str, int] | None = None) -> list[Message]:
    """System + user messages for one shard. `passages` must carry `excerpt`. `labels` maps community_id to a
    named GRZ label hint."""
    labels = labels or {}
    member_counts = member_counts or {}
    wanted = set(shard.evidence_ids)
    by_community: dict[str, list[Passage]] = {}
    for passage in passages:
        if passage.evidence_id in wanted:
            by_community.setdefault(passage.community_id, []).append(passage)
    sections = []
    for community_id in shard.community_ids:
        members = by_community.get(community_id, [])
        if not members:
            continue
        level = members[0].level
        count = member_counts.get(community_id, len(members))
        label = f" \u2014 label: {labels[community_id]}" if labels.get(community_id) else ""
        lines = [f"## Community {community_id} (level {level}, {count} chunks){label}"]
        lines += [f"[{p.evidence_id}] {_excerpt(p)}" for p in members]
        sections.append("\n".join(lines))
    return [{"role": "system", "content": _system(PROPOSAL_SYSTEM, seed)},
            {"role": "user", "content": "\n\n".join(sections)}]


def _excerpt(passage: Passage) -> str:
    if passage.excerpt is None:
        raise ValueError(f"passage {passage.evidence_id} has no excerpt")
    return passage.excerpt


def cited_ids(candidates: list[dict[str, object]]) -> set[str]:
    """Every evidence ID cited by any class or property in `candidates`."""
    found: set[str] = set()
    for candidate in candidates:
        for key in ("classes", "properties"):
            items = candidate.get(key)
            for item in items if isinstance(items, list) else []:
                evidence = item.get("evidence") if isinstance(item, dict) else None
                if isinstance(evidence, list):
                    found.update(e for e in evidence if isinstance(e, str))
    return found


def audit_messages(candidates: list[dict[str, object]], passages: list[Passage], *, seed: Ontology | None,
                   audit_mode: AuditMode) -> list[Message]:
    """System + user messages for the audit: candidate JSON per shard, then `## Evidence` (all excerpts for
    `full`; cited ones truncated to `CITED_EXCERPT_CHARS` for `cited`)."""
    parts = [f"## Candidates from shard {k}\n{json.dumps(c, ensure_ascii=False, sort_keys=True)}"
             for k, c in enumerate(candidates)]
    if audit_mode == "full":
        evidence = [f"[{p.evidence_id}] {_excerpt(p)}" for p in passages]
    else:
        cited = cited_ids(candidates)
        evidence = [f"[{p.evidence_id}] {_excerpt(p)[:CITED_EXCERPT_CHARS]}" for p in passages if p.evidence_id in cited]
    parts.append("## Evidence\n" + "\n".join(evidence))
    return [{"role": "system", "content": _system(AUDIT_SYSTEM, seed)},
            {"role": "user", "content": "\n\n".join(parts)}]


CRITIQUE_SYSTEM = """\
You review a flat domain ontology (classes and properties, no subclasses) that was built from a document corpus, and you propose concrete fixes. You see the ontology, deterministic lint findings, evidence passages (IDs like E1a2b3c4d5e) and, when given, competency questions the ontology must answer.

Score each rubric dimension 1-5 (5 is best):
- connectivity: every class takes part in object properties that express how it relates to others; no orphaned classes; no single hub class owning most relationships.
- specificity: each class is one coherent concept, not a catch-all listing many unrelated alternatives.
- domain_range_correctness: each object property's domain and range are the right classes for its meaning.
- redundancy: no overlapping properties or near-duplicate classes.
- grounding: types and descriptions match the evidence.
- question_coverage: only when competency questions are given; how many can be answered by traversing the ontology.

Report findings. Each finding has a fingerprint `kind:Target` (snake_case kind, then the class or property name, or `Domain->Range` for a pair), a severity (high, medium, low), a one-sentence rationale and the evidence IDs that support it. Reuse a lint finding's fingerprint when you agree with it.

Propose change ops that fix high and medium findings. Every op names the fingerprint it fixes in `finding`. Allowed ops:
- {"op":"add_object_property","finding":"","name":"","domain":"","range":"","description":"","evidence":[""]}
- {"op":"add_datatype_property","finding":"","name":"","domain":"","range":"String|Double|Boolean|DateTime","description":"","evidence":[""]}
- {"op":"narrow_class","finding":"","name":"","description":""}
- {"op":"split_class","finding":"","name":"","into":[{"name":"","description":""}],"reassign":{"propertyName":"NewClass"}}  (every property that uses the old class moves to the class named in `reassign`, or to the first `into` class)
- {"op":"rename","finding":"","from":"","to":""}
- {"op":"drop_property","finding":"","name":"","merge_into":""}  (a property with evidence needs somewhere for its evidence to go: `merge_into` an existing property of the same kind, or add a replacement with the same domain and range in the same list; otherwise leave merge_into empty)
- {"op":"drop_class","finding":"","name":"","merge_into":""}  (a class with evidence only with `merge_into` naming the class that takes over its evidence and properties; without it, only a class with no evidence that no property uses)

Rules:
- Class names are PascalCase singular nouns; property names are lowerCamelCase. Refer only to names in the ontology or created by an earlier op in your list.
- New properties cite 1-5 evidence IDs from the passages you were given. Cite only IDs you were given.
- Connect orphaned classes that carry evidence (for example a transaction linked to the organizations and products involved) instead of dropping them.
- Narrow or split a catch-all class; keep descriptions to one sentence under 200 characters.
- Rename only a wrong or misleading name. Do not rename a property just to add its domain class (servesIndustry -> organizationServesIndustry): properties are already scoped by their domain, and such renames are ignored.
- Never lose evidence: do not drop a property or class that cites passages unless its evidence moves to a replacement as described above. A property whose meaning is right but whose domain or range is wrong is fixed by adding the corrected property and dropping the old one in the same list.
- Never rename, drop or split a class or property marked "seed": true.
- Propose at most 20 ops.

Return only JSON:
{"scores":{"connectivity":0,"specificity":0,"domain_range_correctness":0,"redundancy":0,"grounding":0},
 "findings":[{"fingerprint":"","severity":"high|medium|low","rationale":"","evidence":[""]}],
 "ops":[]}
"""
"""The critique judge's system prompt. Pinned by `critique_prompt_sha256()` in tests/test_prompts.py."""

RUBRIC: tuple[str, ...] = ("connectivity", "specificity", "domain_range_correctness", "redundancy", "grounding")
QUESTION_RUBRIC = "question_coverage"


def critique_prompt_sha256() -> str:
    """sha256 hex of `CRITIQUE_SYSTEM`; part of every critique/refine plan ID."""
    return hashing.sha256_text(CRITIQUE_SYSTEM)


def critique_messages(ontology: Ontology, findings: list[dict[str, str]], evidence: list[tuple[str, str]],
                      queries: list[dict[str, str]] | None) -> list[Message]:
    """System + user messages for one judge call: `## Ontology` (compact JSON), `## Lint findings`,
    `## Evidence` (`[id] excerpt`) and, when given, `## Competency questions` (then question_coverage is
    scored too)."""
    compact = {
        "classes": [{"name": c.name, "description": c.description, "evidence": len(c.evidence),
                     **({"seed": True} if c.seed else {})} for c in ontology.classes],
        "properties": [{"name": p.name, "kind": p.kind, "domain": p.domain, "range": p.range,
                        "description": p.description, **({"seed": True} if p.seed else {})}
                       for p in ontology.properties],
    }
    parts = ["## Ontology\n" + json.dumps(compact, ensure_ascii=False, sort_keys=True),
             "## Lint findings\n" + (json.dumps(findings, ensure_ascii=False, sort_keys=True) if findings else "none"),
             "## Evidence\n" + "\n".join(f"[{eid}] {text}" for eid, text in evidence)]
    if queries:
        parts.append("## Competency questions (also score question_coverage)\n"
                     + "\n".join(f"- {q['id']}: {q['query']}" for q in queries))
    return [{"role": "system", "content": CRITIQUE_SYSTEM}, {"role": "user", "content": "\n\n".join(parts)}]
