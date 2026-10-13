"""`ontology-build critique` and critique/refine plans.

Stage A is `ontology_core.lint` (free). Stage B judges the version `judge_samples` times (default 3) over
local state only: the ontology, its lint findings, the version's stored evidence excerpts and optional
competency questions. The score is the median of the samples, which damps single-sample judge variance. No
Search egress; the only request is the judge deployment's chat completions (the connected deployment unless
the plan names another one on the same account).
"""

from __future__ import annotations

import json
import math
import re
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from ontology_build import budget, model_client, planning, prompts
from ontology_build.model_client import ChatResult, ModelClient, ReasoningEffort
from ontology_build.propose import ProposeDeps, _Run
from ontology_core import hashing, http, lint, state
from ontology_core.errors import Blocked
from ontology_core.journal import Journal, StateLock
from ontology_core.model import (
    DATATYPE_RANGES, Caps, Config, Estimate, EvidenceRecord, Ontology, Plan, PlanCritique, PlanModel, PlanQueries,
)
from ontology_core.state import StatePaths

Kind = Literal["critique", "refine"]
DEFAULT_ROUNDS = 3
MAX_ROUNDS = 5
DEFAULT_JUDGE_SAMPLES = 3
MAX_JUDGE_SAMPLES = 5
DEFAULT_NOISE_MARGIN = 2
"""Rubric points a refine round's median total may drop before the round is rejected (`no_improvement`)."""
MAX_NOISE_MARGIN = 10
REFINE_GROWTH = 1.5
"""Rounds after the first reserve this factor on round one's input (revised ontologies can grow)."""
EVIDENCE_TOP_CLASSES = 8
EVIDENCE_PER_CLASS = 3
EVIDENCE_MAX = 60
EVIDENCE_EXCERPT_CHARS = 400
MAX_OPS = 20
MAX_QUERIES = 200
OPS = ("add_object_property", "add_datatype_property", "narrow_class", "split_class", "rename", "drop_property",
       "drop_class")
_FINGERPRINT = re.compile(r"^[a-z][a-z0-9_]*:\S+$")


@dataclass(frozen=True)
class CritiquePlanRequest:
    """`ontology-build plan --kind critique|refine` flags."""

    kind: Kind
    max_spend_usd: float
    version: int | None = None
    max_rounds: int = DEFAULT_ROUNDS
    queries: Path | None = None
    reasoning_effort: ReasoningEffort = "low"
    max_output_tokens: int = planning.DEFAULT_PROPOSAL_MAX_OUTPUT
    max_tokens: int | None = None
    judge_samples: int = DEFAULT_JUDGE_SAMPLES
    noise_margin: int = DEFAULT_NOISE_MARGIN
    judge_deployment: str | None = None
    judge_reasoning_effort: ReasoningEffort | None = None
    judge_input_price_per_1m: float | None = None
    judge_output_price_per_1m: float | None = None


@dataclass(frozen=True)
class RunRequest:
    plan_id: str
    approved_budget_usd: float | None
    approve_model_calls: bool


# --------------------------------------------------------------------------- inputs


def load_queries(path: Path) -> list[dict[str, str]]:
    """One JSON object per line with non-empty string `id` and `query` (blank lines skipped, IDs unique).

    Raises: Blocked("QUERY_FILE_INVALID").
    """
    source = Path(path).expanduser()
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise Blocked("QUERY_FILE_INVALID", f"cannot read {source}: {exc}") from exc
    queries: list[dict[str, str]] = []
    for n, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except ValueError as exc:
            raise Blocked("QUERY_FILE_INVALID", f"{source}:{n} is not JSON") from exc
        if not isinstance(item, dict) or not all(isinstance(item.get(k), str) and item[k].strip()
                                                 for k in ("id", "query")):
            raise Blocked("QUERY_FILE_INVALID", f"{source}:{n} needs string `id` and `query`")
        if any(q["id"] == item["id"] for q in queries):
            raise Blocked("QUERY_FILE_INVALID", f"{source}:{n} repeats id {item['id']!r}")
        queries.append({"id": item["id"].strip(), "query": item["query"].strip()})
    if not queries or len(queries) > MAX_QUERIES:
        raise Blocked("QUERY_FILE_INVALID", f"{source} must hold 1-{MAX_QUERIES} questions, found {len(queries)}")
    return queries


def select_evidence(ontology: Ontology, records: list[EvidenceRecord],
                    findings: list[lint.Finding]) -> list[tuple[str, str]]:
    """Local excerpts for the judge: the flagged classes first, then the classes with the most evidence;
    up to `EVIDENCE_PER_CLASS` each, `EVIDENCE_MAX` in total, each cut to `EVIDENCE_EXCERPT_CHARS`."""
    by_id = {r.evidence_id: r for r in records}
    flagged: list[str] = []
    for f in findings:
        for name in f.target.split("->"):
            if name not in flagged:
                flagged.append(name)
    top = [c.name for c in sorted(ontology.classes, key=lambda c: (-len(c.evidence), c.name))[:EVIDENCE_TOP_CLASSES]]
    chosen: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name in flagged + [t for t in top if t not in flagged]:
        cls = ontology.find_class(name)
        if cls is None:
            continue
        for eid in [e for e in sorted(cls.evidence) if e in by_id and e not in seen][:EVIDENCE_PER_CLASS]:
            if len(chosen) >= EVIDENCE_MAX:
                return chosen
            seen.add(eid)
            chosen.append((eid, by_id[eid].excerpt[:EVIDENCE_EXCERPT_CHARS]))
    return chosen


def judge_messages(ontology: Ontology, records: list[EvidenceRecord],
                   queries: list[dict[str, str]] | None) -> tuple[list[prompts.Message], list[lint.Finding]]:
    findings = lint.lint(ontology)
    messages = prompts.critique_messages(ontology, [f.to_dict() for f in findings],
                                         select_evidence(ontology, records, findings), queries)
    return messages, findings


def _input_chars(messages: list[prompts.Message]) -> int:
    return sum(len(m["content"]) for m in messages)


# --------------------------------------------------------------------------- plan


def _queries_record(path: Path | None) -> tuple[PlanQueries | None, list[dict[str, str]] | None]:
    if path is None:
        return None, None
    source = Path(path).expanduser().resolve()
    queries = load_queries(source)
    return PlanQueries(path=str(source), sha256=hashing.sha256_file(source), count=len(queries)), queries


def build_plan(paths: StatePaths, config: Config, request: CritiquePlanRequest) -> Plan:
    """Price a critique (one round) or refine (`max_rounds` rounds) of `request.version` (default: latest), at
    `judge_samples` judge calls per round, on the judge deployment (default: the connected one) and its prices
    (default: the connected prices).

    Raises: VERSION_NOT_FOUND, QUERY_FILE_INVALID, STATE_INCOMPATIBLE.
    """
    n = state.resolve_version(paths, request.version)
    meta, ontology = state.load_version(paths, n)
    queries_record, queries = _queries_record(request.queries)
    rounds = 1 if request.kind == "critique" else max(1, min(request.max_rounds, MAX_ROUNDS))
    samples = max(1, min(request.judge_samples, MAX_JUDGE_SAMPLES))
    messages, _findings = judge_messages(ontology, state.load_evidence(paths, n), queries)
    own = request.judge_deployment in (None, config.model.deployment)
    effort = request.judge_reasoning_effort or request.reasoning_effort
    plan = Plan(
        tool_version=state.tool_version(), plan_id="", created_at=state.utc_now(), tenant_id=config.tenant_id,
        grz=None, seed=None, sampling=None,
        model=PlanModel(endpoint=config.model.endpoint,
                        deployment=config.model.deployment if own else str(request.judge_deployment),
                        reasoning_effort=effort,
                        proposal_max_output_tokens=request.max_output_tokens,
                        audit_max_output_tokens=request.max_output_tokens,
                        input_price_per_1m=_or(request.judge_input_price_per_1m, config.model.input_price_per_1m),
                        output_price_per_1m=_or(request.judge_output_price_per_1m,
                                                config.model.output_price_per_1m),
                        model_name=config.model.model_name if own else None,
                        model_version=config.model.model_version if own else None),
        prompt_sha256=prompts.critique_prompt_sha256(),
        estimate=Estimate(calls=0, input_tokens=0, output_tokens=0, usd=0.0),
        caps=Caps(max_spend_usd=request.max_spend_usd, max_tokens=request.max_tokens),
        critique=PlanCritique(kind=request.kind, base_version=n, base_schema_id=meta.schema_id, max_rounds=rounds,
                              max_output_tokens=request.max_output_tokens, queries=queries_record,
                              judge_samples=samples,
                              noise_margin=max(0, min(request.noise_margin, MAX_NOISE_MARGIN)),
                              judge_deployment=None if own else request.judge_deployment,
                              judge_reasoning_effort=None if effort == request.reasoning_effort else effort),
    )
    reserved = reservations(plan, _input_chars(messages))
    total = sum(r.reserve_tokens for r in reserved)
    output_tokens = request.max_output_tokens * len(reserved)
    plan.estimate = Estimate(calls=len(reserved), input_tokens=total - output_tokens, output_tokens=output_tokens,
                             usd=round(sum(r.reserve_usd for r in reserved), 6))
    return plan.with_id()


def _or(value: float | None, default: float) -> float:
    return default if value is None else value


def reservations(plan: Plan, first_input_chars: int) -> list[budget.Reservation]:
    """One worst-case reservation per judge sample of every round: round one at its measured input, later
    rounds at `REFINE_GROWTH` times that."""
    assert plan.critique is not None
    prices = budget.Prices(plan.model.input_price_per_1m, plan.model.output_price_per_1m)
    return [budget.reserve(state.judge_call(k, j), input_chars=first_input_chars if k == 1
                           else math.ceil(first_input_chars * REFINE_GROWTH),
                           max_output_tokens=plan.critique.max_output_tokens, prices=prices)
            for k in range(1, plan.critique.max_rounds + 1) for j in range(1, plan.critique.judge_samples + 1)]


def plan(paths: StatePaths, request: CritiquePlanRequest) -> dict[str, Any]:
    """Build and save a critique/refine plan. Reads only local state (no Search, no model call)."""
    config = state.load_config(paths)
    built = build_plan(paths, config, request)
    planning.require_within_cap(built, plan_flags(request))
    with StateLock(paths, "plan"):
        planning.save_plan(paths, Journal(paths), built)
    return plan_result(built)


def plan_flags(request: CritiquePlanRequest) -> str:
    """The `plan` flags of `request` other than the cap, each with a leading space."""
    flags = [f"--kind {request.kind}"]
    if request.version is not None:
        flags.append(f"--version {request.version}")
    if request.kind == "refine" and request.max_rounds != DEFAULT_ROUNDS:
        flags.append(f"--max-rounds {request.max_rounds}")
    if request.queries is not None:
        q = str(request.queries)
        flags.append(f'--queries "{q}"' if " " in q else f"--queries {q}")
    if request.reasoning_effort != "low":
        flags.append(f"--reasoning-effort {request.reasoning_effort}")
    if request.max_output_tokens != planning.DEFAULT_PROPOSAL_MAX_OUTPUT:
        flags.append(f"--model-max-output-tokens {request.max_output_tokens}")
    if request.max_tokens is not None:
        flags.append(f"--model-max-tokens {request.max_tokens}")
    if request.judge_samples != DEFAULT_JUDGE_SAMPLES:
        flags.append(f"--judge-samples {request.judge_samples}")
    if request.kind == "refine" and request.noise_margin != DEFAULT_NOISE_MARGIN:
        flags.append(f"--noise-margin {request.noise_margin}")
    if request.judge_deployment is not None:
        flags.append(f"--judge-deployment {request.judge_deployment}")
    if request.judge_reasoning_effort is not None:
        flags.append(f"--judge-reasoning-effort {request.judge_reasoning_effort}")
    if request.judge_input_price_per_1m is not None:
        flags.append(f"--judge-input-price-per-1m {request.judge_input_price_per_1m}")
    if request.judge_output_price_per_1m is not None:
        flags.append(f"--judge-output-price-per-1m {request.judge_output_price_per_1m}")
    return "".join(f" {f}" for f in flags)


def plan_result(plan: Plan) -> dict[str, Any]:
    assert plan.critique is not None
    c = plan.critique
    return {
        "status": "ok",
        "kind": c.kind,
        "plan_id": plan.plan_id,
        "version": c.base_version,
        "rounds": c.max_rounds,
        "queries": c.queries.count if c.queries else 0,
        "judge_samples": c.judge_samples,
        "noise_margin": c.noise_margin,
        "judge_deployment": plan.model.deployment,
        "judge_reasoning_effort": plan.model.reasoning_effort,
        "calls": plan.estimate.calls,
        "estimate": {**plan.estimate.__dict__, "expected_usd": planning.expected_usd(plan)},
        "caps": plan.caps.__dict__.copy(),
        "next_step": (f"ontology-build {c.kind} --plan-id {plan.plan_id} --approved-budget-usd "
                      f"{planning.suggested_budget(plan)} --approve-model-calls  # after the user approves"),
    }


def stale_reasons(paths: StatePaths, plan: Plan, config: Config) -> list[str]:
    """Why a critique/refine plan no longer matches local state (empty means fresh)."""
    assert plan.critique is not None
    c = plan.critique
    try:
        current = state.read_record(paths.version_json(c.base_version), state.Version).schema_id
    except Blocked:
        current = None
    queries_sha = None
    if c.queries is not None and Path(c.queries.path).is_file():
        queries_sha = hashing.sha256_file(Path(c.queries.path))
    checks = [
        ("prompt hash", plan.prompt_sha256, prompts.critique_prompt_sha256()),
        ("tool version", plan.tool_version, state.tool_version()),
        ("model endpoint", plan.model.endpoint, config.model.endpoint),
        ("model deployment", plan.model.deployment, c.judge_deployment or config.model.deployment),
        (f"v{c.base_version} schema ID", c.base_schema_id, current),
        ("queries hash", c.queries.sha256 if c.queries else None, queries_sha),
    ]
    return [f"{name} changed: {before} -> {after}" for name, before, after in checks if before != after]


# --------------------------------------------------------------------------- judge output


def _fail(message: str) -> Blocked:
    return Blocked("MODEL_OUTPUT_INVALID", f"critique output invalid: {message}",
                   next_step="rerun the same command to ask again; if it repeats, re-plan with a larger "
                             "`--model-max-output-tokens`")


def _str(item: dict[str, Any], key: str, where: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _fail(f"{where}: `{key}` must be a non-empty string")
    return value.strip()


def _ids(value: Any, local: set[str], where: str, *, required: bool) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(e, str) for e in value):
        raise _fail(f"{where}: `evidence` must be a list of evidence IDs")
    unknown = sorted(set(value) - local)
    if unknown:
        raise _fail(f"{where}: evidence IDs not in this version: {', '.join(unknown[:5])}")
    if required and not value:
        raise _fail(f"{where}: cite at least one evidence ID")
    return sorted(set(value))


def _op(raw: Any, index: int, fingerprints: set[str], local: set[str]) -> dict[str, Any]:
    where = f"ops[{index}]"
    if not isinstance(raw, dict) or raw.get("op") not in OPS:
        raise _fail(f"{where}: `op` must be one of {', '.join(OPS)}")
    kind = raw["op"]
    finding = _str(raw, "finding", where)
    if finding not in fingerprints:
        raise _fail(f"{where}: `finding` {finding!r} is not a reported finding")
    op: dict[str, Any] = {"op": kind, "finding": finding}
    if kind in ("add_object_property", "add_datatype_property"):
        for key in ("name", "domain", "range", "description"):
            op[key] = _str(raw, key, where)
        if kind == "add_datatype_property" and op["range"] not in DATATYPE_RANGES:
            raise _fail(f"{where}: datatype range must be one of {', '.join(DATATYPE_RANGES)}")
        op["evidence"] = _ids(raw.get("evidence"), local, where, required=bool(local))
    elif kind == "narrow_class":
        op["name"], op["description"] = _str(raw, "name", where), _str(raw, "description", where)
    elif kind == "split_class":
        op["name"] = _str(raw, "name", where)
        into = raw.get("into")
        if not isinstance(into, list) or not into:
            raise _fail(f"{where}: `into` must be a non-empty list")
        op["into"] = [{"name": _str(i, "name", where), "description": _str(i, "description", where)}
                      if isinstance(i, dict) else _raise(_fail(f"{where}: `into` items are objects"))
                      for i in into]
        reassign = raw.get("reassign", {})
        targets = {i["name"] for i in op["into"]}
        if not isinstance(reassign, dict) or not all(isinstance(k, str) and v in targets
                                                     for k, v in reassign.items()):
            raise _fail(f"{where}: `reassign` maps property names to one of the `into` classes")
        op["reassign"] = dict(sorted(reassign.items()))
    elif kind == "rename":
        op["from"], op["to"] = _str(raw, "from", where), _str(raw, "to", where)
    else:
        op["name"] = _str(raw, "name", where)
        if raw.get("merge_into") not in (None, ""):
            op["merge_into"] = _str(raw, "merge_into", where)
    return op


def _raise(exc: Exception) -> Any:
    raise exc


def _reason(exc: Blocked) -> str:
    return exc.error.removeprefix("critique output invalid: ")


def validate(parsed: dict[str, Any], lint_findings: list[lint.Finding], local_ids: set[str], *,
             with_queries: bool) -> dict[str, Any]:
    """Check the judge JSON and return `{scores, total, max_total, findings, ops, judge_warnings}` where
    `findings` merges lint and judge findings by fingerprint (the higher severity wins).

    Only the envelope is strict: `scores`, a `findings` list and an `ops` list of at most MAX_OPS. One bad
    item never fails the round. A malformed finding (not an object, a fingerprint that is not `kind:Target`,
    an unknown severity, no rationale, unknown evidence IDs) is dropped with `finding_invalid`; an op that
    addresses a dropped finding is skipped with `op_for_invalid_finding`; any other malformed op (unknown op,
    unreported finding, missing field, no or unknown evidence) is skipped with `op_invalid`. Skipped ops are
    never applied, so grounding holds.

    Raises: Blocked("MODEL_OUTPUT_INVALID") for an invalid envelope.
    """
    rubric = list(prompts.RUBRIC) + ([prompts.QUESTION_RUBRIC] if with_queries else [])
    scores = parsed.get("scores")
    if not isinstance(scores, dict) or set(scores) != set(rubric):
        raise _fail(f"`scores` must have exactly {', '.join(rubric)}")
    for key, value in scores.items():
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
            raise _fail(f"score {key} must be an integer 1-5")
    merged: dict[str, dict[str, Any]] = {
        f.fingerprint: {"fingerprint": f.fingerprint, "severity": f.severity, "source": "lint",
                        "rationale": f.message, "evidence": []} for f in lint_findings}
    raw_findings = parsed.get("findings")
    if not isinstance(raw_findings, list):
        raise _fail("`findings` must be a list")
    warnings: list[str] = []
    dropped: set[str] = set()
    for i, raw in enumerate(raw_findings):
        where = f"findings[{i}]"
        fingerprint = raw.get("fingerprint") if isinstance(raw, dict) else None
        severity = raw.get("severity") if isinstance(raw, dict) else None
        if not isinstance(fingerprint, str) or not _FINGERPRINT.match(fingerprint.strip()) \
                or severity not in lint.SEVERITIES:
            if isinstance(fingerprint, str) and fingerprint.strip():
                dropped.add(fingerprint.strip())
            warnings.append(f"finding_invalid: {where} {fingerprint!r} (needs `kind:Target` and a severity of "
                            "high, medium or low)")
            continue
        fingerprint = fingerprint.strip()
        try:
            rationale = _str(raw, "rationale", where)
            evidence = _ids(raw.get("evidence", []), local_ids, where, required=False)
        except Blocked as exc:
            if fingerprint not in merged:
                dropped.add(fingerprint)
            warnings.append(f"finding_invalid: {_reason(exc)}")
            continue
        old = merged.get(fingerprint)
        if old is None:
            merged[fingerprint] = {"fingerprint": fingerprint, "severity": severity, "source": "judge",
                                   "rationale": rationale, "evidence": evidence}
        else:
            if lint.SEVERITIES.index(severity) < lint.SEVERITIES.index(old["severity"]):
                old["severity"] = severity
            old["source"] = "both" if old["source"] == "lint" else old["source"]
            old["rationale"] = rationale
            old["evidence"] = sorted(set(old["evidence"]) | set(evidence))
    raw_ops = parsed.get("ops")
    if not isinstance(raw_ops, list) or len(raw_ops) > MAX_OPS:
        raise _fail(f"`ops` must be a list of at most {MAX_OPS} change ops")
    ops = []
    for i, raw in enumerate(raw_ops):
        finding = raw.get("finding") if isinstance(raw, dict) else None
        if isinstance(finding, str) and finding.strip() in dropped - set(merged):
            warnings.append(f"op_for_invalid_finding: ops[{i}] addresses {finding.strip()!r}")
            continue
        try:
            ops.append(_op(raw, i, set(merged), local_ids))
        except Blocked as exc:
            warnings.append(f"op_invalid: {_reason(exc)}")
    findings = sorted(merged.values(), key=lambda f: (lint.SEVERITIES.index(f["severity"]), f["fingerprint"]))
    return {"scores": {k: scores[k] for k in rubric}, "total": sum(scores.values()), "max_total": 5 * len(rubric),
            "findings": findings, "ops": ops, "judge_warnings": warnings}


# --------------------------------------------------------------------------- run


def egress_policy(config: Config, deployment: str | None = None) -> http.EgressPolicy:
    """Critique and refine reach only the judge deployment on the connected account (no Search, no ARM)."""
    return http.EgressPolicy(model_endpoint=config.model.endpoint,
                             model_deployment=deployment or config.model.deployment)


def default_deps(paths: StatePaths, config: Config, deployment: str | None = None) -> ProposeDeps:
    """Live collaborators for the judge `deployment` (default: the connected one)."""
    from ontology_core import azure_auth

    judge_deployment = deployment or config.model.deployment
    policy = egress_policy(config, judge_deployment)

    def client() -> ModelClient:
        azure_auth.require_tenant(config.tenant_id, config.tenant_name)
        return ModelClient(endpoint=config.model.endpoint, deployment=judge_deployment,
                           tenant_id=config.tenant_id, policy=policy)

    def no_reader() -> Any:  # pragma: no cover - critique never reads Search
        raise Blocked("INTERNAL_ERROR", "critique does not read the GRZ sidecar")

    return ProposeDeps(reader=no_reader, client=client)


def critique_id_for_plan(plan_id: str, round_: int | None = None) -> str:
    base = "crit-" + plan_id.removeprefix("oplan-")
    return base if round_ is None else f"{base}-r{round_}"


def critique_id(plan: Plan, round_: int | None = None) -> str:
    return critique_id_for_plan(plan.plan_id, round_)


def start(paths: StatePaths, request: RunRequest, kind: Kind, deps: ProposeDeps | None) -> tuple[Plan, _Run]:
    """Checks shared by `critique` and `refine` (caller holds the lock): plan kind, not yet completed,
    fresh, approved; journals `run_started` once and returns the call runner."""
    config = state.load_config(paths)
    journal = Journal(paths)
    plan = state.load_plan(paths, request.plan_id)
    if plan.critique is None or plan.critique.kind != kind:
        actual = plan.critique.kind if plan.critique else "propose"
        raise Blocked("PLAN_ID_MISMATCH", f"plan {plan.plan_id} is a {actual} plan, not a {kind} plan",
                      next_step=f"ontology-build plan --kind {kind} --model-max-spend-usd <usd>",
                      details={"plan_id": plan.plan_id, "kind": actual})
    if any(journal.events("run_finished", plan_id=plan.plan_id, status="completed")):
        n = plan.critique.base_version
        created = [e["version"] for e in journal.events("version_created", plan_id=plan.plan_id)]
        n = created[-1] if created and kind == "refine" else n
        raise Blocked("PLAN_ALREADY_EXECUTED", f"plan {plan.plan_id} has already run", n=n,
                      details={"plan_id": plan.plan_id, "version": n})
    reasons = stale_reasons(paths, plan, config)
    if reasons:
        raise Blocked("PLAN_STALE", f"plan {plan.plan_id} is stale: " + "; ".join(reasons),
                      details={"plan_id": plan.plan_id, "reasons": reasons})
    if not request.approve_model_calls or request.approved_budget_usd is None:
        raise Blocked("APPROVAL_REQUIRED",
                      f"plan {plan.plan_id} needs explicit approval for up to ${planning.suggested_budget(plan)} "
                      "of model calls", id=plan.plan_id, usd=planning.suggested_budget(plan),
                      details={"plan_id": plan.plan_id, "estimate_usd": plan.estimate.usd,
                               "max_spend_usd": plan.caps.max_spend_usd})
    budget.check_approval(approved_budget_usd=request.approved_budget_usd, max_spend_usd=plan.caps.max_spend_usd,
                          estimate_usd=plan.estimate.usd)
    if not any(journal.events("run_started", plan_id=plan.plan_id)):
        journal.append("run_started", plan_id=plan.plan_id, approved_budget_usd=request.approved_budget_usd,
                       actor=state.actor())
    runner = _Run(paths, journal, plan, request.approved_budget_usd, None,
                  deps or default_deps(paths, config, plan.model.deployment))
    return plan, runner


def plan_queries(plan: Plan) -> list[dict[str, str]] | None:
    assert plan.critique is not None
    return load_queries(Path(plan.critique.queries.path)) if plan.critique.queries else None


def _median(values: list[int]) -> int | float:
    m = statistics.median(values)
    return int(m) if float(m).is_integer() else float(m)


def aggregate(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Combine validated judge samples: `scores` and `total` are medians (per dimension, and of the sample
    totals); `findings`, `ops` and `judge_warnings` come from the representative sample, the one whose total
    is closest to the median (the earliest on a tie). `samples` keeps every sample's scores and total."""
    total = _median([s["total"] for s in samples])
    pick = min(range(len(samples)), key=lambda i: (abs(samples[i]["total"] - total), i))
    rep = samples[pick]
    return {"scores": {k: _median([s["scores"][k] for s in samples]) for k in rep["scores"]}, "total": total,
            "max_total": rep["max_total"], "findings": rep["findings"], "ops": rep["ops"],
            "judge_warnings": rep["judge_warnings"], "representative_sample": pick + 1,
            "samples": [{"sample": i + 1, "scores": s["scores"], "total": s["total"]}
                        for i, s in enumerate(samples)]}


def question_coverage(record: dict[str, Any]) -> int | float | None:
    """The (median) question_coverage score of a critique record, or None when it had no questions."""
    return record["scores"].get(prompts.QUESTION_RUBRIC)


def judge(paths: StatePaths, runner: _Run, plan: Plan, version: int, round_: int | None) -> dict[str, Any]:
    """Lint `version`, make (or reuse) the plan's `judge_samples` judge calls, score by the median and write
    `critiques/<id>.json`. Returns the record."""
    _meta, ontology = state.load_version(paths, version)
    meta = _meta
    records = state.load_evidence(paths, version)
    queries = plan_queries(plan)
    messages, findings = judge_messages(ontology, records, queries)
    local = {r.evidence_id for r in records}
    call_round = round_ or 1

    def parse(result: ChatResult) -> dict[str, Any]:
        return validate(model_client.parse_json_object(result), findings, local, with_queries=bool(queries))

    assert plan.critique is not None
    judged = aggregate([runner.call(state.judge_call(call_round, j), messages,
                                    paths.judge_request(plan.plan_id, call_round, j),
                                    paths.judge_response(plan.plan_id, call_round, j),
                                    plan.critique.max_output_tokens, parse=parse)
                        for j in range(1, plan.critique.judge_samples + 1)])
    cid = critique_id(plan, round_)
    record = {
        "critique_id": cid, "plan_id": plan.plan_id, "round": round_, "version": version,
        "schema_id": meta.schema_id, "created_at": state.utc_now(), "prompt_sha256": plan.prompt_sha256,
        "queries": len(queries) if queries else 0, "lint": [f.to_dict() for f in findings], **judged,
    }
    path = paths.critique(cid)
    if path.is_file():
        existing = state.read_json(path)
        if existing.get("schema_id") == meta.schema_id:
            return existing
    sha = state.write_json(path, record)
    runner.journal.append("artifact_written", path=paths.relative(path), sha256=sha)
    return record


def summary(record: dict[str, Any]) -> dict[str, Any]:
    """The short view of a critique record: median score, sample totals, finding counts, top 3 findings, op
    count."""
    counts = {s: sum(1 for f in record["findings"] if f["severity"] == s) for s in lint.SEVERITIES}
    return {"critique_id": record["critique_id"], "version": record["version"], "scores": record["scores"],
            "total": record["total"], "max_total": record["max_total"],
            "sample_totals": [x["total"] for x in record.get("samples", [])], "findings": counts,
            "top_findings": [{"fingerprint": f["fingerprint"], "severity": f["severity"],
                              "rationale": f["rationale"]} for f in record["findings"][:3]],
            "ops": len(record["ops"])}


def run(paths: StatePaths, request: RunRequest, deps: ProposeDeps | None = None) -> dict[str, Any]:
    """Run an approved critique plan: lint + one judge call, then write `critiques/<id>.json`.

    Raises: CONFIG_MISSING, STATE_LOCKED, PLAN_NOT_FOUND, PLAN_ID_MISMATCH, PLAN_STALE, PLAN_ALREADY_EXECUTED,
        APPROVAL_REQUIRED, BUDGET_*, RUN_INCOMPLETE, MODEL_*, QUERY_FILE_INVALID, AZ_NOT_SIGNED_IN,
        TENANT_MISMATCH.
    """
    state.load_config(paths)  # CONFIG_MISSING before the lock creates the state dir
    with StateLock(paths, "critique"):
        plan, runner = start(paths, request, "critique", deps)
        assert plan.critique is not None
        try:
            record = judge(paths, runner, plan, plan.critique.base_version, None)
        except Blocked as exc:
            _finish_on(runner, exc)
            raise
        runner.finish("completed")
    return {"status": "ok", **summary(record), "spent_usd": round(runner.ledger().spent_usd, 6),
            "approved_budget_usd": request.approved_budget_usd,
            "next_step": (f"ontology-build revise --from-critique {record['critique_id']}" if record["ops"]
                          else f"ontology-build review --version {record['version']}")}


def _finish_on(runner: _Run, exc: Blocked) -> None:
    if exc.code == "BUDGET_EXHAUSTED":
        runner.finish("budget_exhausted")
    elif exc.code != "RUN_INCOMPLETE" and exc.code.startswith(("MODEL_", "EMPTY_")):
        runner.finish("blocked")


def load(paths: StatePaths, critique_id_: str) -> dict[str, Any]:
    """A saved critique record. Raises: Blocked("VERSION_NOT_FOUND") when there is no such critique."""
    path = paths.critique(critique_id_)
    if not re.fullmatch(r"crit-[0-9a-f]{16}(-r[1-9])?", critique_id_) or not path.is_file():
        raise Blocked("VERSION_NOT_FOUND", f"no critique {critique_id_!r}",
                      next_step="ontology-build status  # shows the latest critique")
    return state.read_json(path)


def latest(paths: StatePaths) -> dict[str, Any] | None:
    """The newest critique summary (by creation time), or None."""
    if not paths.critiques_dir.is_dir():
        return None
    records = [state.read_json(p) for p in paths.critiques_dir.glob("crit-*.json")]
    if not records:
        return None
    return summary(max(records, key=lambda r: (r["created_at"], r["critique_id"])))
