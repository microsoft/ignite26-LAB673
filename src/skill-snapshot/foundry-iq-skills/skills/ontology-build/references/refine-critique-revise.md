# Refine, critique, revise

## Quick starts

- "Price a refine pass on the latest ontology version and show me the approval card."
- "Run one critique of version 2 against my competency questions."
- "Apply the accepted changes from critique `<id>` as a new version."

## Use this path

Use this path after a draft exists. A reviewer model checks the draft for gaps such as types with no relationships, catch-all types, and overlapping relationships, then fixes them and keeps each round as a version.

## Refine

1. Price it first: `ontology-build plan --kind refine --model-max-spend-usd <cap>`. Add `--queries <file.jsonl>` (one `id` and `query` per line) when the user has questions the ontology must answer.
2. Show the plan `approval` card and stop. After `approved <plan-id>`, run the `refine` command the plan printed, with `--plan-id`, `--approved-budget-usd`, and `--approve-model-calls`.
3. It stops on its own: `converged`, `causal_repeat`, `no_improvement`, `no_changes`, `max_rounds`, or `budget_exhausted`. Rerunning resumes. On `no_improvement` it keeps the best judged version and lists unapplied changes under `rejected`.

## Critique and revise

- `ontology-build plan --kind critique`, then show the card and wait for `approved <plan-id>` before `ontology-build critique`. It is one judged round that proposes changes and writes no version.
- `ontology-build revise --from-critique <id>` applies the accepted changes as a new, unapproved version. It sends nothing to the model, so it needs no approval card. `--accept <fingerprints>|all` narrows what is applied; the default is high and medium findings.

## Return

Report the stop reason, the scores per round, problems fixed and still open, and the version produced. Cost is bounded by the approved budget; say what was spent. Never present a refined version as approved; approval is a separate gate.
