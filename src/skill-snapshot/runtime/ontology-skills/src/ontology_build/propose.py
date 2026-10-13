"""Run and resume a plan."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ontology_build import budget, grz_reader, model_client, planning, prompts, sampler
from ontology_build.grz_reader import GrzReader
from ontology_build.model_client import ModelClient
from ontology_core import azure_auth, hashing, http, hygiene, state
from ontology_core import diff as diff_mod
from ontology_core.errors import Blocked
from ontology_core.journal import Journal, StateLock
from ontology_core.model import Config, EvidenceRecord, Ontology, Passage, Plan, Sample, Version, VersionModel
from ontology_core.state import StatePaths


@dataclass(frozen=True)
class ProposeRequest:
    plan_id: str
    approved_budget_usd: float | None
    approve_model_calls: bool


@dataclass
class ProposeDeps:
    """Injected collaborators so tests run offline with fixtures."""

    reader: Callable[[], GrzReader]
    client: Callable[[], ModelClient]


def egress_policy(config: Config) -> http.EgressPolicy:
    """The allowlist for a propose run: the sidecar index and the model deployment from config."""
    return http.EgressPolicy(search_endpoint=config.grz.search_endpoint, physical_index=config.grz.physical_index,
                             model_endpoint=config.model.endpoint, model_deployment=config.model.deployment,
                             subscription_id=config.model.subscription_id,
                             resource_group=config.model.resource_group)


def default_deps(paths: StatePaths, config: Config) -> ProposeDeps:
    """Live collaborators: the signed-in tenant must match config before anything is read or sent."""
    policy = egress_policy(config)

    def reader() -> GrzReader:
        azure_auth.require_tenant(config.tenant_id, config.tenant_name)
        descriptor = grz_reader.load_descriptor(paths.descriptor)
        return GrzReader(descriptor, grz_reader.live_search(descriptor, config.tenant_id, policy))

    def client() -> ModelClient:
        return ModelClient(endpoint=config.model.endpoint, deployment=config.model.deployment,
                           tenant_id=config.tenant_id, policy=policy)

    return ProposeDeps(reader=reader, client=client)


def produced_version(journal: Journal, plan_id: str) -> int | None:
    """The version a completed run of `plan_id` created, or None if it has not completed."""
    if not any(journal.events("run_finished", plan_id=plan_id, status="completed")):
        return None
    created = [e["version"] for e in journal.events("version_created", plan_id=plan_id)]
    return created[-1] if created else None


def run(paths: StatePaths, request: ProposeRequest, deps: ProposeDeps | None = None) -> dict[str, Any]:
    """Execute the propose steps under `StateLock(paths, "propose")`. Rerunning the same request resumes.

    Returns `{status:"ok", version, schema_id, classes, properties, spent_usd, approved_budget_usd,
    dropped:{reason: n}, next_step}`.

    Raises:
        CONFIG_MISSING, STATE_LOCKED, PLAN_NOT_FOUND, PLAN_ID_MISMATCH, PLAN_STALE,
        APPROVAL_REQUIRED (missing `approve_model_calls` or budget), BUDGET_ABOVE_PLAN_CAP,
        BUDGET_BELOW_ESTIMATE, PLAN_ALREADY_EXECUTED, BUDGET_EXHAUSTED, RUN_INCOMPLETE (unknown outcome),
        GRZ_*, MODEL_*, AZ_NOT_SIGNED_IN, TENANT_MISMATCH.
    """
    config = state.load_config(paths)
    journal = Journal(paths)
    with StateLock(paths, "propose"):
        plan = state.load_plan(paths, request.plan_id)
        if plan.critique is not None or plan.grz is None or plan.sampling is None:
            kind = plan.critique.kind if plan.critique else "critique"
            raise Blocked("PLAN_ID_MISMATCH", f"plan {plan.plan_id} is a {kind} plan, not a propose plan",
                          next_step=f"ontology-build {kind} --plan-id {plan.plan_id} ...",
                          details={"plan_id": plan.plan_id, "kind": kind})
        done = produced_version(journal, plan.plan_id)
        if done is not None:
            raise Blocked("PLAN_ALREADY_EXECUTED", f"plan {plan.plan_id} already produced v{done}", n=done,
                          details={"plan_id": plan.plan_id, "version": done})
        freshness = {"prompt_sha256": prompts.prompt_sha256(), "tool_version": state.tool_version(),
                     "seed_sha256": planning.seed_sha256(paths, plan)}
        planning.require_fresh(plan, config, manifest_digest=plan.grz.manifest_digest, **freshness)
        if not request.approve_model_calls or request.approved_budget_usd is None:
            raise Blocked("APPROVAL_REQUIRED",
                          f"plan {plan.plan_id} needs explicit approval for up to "
                          f"${planning.suggested_budget(plan)} of model calls",
                          id=plan.plan_id, usd=planning.suggested_budget(plan),
                          details={"plan_id": plan.plan_id, "estimate_usd": plan.estimate.usd,
                                   "max_spend_usd": plan.caps.max_spend_usd})
        budget.check_approval(approved_budget_usd=request.approved_budget_usd,
                              max_spend_usd=plan.caps.max_spend_usd, estimate_usd=plan.estimate.usd)
        deps = deps or default_deps(paths, config)
        reader = deps.reader()
        manifest = reader.manifest()
        planning.require_fresh(plan, config, manifest_digest=manifest.digest, **freshness)
        if not any(journal.events("run_started", plan_id=plan.plan_id)):
            journal.append("run_started", plan_id=plan.plan_id, approved_budget_usd=request.approved_budget_usd,
                           actor=state.actor())
        return _Run(paths, journal, plan, request.approved_budget_usd, reader, deps).execute()


class _Run:
    """One propose attempt for a fresh, approved plan; the caller holds the lock."""

    def __init__(self, paths: StatePaths, journal: Journal, plan: Plan, approved_budget_usd: float,
                 reader: GrzReader | None, deps: ProposeDeps) -> None:
        self.paths = paths
        self.journal = journal
        self.plan = plan
        self.approved = approved_budget_usd
        self.reader = reader
        self.deps = deps
        self.prices = budget.Prices(plan.model.input_price_per_1m, plan.model.output_price_per_1m)
        self._client: ModelClient | None = None

    @property
    def client(self) -> ModelClient:
        if self._client is None:
            self._client = self.deps.client()
        return self._client

    def ledger(self) -> budget.Ledger:
        return budget.Ledger.from_journal(self.journal.read(), self.plan.plan_id)

    def finish(self, status: str) -> None:
        self.journal.append("run_finished", plan_id=self.plan.plan_id, status=status,
                            spent_usd=round(self.ledger().spent_usd, 6))

    def execute(self) -> dict[str, Any]:
        try:
            return self._execute()
        except Blocked as exc:
            if exc.code == "BUDGET_EXHAUSTED":
                self.finish("budget_exhausted")
            elif exc.code != "RUN_INCOMPLETE" and exc.code.startswith(("MODEL_", "EMPTY_")):
                self.finish("blocked")
            raise

    def _execute(self) -> dict[str, Any]:
        plan = self.plan
        representatives = self.reader.representatives()
        members = self.reader.members(None)
        sample = self.load_sample(planning.rebuild_sample(plan, representatives, members))
        seed = planning.reload_seed(self.paths, plan)
        labels = {r.community_id: r.label_hint for r in representatives if r.label_hint}
        member_counts = {r.community_id: r.member_count for r in representatives}
        candidates = []
        for shard in sample.shards:
            messages = prompts.proposal_messages(shard, sample.passages, seed=seed, labels=labels,
                                                 member_counts=member_counts)
            candidates.append(self.call(f"shard-{shard.index}", messages, self.paths.shard_request(plan.plan_id, shard.index),
                                        self.paths.shard_response(plan.plan_id, shard.index),
                                        plan.model.proposal_max_output_tokens))
        messages = prompts.audit_messages(candidates, sample.passages, seed=seed, audit_mode=plan.sampling.audit_mode)
        audited = self.call("audit", messages, self.paths.audit_request(plan.plan_id),
                            self.paths.audit_response(plan.plan_id), plan.model.audit_max_output_tokens)
        return self.write_version(audited, sample, seed)

    def load_sample(self, rebuilt: Sample) -> Sample:
        """The sample with excerpts: reuse `sample.json` when it matches the rebuilt selection, otherwise fetch
        the evidence text and write it."""
        path = self.paths.sample(self.plan.plan_id)
        if path.is_file():
            existing = state.read_record(path, Sample)
            if _shape(existing) == _shape(rebuilt) and all(p.excerpt is not None for p in existing.passages):
                return existing
        evidence = self.reader.evidence([p.chunk_id for p in rebuilt.passages])
        sample = sampler.attach_excerpts(rebuilt, evidence, plan_id=self.plan.plan_id)
        sha = state.write_record(path, sample)
        self.journal.append("artifact_written", path=self.paths.relative(path), sha256=sha)
        return sample

    def reusable(self, call: str, response_path: Path) -> dict[str, Any] | None:
        """The saved raw response of the last completed `call`, if its file still matches the journal."""
        completed = list(self.journal.events("call_completed", plan_id=self.plan.plan_id, call=call))
        if not completed or not response_path.is_file():
            return None
        if hashing.sha256_file(response_path) != completed[-1]["response_sha256"]:
            return None
        return state.read_json(response_path)

    def call(self, call: str, messages: list[prompts.Message], request_path: Path, response_path: Path,
             max_output_tokens: int,
             parse: Callable[[model_client.ChatResult], dict[str, Any]] = model_client.parse_ontology_json,
             ) -> dict[str, Any]:
        """One journaled model call: reuse a saved completed response, else reserve, check the ledger, send
        once and journal the outcome. `parse` turns the result into the caller's JSON (and may raise
        MODEL_OUTPUT_INVALID; an unparsable saved answer is re-asked)."""
        raw = self.reusable(call, response_path)
        if raw is not None:
            try:
                return parse(_saved_result(raw))
            except Blocked as exc:
                if exc.code != "MODEL_OUTPUT_INVALID":
                    raise
                # an unparsable saved answer is re-asked (budget permitting) rather than reused forever
        reservation = budget.reserve(call, input_chars=sum(len(m["content"]) for m in messages),
                                     max_output_tokens=max_output_tokens, prices=self.prices)
        self.ledger().check(reservation, approved_budget_usd=self.approved, max_tokens=self.plan.caps.max_tokens)
        client = self.client
        body = client.request_body(messages, max_completion_tokens=max_output_tokens,
                                   reasoning_effort=self.plan.model.reasoning_effort)
        request_sha = state.write_json(request_path, body)
        self.journal.append("call_requested", plan_id=self.plan.plan_id, call=call, request_sha256=request_sha,
                            reserve_tokens=reservation.reserve_tokens, reserve_usd=reservation.reserve_usd)

        def failed(attempt: model_client.Attempt) -> None:
            self.journal.append("call_failed", plan_id=self.plan.plan_id, call=call,
                                http_status=attempt.http_status, billed=attempt.billed)

        try:
            result = client.complete(messages, max_completion_tokens=max_output_tokens,
                                     reasoning_effort=self.plan.model.reasoning_effort, on_attempt=failed)
        except http.EgressUnknownOutcome as exc:
            self.journal.append("call_unknown", plan_id=self.plan.plan_id, call=call,
                                reserve_usd=reservation.reserve_usd)
            raise Blocked("RUN_INCOMPLETE", f"{call}: the model call outcome is unknown ({exc}); it is charged at "
                          "its full reservation and re-sent on resume only if the budget allows",
                          details={"call": call, "plan_id": self.plan.plan_id}) from exc
        except http.EgressNotSent as exc:
            failed(model_client.Attempt(0, billed=False))
            raise Blocked("RUN_INCOMPLETE", f"{call}: could not reach the model endpoint ({exc})",
                          details={"call": call, "plan_id": self.plan.plan_id}) from exc
        if result.request_body != body:
            state.write_json(request_path, result.request_body)
        response_sha = state.write_json(response_path, result.raw)
        if result.prompt_tokens is None or result.completion_tokens is None:
            usd = reservation.reserve_usd
        else:
            usd = budget.actual_usd(result.prompt_tokens, result.completion_tokens, self.prices)
        self.journal.append("call_completed", plan_id=self.plan.plan_id, call=call, response_sha256=response_sha,
                            prompt_tokens=result.prompt_tokens, completion_tokens=result.completion_tokens,
                            usd=round(usd, 8), finish_reason=result.finish_reason)
        return parse(result)

    def write_version(self, audited: dict[str, Any], sample: Sample, seed: Ontology | None) -> dict[str, Any]:
        plan = self.plan
        n = state.next_version(self.paths)
        ontology, report = hygiene.clean(audited, {p.evidence_id for p in sample.passages}, seed, version=n,
                                         origin="propose")
        parent = state.latest_version(self.paths)
        previous = state.load_version(self.paths, parent)[1] if parent is not None else None
        version = Version(version=n, schema_id=ontology.schema_id(), origin="propose",
                          tool_version=state.tool_version(), created_at=state.utc_now(), hygiene=report,
                          parent_version=parent, plan_id=plan.plan_id, grz_generation_id=plan.grz.generation_id,
                          prompt_sha256=plan.prompt_sha256,
                          model=VersionModel(deployment=plan.model.deployment, model_name=plan.model.model_name,
                                             model_version=plan.model.model_version))
        state.write_version(self.paths, self.journal, version=version, ontology=ontology,
                            evidence=_evidence(ontology, sample.passages), diff=diff_mod.diff(previous, ontology))
        self.finish("completed")
        spent = self.ledger().spent_usd
        return {
            "status": "ok",
            "version": n,
            "schema_id": version.schema_id,
            "classes": len(ontology.classes),
            "properties": len(ontology.properties),
            "spent_usd": round(spent, 6),
            "approved_budget_usd": self.approved,
            "dropped": dict(sorted(Counter(d.reason for d in report.dropped).items())),
            "next_step": f"ontology-build approve --version {n} --schema-id {version.schema_id}",
        }


def _shape(sample: Sample) -> dict[str, Any]:
    """The sample without fetched text, for comparing a rebuilt selection with `sample.json`."""
    data = sample.to_dict()
    data["passages"] = [{**p, "source_id": None, "excerpt": None} for p in data["passages"]]
    return data


def _saved_result(raw: dict[str, Any]) -> model_client.ChatResult:
    choice = (raw.get("choices") or [{}])[0]
    return model_client.ChatResult(content=(choice.get("message") or {}).get("content") or "",
                                   finish_reason=choice.get("finish_reason") or "", prompt_tokens=None,
                                   completion_tokens=None, raw=raw, request_body={})


def _evidence(ontology: Ontology, passages: list[Passage]) -> list[EvidenceRecord]:
    cited = {e for item in [*ontology.classes, *ontology.properties] for e in item.evidence}
    return [EvidenceRecord(evidence_id=p.evidence_id, chunk_id=p.chunk_id, source_id=p.source_id or "",
                           community_id=p.community_id, level=p.level, excerpt=p.excerpt or "")
            for p in passages if p.evidence_id in cited]
