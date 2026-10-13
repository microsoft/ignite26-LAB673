"""Plan building, saving and staleness.

The plan ID is `hashing.plan_id(plan.to_dict())` (excludes `plan_id`, `created_at`, `estimate`). The
sampling seed is `hashing.sampling_seed(...)`, computed from the plan inputs without sampling output.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from pathlib import Path

from ontology_build import budget, grz_reader, prompts, sampler
from ontology_build.grz_reader import GrzReader
from ontology_build.model_client import ReasoningEffort
from ontology_core import hashing, hygiene, owl_read, state
from ontology_core.errors import Blocked
from ontology_core.journal import Journal
from ontology_core.model import (
    Caps, Config, Estimate, Ontology, Plan, PlanGrz, PlanModel, PlanSeed, Sample, Sampling,
)
from ontology_core.state import StatePaths

DEFAULT_PROPOSAL_MAX_OUTPUT = 8000
AUDIT_OUTPUT_MULTIPLIER = 2
PASSAGE_OVERHEAD_CHARS = 16
"""`[E0123456789] ` plus the newline around each excerpt."""
COMMUNITY_HEADER_CHARS = 160
"""`## Community <64-hex id> (level n, m chunks) — label: …` upper bound."""


@dataclass(frozen=True)
class PlanRequest:
    """`ontology-build plan` flags (and the `ontology_plan_estimate` MCP input)."""

    max_spend_usd: float
    seed: Path | None = None
    level: int | None = None
    passages: int | None = None
    excerpt_chars: int = 1200
    shard_chars: int = 60000
    reasoning_effort: ReasoningEffort = "low"
    max_output_tokens: int = DEFAULT_PROPOSAL_MAX_OUTPUT
    max_tokens: int | None = None


def load_seed(paths: StatePaths, seed: Path | None) -> tuple[Ontology | None, dict[str, str] | None]:
    """The seed ontology (all items `seed=True`) and its plan record `{path, sha256, format}`. With no `seed`
    path, uses v0 if an `import --as-seed` created it; otherwise `(None, None)`.

    Raises: owl_read import codes (IMPORT_*), EMPTY_ONTOLOGY.
    """
    if seed is None:
        if not paths.version_json(0).is_file():
            return None, None
        _meta, ontology = state.load_version(paths, 0)
        record = {"path": paths.relative(paths.ontology(0)), "sha256": hashing.sha256_file(paths.ontology(0)),
                  "format": "json"}
        return _as_seed(ontology), record
    source = Path(seed).expanduser().resolve()
    read = owl_read.read_file(source)
    ontology, _report = hygiene.clean(read.raw, None, None, version=0, origin="import")
    record = {"path": str(source), "sha256": hashing.sha256_file(source), "format": source.suffix.lower().lstrip(".")}
    return _as_seed(ontology), record


def _as_seed(ontology: Ontology) -> Ontology:
    return replace(ontology, classes=[replace(c, seed=True) for c in ontology.classes],
                   properties=[replace(p, seed=True) for p in ontology.properties])


def seed_sha256(paths: StatePaths, plan: Plan) -> str | None:
    """The current hash of the plan's seed file (None when the plan has no seed or the file is gone)."""
    if plan.seed is None:
        return None
    path = seed_path(paths, plan)
    return hashing.sha256_file(path) if path.is_file() else None


def seed_path(paths: StatePaths, plan: Plan) -> Path:
    assert plan.seed is not None
    path = Path(plan.seed.path)
    return path if path.is_absolute() else paths.root / path


def reload_seed(paths: StatePaths, plan: Plan) -> Ontology | None:
    """The seed a saved plan refers to, read the same way `plan` read it."""
    if plan.seed is None:
        return None
    if plan.seed.path == paths.relative(paths.ontology(0)):
        return load_seed(paths, None)[0]
    return load_seed(paths, seed_path(paths, plan))[0]


def shard_input_chars(sample: Sample, *, seed: Ontology | None) -> dict[int, int]:
    """Upper-bound prompt chars per shard: system prompt, community headers and `excerpt_chars` per passage."""
    system = len(prompts.PROPOSAL_SYSTEM.replace("{SEED_BLOCK}", prompts.seed_block(seed)))
    per_passage = sample.excerpt_chars + PASSAGE_OVERHEAD_CHARS
    return {shard.index: system + COMMUNITY_HEADER_CHARS * len(shard.community_ids)
            + per_passage * len(shard.evidence_ids) for shard in sample.shards}


def audit_input_chars(sample: Sample, *, seed: Ontology | None, proposal_max_output_tokens: int,
                      audit_mode: prompts.AuditMode) -> int:
    """Upper-bound audit prompt chars: system prompt, every shard's candidate JSON at its output cap, then the
    evidence section for `audit_mode`."""
    system = len(prompts.AUDIT_SYSTEM.replace("{SEED_BLOCK}", prompts.seed_block(seed)))
    candidates = len(sample.shards) * proposal_max_output_tokens * budget.CHARS_PER_TOKEN
    excerpt = sample.excerpt_chars if audit_mode == "full" else min(sample.excerpt_chars, prompts.CITED_EXCERPT_CHARS)
    return system + candidates + len(sample.passages) * (excerpt + PASSAGE_OVERHEAD_CHARS)


def choose_audit_mode(sample: Sample, *, seed: Ontology | None, proposal_max_output_tokens: int) -> prompts.AuditMode:
    """`full` when the full audit input is estimated at <= `AUDIT_FULL_MAX_TOKENS`, else `cited`."""
    chars = audit_input_chars(sample, seed=seed, proposal_max_output_tokens=proposal_max_output_tokens,
                              audit_mode="full")
    return "full" if math.ceil(chars / budget.CHARS_PER_TOKEN) <= prompts.AUDIT_FULL_MAX_TOKENS else "cited"


def reservations(plan: Plan, sample: Sample, *, seed: Ontology | None) -> dict[str, budget.Reservation]:
    """`{"shard-<k>": ..., "audit": ...}` in call order, priced with the plan's model prices."""
    prices = budget.Prices(plan.model.input_price_per_1m, plan.model.output_price_per_1m)
    out = {f"shard-{k}": budget.reserve(f"shard-{k}", input_chars=chars,
                                        max_output_tokens=plan.model.proposal_max_output_tokens, prices=prices)
           for k, chars in sorted(shard_input_chars(sample, seed=seed).items())}
    chars = audit_input_chars(sample, seed=seed, proposal_max_output_tokens=plan.model.proposal_max_output_tokens,
                              audit_mode=plan.sampling.audit_mode)
    out["audit"] = budget.reserve("audit", input_chars=chars, max_output_tokens=plan.model.audit_max_output_tokens,
                                  prices=prices)
    return out


def rebuild_sample(plan: Plan, representatives: list[grz_reader.Representative],
                   members: list[grz_reader.Membership]) -> Sample:
    """The text-free sample the plan's inputs select, with `plan_id` set."""
    sample = _select(plan.grz.generation_id, plan.grz.manifest_digest, representatives, members,
                     level=plan.sampling.level, passages=plan.sampling.passages,
                     excerpt_chars=plan.sampling.excerpt_chars, shard_chars=plan.sampling.shard_chars)
    sample.plan_id = plan.plan_id
    return sample


def _select(generation_id: str, manifest_digest: str, representatives: list[grz_reader.Representative],
            members: list[grz_reader.Membership], *, level: int, passages: int, excerpt_chars: int,
            shard_chars: int) -> Sample:
    seed_value = hashing.sampling_seed(generation_id=generation_id, manifest_digest=manifest_digest, level=level,
                                       passages=passages, excerpt_chars=excerpt_chars, shard_chars=shard_chars)
    return sampler.select(representatives, members, plan_id_seed=seed_value, level=level, passages=passages,
                          excerpt_chars=excerpt_chars, shard_chars=shard_chars)


def build_plan(config: Config, reader: GrzReader, request: PlanRequest, *,
               seed: tuple[Ontology | None, dict[str, str] | None] = (None, None)) -> tuple[Plan, Sample]:
    """Read manifest/representatives/members, check the manifest, sample, price every call, and return the
    plan (with `plan_id` set) plus the text-free sample.

    Raises:
        GRZ_* codes from the reader and `check_manifest`; LEVEL_OUT_OF_RANGE; PASSAGE_BUDGET_TOO_SMALL.
    """
    seed_ontology, seed_record = seed
    manifest = reader.manifest()
    representatives = reader.representatives()
    members = reader.members(None)
    grz_reader.check_manifest(manifest, representatives, members)
    counts = sampler.levels(representatives)
    level = request.level if request.level is not None else sampler.default_level(representatives)
    communities = counts.get(level, 0)
    if request.passages is not None:
        passages = request.passages
    else:
        available = len({m.chunk_id for m in members if m.level == 0})
        passages = sampler.default_passages(communities, available)
    sample = _select(config.grz.generation_id, manifest.digest, representatives, members, level=level,
                     passages=passages, excerpt_chars=request.excerpt_chars, shard_chars=request.shard_chars)
    audit_mode = choose_audit_mode(sample, seed=seed_ontology, proposal_max_output_tokens=request.max_output_tokens)
    plan = Plan(
        tool_version=state.tool_version(), plan_id="", created_at=state.utc_now(), tenant_id=config.tenant_id,
        grz=PlanGrz(search_endpoint=config.grz.search_endpoint, physical_index=config.grz.physical_index,
                    generation_id=config.grz.generation_id, manifest_digest=manifest.digest),
        seed=PlanSeed(**seed_record) if seed_record else None,
        sampling=Sampling(level=level, communities_at_level=communities, passages=passages,
                          excerpt_chars=request.excerpt_chars, shard_chars=request.shard_chars,
                          shards=len(sample.shards), audit_mode=audit_mode),
        model=PlanModel(endpoint=config.model.endpoint, deployment=config.model.deployment,
                        reasoning_effort=request.reasoning_effort,
                        proposal_max_output_tokens=request.max_output_tokens,
                        audit_max_output_tokens=request.max_output_tokens * AUDIT_OUTPUT_MULTIPLIER,
                        input_price_per_1m=config.model.input_price_per_1m,
                        output_price_per_1m=config.model.output_price_per_1m,
                        model_name=config.model.model_name, model_version=config.model.model_version),
        prompt_sha256=prompts.prompt_sha256(),
        estimate=Estimate(calls=0, input_tokens=0, output_tokens=0, usd=0.0),
        caps=Caps(max_spend_usd=request.max_spend_usd, max_tokens=request.max_tokens),
    )
    reserved = reservations(plan, sample, seed=seed_ontology)
    output_tokens = (plan.model.proposal_max_output_tokens * len(sample.shards) + plan.model.audit_max_output_tokens)
    total_tokens = sum(r.reserve_tokens for r in reserved.values())
    plan.estimate = Estimate(calls=len(reserved), input_tokens=total_tokens - output_tokens,
                             output_tokens=output_tokens, usd=round(sum(r.reserve_usd for r in reserved.values()), 6))
    plan.with_id()
    sample.plan_id = plan.plan_id
    return plan, sample


def save_plan(paths: StatePaths, journal: Journal, plan: Plan) -> Path:
    """Write `plans/<id>.json` and journal `artifact_written` and `plan_saved`. Idempotent for the same ID."""
    if not plan.id_matches():
        raise Blocked("INTERNAL_ERROR", f"plan {plan.plan_id} does not hash to its ID")
    path = paths.plan(plan.plan_id)
    if path.is_file() and any(journal.events("plan_saved", plan_id=plan.plan_id)):
        return path
    sha = state.write_record(path, plan)
    journal.append("artifact_written", path=paths.relative(path), sha256=sha)
    journal.append("plan_saved", plan_id=plan.plan_id, estimate_usd=plan.estimate.usd,
                   max_spend_usd=plan.caps.max_spend_usd)
    return path


def stale_reasons(plan: Plan, config: Config, *, manifest_digest: str, prompt_sha256: str,
                  tool_version: str, seed_sha256: str | None) -> list[str]:
    """Why the plan no longer matches the world (empty list means fresh): generation, manifest digest,
    prompt hash, tool version, model deployment or seed hash changed."""
    checks = [
        ("grz generation", plan.grz.generation_id, config.grz.generation_id),
        ("grz manifest digest", plan.grz.manifest_digest, manifest_digest),
        ("prompt hash", plan.prompt_sha256, prompt_sha256),
        ("tool version", plan.tool_version, tool_version),
        ("model endpoint", plan.model.endpoint, config.model.endpoint),
        ("model deployment", plan.model.deployment, config.model.deployment),
        ("seed hash", plan.seed.sha256 if plan.seed else None, seed_sha256),
    ]
    return [f"{name} changed: {before} -> {after}" for name, before, after in checks if before != after]


def require_fresh(plan: Plan, config: Config, *, manifest_digest: str, prompt_sha256: str,
                  tool_version: str, seed_sha256: str | None) -> None:
    """Raises:
        Blocked("PLAN_STALE"): `stale_reasons` is non-empty (reasons in `details`).
    """
    reasons = stale_reasons(plan, config, manifest_digest=manifest_digest, prompt_sha256=prompt_sha256,
                            tool_version=tool_version, seed_sha256=seed_sha256)
    if reasons:
        raise Blocked("PLAN_STALE", f"plan {plan.plan_id} is stale: " + "; ".join(reasons),
                      details={"plan_id": plan.plan_id, "reasons": reasons})


def suggested_budget(plan: Plan) -> str:
    """The estimate rounded up to the cent, as the approval amount to show the user."""
    return f"{min(math.ceil(plan.estimate.usd * 100) / 100, plan.caps.max_spend_usd):.2f}"


def expected_usd(plan: Plan) -> float:
    """The estimate's tokens at their own prices (input at the input price, output at the output price),
    where `estimate.usd` is the worst-case bound that prices every token at the higher of the two."""
    return round((plan.estimate.input_tokens * plan.model.input_price_per_1m
                  + plan.estimate.output_tokens * plan.model.output_price_per_1m) / 1e6, 6)


def minimum_cap(plan: Plan) -> str:
    """The smallest `--model-max-spend-usd`, in whole cents, that covers the estimate."""
    return f"{math.ceil(round(plan.estimate.usd * 100, 6)) / 100:.2f}"


def plan_flags(request: PlanRequest) -> str:
    """The non-default `plan` flags of `request` other than the cap, each with a leading space."""
    defaults = PlanRequest(max_spend_usd=0)
    flags: list[str] = []
    if request.seed is not None:
        seed = str(request.seed)
        flags.append(f'--seed "{seed}"' if " " in seed else f"--seed {seed}")
    for flag, name in (("--level", "level"), ("--passages", "passages"), ("--excerpt-chars", "excerpt_chars"),
                       ("--shard-chars", "shard_chars"), ("--reasoning-effort", "reasoning_effort"),
                       ("--model-max-output-tokens", "max_output_tokens"), ("--model-max-tokens", "max_tokens")):
        value = getattr(request, name)
        if value is not None and value != getattr(defaults, name):
            flags.append(f"{flag} {value}")
    return "".join(f" {f}" for f in flags)


def require_within_cap(plan: Plan, request: PlanRequest | str) -> None:
    """Raises:
        Blocked("BUDGET_CAP_BELOW_ESTIMATE"): the worst-case estimate is above `--model-max-spend-usd`, so no
        approved budget could satisfy the run. `next_step` is the same plan with the minimum cap; `request` is the
        propose request, or the other `plan` flags as a string (critique/refine plans).
    """
    if plan.estimate.usd <= plan.caps.max_spend_usd + 1e-9:
        return
    cap = minimum_cap(plan)
    raise Blocked("BUDGET_CAP_BELOW_ESTIMATE",
                  f"Estimated cost: up to ${plan.estimate.usd:.2f} (expected ~${expected_usd(plan):.2f}) is above "
                  f"the ${plan.caps.max_spend_usd:.2f} cap. The estimate is a worst-case bound (every token priced "
                  "at the higher of the input/output prices), and propose needs a budget of at least that bound",
                  min_cap=cap, flags=request if isinstance(request, str) else plan_flags(request),
                  details={"estimate_usd": plan.estimate.usd, "expected_usd": expected_usd(plan),
                           "max_spend_usd": plan.caps.max_spend_usd, "minimum_cap_usd": float(cap)})


def result(plan: Plan) -> dict[str, object]:
    """The verb's `--json` result: `{status:"ok", plan_id, level, passages, shards, calls, estimate, caps,
    next_step}` where next_step is the propose command with the approval flags. `estimate.usd` is the
    worst-case bound; `estimate.expected_usd` prices input and output tokens at their own prices."""
    assert plan.sampling is not None
    return {
        "status": "ok",
        "plan_id": plan.plan_id,
        "level": plan.sampling.level,
        "passages": plan.sampling.passages,
        "shards": plan.sampling.shards,
        "calls": plan.estimate.calls,
        "estimate": {**plan.estimate.__dict__, "expected_usd": expected_usd(plan)},
        "caps": plan.caps.__dict__.copy(),
        "next_step": (f"ontology-build propose --plan-id {plan.plan_id} --approved-budget-usd "
                      f"{suggested_budget(plan)} --approve-model-calls  # after the user approves"),
    }
