# Connect, plan, propose

## Quick starts

- "Set up ontology-build against this GRZ descriptor and my Azure OpenAI deployment."
- "Inspect the community levels and plan an ontology proposal with a one-dollar cap."
- "Run the approved proposal and tell me what version it wrote."

## Use this path

Use this path to bind a state directory to one GRZ generation and one model deployment, price a proposal, and run it after approval.

## Setup

1. Follow [runtime setup](../../graph-guide/references/install-and-checks.md#plugin-and-clis): explicit `setup ontology`, then `run ontology ontology-build --help`. Retain the launcher prefix on later commands; warm run never installs.
2. Run `ontology-build doctor --json` first, and again after any blocked result. It only reads, always exits 0, and ends with one `next_step`. Before connecting, pass the same `--tenant-id`, `--grz-descriptor`, `--model-endpoint`, and `--model-deployment` you will pass to `connect`. A `warn` check names the missing flag.
3. Name the tenant before sign-in, then the user runs `az login --tenant <id>`.

## Steps

1. Choose one absolute `--state-dir` and retain it on every build/consume command. `ontology-build connect` with `--tenant-id`, the published GRZ `--grz-descriptor <descriptor.json>`, `--model-endpoint <observed-https-endpoint>`, `--model-deployment`, `--model-input-price-per-1m` and `--model-output-price-per-1m`. Add `--subscription-id` and `--model-resource-group` for the deployment check. It binds only when doctor is clean; never synthesize an account endpoint.
2. `ontology-build inspect` lists community levels and default sampling. It is free.
3. `ontology-build plan --model-max-spend-usd <cap>` is free and saves an estimate. If it blocks because the estimate is above the cap, tell the user the cap `next_step` names and ask before re-planning. Show the plan `approval` card and stop.
4. After `approved <plan-id>`, run `ontology-build propose --plan-id <id> --approved-budget-usd <amount> --approve-model-calls`. The amount is the card's "at most" figure unless the user names a lower one at or above the estimate. If it stops part way, rerun the same command; completed calls are not sent again.
5. To extend an existing ontology, run `ontology-build import <file> --as-seed` before `plan`.

## Return

Say what each step is for and what it costs in dollars. Report the new version number and one safe next action, usually review. Never show fingerprints, shards, or the journal unless asked.
