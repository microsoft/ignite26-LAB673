# Connect, plan, propose

## Quick starts

- "Set up ontology-build against this GRZ descriptor and my Azure OpenAI deployment."
- "Inspect the community levels and plan an ontology proposal with a one-dollar cap."
- "Run the approved proposal and tell me what version it wrote."

## Use this path

Use this path to bind a state directory to one GRZ generation and one model deployment, price a proposal, and run it after approval.

## Setup

1. Run `ontology-build --version`. If missing, read the [local runtime installation instructions](../../../README.md#install-the-local-runtimes) first. Install or run the shipped `runtime/ontology-skills` package through the Microsoft CFS feed.
2. Run `ontology-skills-ontology_doctor` or `ontology-build doctor --json` first, and again after any blocked result. It only reads, always exits 0, and ends with one `next_step`. Before connecting, pass the same `--tenant-id`, `--grz-descriptor`, `--model-endpoint`, and `--model-deployment` you will pass to `connect`. A `warn` check names the missing flag.
3. Name the tenant before sign-in, then the user runs `az login --tenant <id>`.

## Steps

1. `ontology-build connect` with `--tenant-id`, `--grz-descriptor <descriptor.json>`, `--model-endpoint https://<account>.openai.azure.com`, `--model-deployment`, and the two per-1M token prices. Add `--subscription-id` and `--model-resource-group` so doctor also checks the deployment. It binds the state directory only when doctor is clean.
2. `ontology-build inspect` lists community levels and default sampling. It is free.
3. `ontology-build plan --model-max-spend-usd <cap>` is free and saves an estimate. If it blocks because the estimate is above the cap, tell the user the cap `next_step` names and ask before re-planning. Show the plan `approval` card and stop.
4. After `approved <plan-id>`, run `ontology-build propose --plan-id <id> --approved-budget-usd <amount> --approve-model-calls`. The amount is the card's "at most" figure unless the user names a lower one at or above the estimate. If it stops part way, rerun the same command; completed calls are not sent again.
5. To extend an existing ontology, run `ontology-build import <file> --as-seed` before `plan`.

## Return

Say what each step is for and what it costs in dollars. Report the new version number and one safe next action, usually review. Never show fingerprints, shards, or the journal unless asked.
