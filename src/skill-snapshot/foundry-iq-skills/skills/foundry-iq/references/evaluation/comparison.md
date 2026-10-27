# Control the hill-climb experiment

[Hill-Climb Retrieval Quality through Evaluation](../../hero-scenarios/hill-climb-retrieval-quality/hill-climb-retrieval-quality.md)
owns baseline, candidate, evaluation, comparison and retain-or-revert decisions.
Its evaluation stage also exposes the same contract to an optional optimizer.

## Freeze the experiment

Record a versioned `evaluation-plan.json` in the approved customer artifact folder:

- Reviewed question-set and development/holdout digests, query IDs, source corpus
  snapshot, labels/provenance when present, coverage and sample-size rationale.
- Target kind/identity, answer owner, caller/entitlements, API/interface, sanitized
  target and request configuration hashes, agent version and extraction/index lineage.
- Exact cloud project, evaluator IDs/versions, mappings, metric names/scales, judge
  deployment/resolved model, SDK/script versions and hashes.
- Primary metric/direction, meaningful delta, critical-slice and latency/cost bounds,
  repetitions, comparison method, maximum attempts, privacy/spend/retention approval.

Do not change criteria or select favorable slices after results. A budget-limited
sample is an explicitly reviewed calibration, not the full agreed comparison.
Prefer the largest sample the approved budget allows; a small calibration sample
can hide per-slice regressions and random noise that only show up at scale.
Capture successful and failed rows; lack of a metric is not a zero score.

## Baseline and trial records

Return `schema_version: "1.0"`, plan digest, trial ID, parent baseline ID, target and
configuration identities, query/split digests, execution mode and timestamps.
Attach actual cloud `eval_id`, `run_id`, service-returned `report_url` or absence
reason, row artifact paths/digests, criterion scores/reasons and failure counts.
Separate `integrity` from `quality_verdict`; default verdict is `not_assessed`.

Include row/slice metrics, wins/losses, target latency, target/judge token usage,
search counts and priced components with provenance. Record missing measurements
as null with reasons. A returned Foundry report URL is not a Search/API endpoint.
Keep raw queries, contexts, responses and detailed evidence private; public PRs
contain sanitized synthetic fixtures, never customer artifacts or credentials.

For an evaluation-only handoff, attach the frozen experiment plan, original runner
artifacts, [saved report](cloud.md#inspect-saved-results-without-inference),
target snapshot/readback proof and full attempt ledger. The saved report carries
row scores, usage and artifact digests, not an optimization decision. Do not infer
target verification or a complete cost from its valid cloud-evidence result.

## Choose an experiment from failures

Tie every proposal to affected queries and an observed failure. Missing content in
tables/figures/diagrams warrants inspecting extraction, then a basic-versus-Content
Understanding Standard comparison if justified. Decomposition, ambiguity, multiple
searches or cross-evidence synthesis failures can justify classic-versus-KB.
Otherwise keep the current architecture and make a smaller reversible change.

Name the experimental variable and all intended dependent differences. For an
architecture comparison, different target IDs and associated setup are the declared
treatment; they do not make unrelated model, prompt, corpus or evaluator drift
acceptable. Use separately approved isolated resources. Compare a retrieval-only
system with retrieval metrics, or the same full answering contract on both sides;
do not compare a search passage to an agent answer as interchangeable outputs.

## Run the candidate loop

Choose quality improvement or cost reduction as the primary goal. Set the primary
metric, minimum useful delta, quality floor, regression bounds, repetitions and
iteration budget before trying candidates. Cost reduction may allow an explicitly
approved quality tolerance; do not decide the customer's tradeoff after seeing a
cheaper score. No unknown cost component becomes zero to manufacture a winner.

If no regression bounds were predeclared, propose for approval before trials:
no security/access-control regression, no critical-query regression, and no more
than roughly 20% latency or cost regression unless the user explicitly approves
a different bound.

Use row-level failure evidence to propose a reversible single-variable change.
If an optimization skill is available, provide the baseline, hypotheses, controls,
metric policy and remaining budget for candidate guidance. Otherwise the Hero
continues this same bounded loop using supported operation references. Neither
path may bypass approval or run an open-ended parameter sweep.

Record the exact baseline definition/request, candidate delta, readback checks and
rollback. Apply only the approved delta, verify it and check retrieval readiness.
Evaluate fresh outputs, then restore and verify the baseline before an independent
candidate. Advancing from a retained winner requires a new baseline identity.

Each proposed candidate gets before/after values, rationale, approval, fresh
outputs, measurements, decision (`accepted`, `rejected`, `inconclusive`, `invalid`
or `not_run`) and rollback/retained-state evidence in an append-only trial log.
Do not omit failed or unexecuted candidates. Re-evaluate on the same queries
with the same judge and controlled settings. Report uncertainty and per-slice
regressions; no claim of statistical significance without a predeclared method.

Retain a candidate only after the agreed improvement and all noncompensating safety
and regression bounds pass. Unknown cost blocks a total-cost acceptance claim.
Use the sealed holdout once for the selected candidate and baseline comparison;
retain neither a failed holdout winner nor a configuration with unverified rollback.
No improvement is an honest outcome. Repeated holdout-driven tuning needs a new
independent holdout and a new reviewed experiment.

After a candidate is accepted on the development set, run that exact retained
configuration once against the reserved holdout queries, using the same metric,
judge and comparison method as the development comparison. Record the holdout
result regardless of outcome. A holdout failure requires reverting to the
verified baseline, not trying another candidate against that same holdout.