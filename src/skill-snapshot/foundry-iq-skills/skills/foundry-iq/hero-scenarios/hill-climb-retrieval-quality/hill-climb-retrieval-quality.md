# Hill-Climb Retrieval Quality through Evaluation

Quality failures need evidence. Start
from the existing architecture; no KB prerequisite.
This Hero owns the complete loop: queries, baseline, diagnosis, approved change,
re-evaluation, retain/revert. Evaluation is a reusable stage, not improvement's endpoint.

## Scope and inputs

Approved setup: read [service selection](../../references/service-provisioning.md).
Run the [shared RBAC check](../../references/authentication-rbac.md);
ask before granting missing permissions or provide administrator instructions.

## API version preflight

Resolve classic Search/application, KB-only or Agent + KB, answer owner, interface,
sources and identity. Resolve `dataApiVersion` and needed `managementApiVersion`
under shared policy before requests. Reuse resources; ask for missing boundaries,
goals and approvals.
Do not require a prepared dataset or ground truth.

Fixed-batch improvement, not continuous
evaluation. No monitoring, live-trace harvesting, external-agent registration
or recurring rules. Inspect read-only; retrieval, generation and cloud
judging cost money and move private data.

## 1. Establish an evaluation set

Read [query-set admission](../../references/evaluation/dataset.md).
Reuse suitable supplied questions. Otherwise review failing examples and approved
source excerpts/query exports; propose questions covering topics, formats, languages
and critical/identity slices. Review relevance/coverage, not invented answers.
Review synthetic questions; generation-only requests stop here.

Assign stable IDs and preserve provenance/metadata. Freeze the agreed development
set; reserve a holdout before iteration. No ground truth is required for
Groundedness, Relevance and Retrieval: use actual target query/response/context.
Add Response Completeness only with verified answers; Document Retrieval needs
reviewed qrels. Never promote generated answers to gold.
Do not silently subsample an agreed comparison set to save money.

## 2. Record the existing baseline

Read [target capture](../../references/evaluation/capture.md) and selected
[cloud evaluation](../../references/evaluation/cloud.md) profile.
Freeze configurations, corpus, caller, query/split digests, judge/model/evaluator
versions and mappings. Agree metric/direction, useful delta, slice/latency/cost bounds,
repetitions, attempts and spend. Approve data/project/assets/retention/calls; approve missing setup separately.
Without acceptance criteria, report a baseline, not
a quality pass or permission to retain a change. Unknown cost remains null, not zero.

Use [Search](../../operations/data-plane/documents/search-post.md)
(`Documents_SearchPost`) or [KB retrieve](../../operations/data-plane/knowledge-retrieval/retrieve.md)
(`KnowledgeRetrieval_Retrieve`) through the existing application's actual path.
Use the pinned existing agent for native evaluation; no artificial KB-only agent.
Test the selected surface, not every transport. Preserve query-time ACL identity.

Probe one development row, then the remaining rows; count the probe once. Capture
answer/evidence from the same invocation; never retrieve again to fill context.
A search-only target uses Retrieval, plus Document Retrieval with qrels, without
inventing an answer. Answering systems use all three reference-free evaluators.
Use Foundry Cloud Evaluators only; never fall back to local evaluators.

### Complete each evaluation

Before returning or considering a candidate:
1. Reconcile every query, metric and failure; retain actual cloud run/report IDs.
2. Read back the target configuration against the frozen snapshot. Record unchanged,
  changed or unverified with evidence; read-only intent is not verification.
3. Report cloud execution, evidence integrity, target verification and workload
  quality separately. Cloud completion alone is not verified task completion.

Baseline-only requests stop only after these checks and the final report. Skip
optimization, never verification. Missing checks mean incomplete verification.

## 3. Identify likely failure modes

Inspect failing rows/citations for ingestion, extraction, retrieval, reasoning,
synthesis, freshness or authorization defects. Reference-free scores do not prove
completeness. Log hypotheses, affected slices, evidence and discriminators.

- Missing information in tables, figures, diagrams or other multimodal content:
  inspect extraction before blaming ranking. Compare basic extraction against
  Content Understanding Standard only when that evidence justifies it.
- Classic retrieval fails on decomposition, multiple searches, ambiguity or
  synthesis across evidence: consider a classic-versus-Knowledge-Base experiment.
- Classic search already meets the target with better latency and cost: retain it;
  do not introduce agentic retrieval merely because the skill supports it.

## 4. Change one meaningful variable

Read [candidate guidance](../../references/hill-climb-candidates.md) and
[comparison policy](../../references/evaluation/comparison.md).
Choose quality or cost improvement within approved bounds; use failure evidence
for one reversible candidate. Re-measure stale or different-workload baselines.
Treat any proposed candidate as unretained until a re-evaluation against the frozen
baseline confirms it meets the predeclared policy, even when the request only asks
for the change itself.
An owning optimization workflow may guide candidates; do not stop an improvement
request when that separate skill is absent.

Log one variable, before/after, hypothesis, controls, actions, cost and rollback.
Read the operation; approve deployed/billable/data/ingestion changes. Preserve other
settings; query-time trials need data/spend approval.
Keep an append-only trial log, including failed and not-run candidates. Apply only the approved delta;
verify its definition/request and retrieval readiness before evaluation.

Approve architecture/extraction experiments separately. Use isolated candidate resources
with the same workload, corpus, judge and answer contract; declare implementation
differences as the treatment. Delegate setup to its owner.
Never rebuild shared production sources/indexes just for comparison.

## 5. Re-evaluate and retain or revert

Regenerate target outputs for every candidate on the same frozen development set;
never score baseline answers as new retrieval. Recheck controls and record drift.
Return to the verified baseline between independent candidates. Adopting a winner
requires a new baseline ID; record the transition before another hypothesis.
Compare paired rows and critical slices, quality, p50/p95 target latency, searches,
target/judge tokens and attributable cost with price source/date. Separate target
latency from cloud evaluation wall time. Include failed attempts and losing runs.

Retain only a measurable improvement under the predeclared policy without violating
safety or regression bounds. An inconclusive, invalid or regressing candidate is
not a winner. Restore the approved baseline through its owning workflow and verify
rollback, or record blocked recovery. Confirm the selected winner once on the sealed
holdout; a failed holdout is not another tuning opportunity. Stop at the agreed
attempt/spend bound. Never claim statistical significance from a smoke sample.
Read back the retained configuration; verify its retrieval path. A test
or user instruction to stop after evaluation overrides steps 3-5 for that run only;
this Hero is not evaluation-only.

## Verify and return

Return questions, baseline, findings, candidates/decisions, retained configuration,
rollback proof, reports, costs/unknowns and limitations. No improvement is valid.
Verify comparability, security boundaries and the evaluation checks above.
Cleanup is separately approved: use [scenario cleanup](../../references/safety-and-idempotency.md#scenario-cleanup)
for run-owned assets; retain evidence/ownership.
Manual success is not proof of skill-value improvement.