"""`ontology-build` entry point.

The argparse surface below is the contract: every verb and flag is registered.
`HANDLERS` maps each verb to `fn(args) -> result dict`, which raises `Blocked`.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from typing import Any

from ontology_core import output

Handler = Callable[[argparse.Namespace], dict[str, Any]]
PROG = "ontology-build"
VERBS = ("doctor", "connect", "inspect", "plan", "propose", "review", "approve", "export", "import", "status",
         "reconcile", "critique", "revise", "refine", "current")


def _paths(args: argparse.Namespace) -> Any:
    from ontology_core import state

    return state.paths_for(args.state_dir)


def doctor(args: argparse.Namespace) -> dict[str, Any]:
    from ontology_build import connection

    paths = _paths(args)
    ctx = connection.doctor_context(paths, tenant_id=args.tenant_id, grz_descriptor=args.grz_descriptor,
                                    model_endpoint=args.model_endpoint, model_deployment=args.model_deployment,
                                    subscription_id=args.subscription_id,
                                    model_resource_group=args.model_resource_group, plugin_root=args.plugin_root)
    return connection.run_doctor(ctx, paths)


def connect(args: argparse.Namespace) -> dict[str, Any]:
    from ontology_build import connection

    return connection.connect(_paths(args), tenant_id=args.tenant_id, grz_descriptor=args.grz_descriptor,
                              model_endpoint=args.model_endpoint, model_deployment=args.model_deployment,
                              input_price_per_1m=args.model_input_price_per_1m,
                              output_price_per_1m=args.model_output_price_per_1m,
                              subscription_id=args.subscription_id, model_resource_group=args.model_resource_group)


def inspect(args: argparse.Namespace) -> dict[str, Any]:
    from ontology_build import connection

    return connection.inspect(_paths(args))


def plan(args: argparse.Namespace) -> dict[str, Any]:
    from ontology_build import connection

    if args.kind != "propose":
        from pathlib import Path

        from ontology_build import critique as critique_mod

        return _with_plan_card(args, critique_mod.plan(_paths(args), critique_mod.CritiquePlanRequest(
            kind=args.kind, max_spend_usd=args.model_max_spend_usd, version=args.version_n,
            max_rounds=args.max_rounds, queries=Path(args.queries) if args.queries else None,
            reasoning_effort=args.reasoning_effort, max_output_tokens=args.model_max_output_tokens,
            max_tokens=args.model_max_tokens, judge_samples=args.judge_samples, noise_margin=args.noise_margin,
            judge_deployment=args.judge_deployment, judge_reasoning_effort=args.judge_reasoning_effort,
            judge_input_price_per_1m=args.judge_input_price_per_1m,
            judge_output_price_per_1m=args.judge_output_price_per_1m)))
    request = connection.plan_request(
        max_spend_usd=args.model_max_spend_usd, seed=args.seed, level=args.level, passages=args.passages,
        excerpt_chars=args.excerpt_chars, shard_chars=args.shard_chars, reasoning_effort=args.reasoning_effort,
        max_output_tokens=args.model_max_output_tokens, max_tokens=args.model_max_tokens)
    return _with_plan_card(args, connection.plan(_paths(args), request))


def _with_plan_card(args: argparse.Namespace, result: dict[str, Any]) -> dict[str, Any]:
    from ontology_build import approval_card

    return {**result, "approval": approval_card.for_plan(_paths(args), result)}


def propose(args: argparse.Namespace) -> dict[str, Any]:
    from ontology_build import propose as runner

    request = runner.ProposeRequest(plan_id=args.plan_id, approved_budget_usd=args.approved_budget_usd,
                                    approve_model_calls=args.approve_model_calls)
    return runner.run(_paths(args), request)


def _run_request(args: argparse.Namespace) -> Any:
    from ontology_build import critique as critique_mod

    return critique_mod.RunRequest(plan_id=args.plan_id, approved_budget_usd=args.approved_budget_usd,
                                   approve_model_calls=args.approve_model_calls)


def critique(args: argparse.Namespace) -> dict[str, Any]:
    from ontology_build import critique as runner

    return runner.run(_paths(args), _run_request(args))


def revise(args: argparse.Namespace) -> dict[str, Any]:
    from ontology_build import revise as reviser

    accept = [a.strip() for a in args.accept.split(",") if a.strip()] if args.accept else None
    return reviser.run(_paths(args), from_critique=args.from_critique, accept=accept)


def refine(args: argparse.Namespace) -> dict[str, Any]:
    from ontology_build import refine as runner

    return runner.run(_paths(args), _run_request(args))


def review(args: argparse.Namespace) -> dict[str, Any]:
    from ontology_build import approval

    from ontology_build import approval_card

    result = approval.review(_paths(args), args.version_n, details=args.details)
    if not result.get("approved"):
        result["approval"] = approval_card.for_review(_paths(args), result)
    return result


def approve(args: argparse.Namespace) -> dict[str, Any]:
    from ontology_build import approval

    return approval.approve(_paths(args), args.version_n, args.schema_id)


def export(args: argparse.Namespace) -> dict[str, Any]:
    from pathlib import Path

    from ontology_build import export as exporter

    return exporter.export(_paths(args), output=Path(args.output), version=args.version_n, fmt=args.format,
                           base_iri=args.base_iri, force=args.force)


def import_(args: argparse.Namespace) -> dict[str, Any]:
    from pathlib import Path

    from ontology_build import export as exporter

    return exporter.import_file(_paths(args), Path(args.file), as_seed=args.as_seed)


def status(args: argparse.Namespace) -> dict[str, Any]:
    from ontology_consume import service

    return service.status(_paths(args))


def reconcile(args: argparse.Namespace) -> dict[str, Any]:
    from ontology_build import reconcile as checker

    return checker.run(_paths(args), release_lock=args.release_lock)


def current(args: argparse.Namespace) -> dict[str, Any]:
    from ontology_core import current as pointer

    return pointer.result()


HANDLERS: dict[str, Handler] = {
    "doctor": doctor, "connect": connect, "inspect": inspect, "plan": plan, "propose": propose,
    "review": review, "approve": approve, "export": export, "import": import_, "status": status,
    "reconcile": reconcile, "critique": critique, "revise": revise, "refine": refine, "current": current,
}


def _positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return value


def _non_negative_int(text: str) -> int:
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return value


def _rounds(text: str) -> int:
    value = int(text)
    if not 1 <= value <= 5:
        raise argparse.ArgumentTypeError("must be 1-5")
    return value


def _margin(text: str) -> int:
    value = int(text)
    if not 0 <= value <= 10:
        raise argparse.ArgumentTypeError("must be 0-10")
    return value


def _usd(text: str) -> float:
    value = float(text)
    if not value >= 0:
        raise argparse.ArgumentTypeError("must be a non-negative amount")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=PROG, description="Propose, review and export an OWL ontology "
                                     "from a published GRZ community generation.")
    output.add_version_flag(parser)
    output.add_common_flags(parser)
    sub = parser.add_subparsers(dest="verb", required=True, metavar="verb")

    def verb(name: str, help_text: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_text)
        output.add_common_flags(p, subcommand=True)
        return p

    p = verb("doctor", "check install, sign-in, GRZ and model access (no completions)")
    p.add_argument("--tenant-id")
    p.add_argument("--grz-descriptor")
    p.add_argument("--model-endpoint")
    p.add_argument("--model-deployment")
    p.add_argument("--subscription-id")
    p.add_argument("--model-resource-group")
    p.add_argument("--plugin-root")

    p = verb("connect", "bind this state dir to a tenant, GRZ generation and model deployment")
    p.add_argument("--tenant-id", required=True)
    p.add_argument("--grz-descriptor", required=True)
    p.add_argument("--model-endpoint", required=True)
    p.add_argument("--model-deployment", required=True)
    p.add_argument("--model-input-price-per-1m", type=_usd, required=True)
    p.add_argument("--model-output-price-per-1m", type=_usd, required=True)
    p.add_argument("--subscription-id")
    p.add_argument("--model-resource-group")

    verb("inspect", "levels, communities and the default sampling")

    p = verb("plan", "price a propose, critique or refine run and save a plan")
    p.add_argument("--kind", choices=("propose", "critique", "refine"), default="propose")
    p.add_argument("--version", type=_non_negative_int, dest="version_n",
                   help="critique/refine: the version to start from (default: latest)")
    p.add_argument("--max-rounds", type=_rounds, default=3, help="refine: rounds (1-5, default 3)")
    p.add_argument("--queries", help="critique/refine: optional competency questions (.jsonl with id, query)")
    p.add_argument("--seed")
    p.add_argument("--level", type=_non_negative_int)
    p.add_argument("--passages", type=_positive_int)
    p.add_argument("--excerpt-chars", type=_positive_int, default=1200)
    p.add_argument("--shard-chars", type=_positive_int, default=60000)
    p.add_argument("--reasoning-effort", choices=("minimal", "low", "medium", "high"), default="low")
    p.add_argument("--model-max-output-tokens", type=_positive_int, default=8000)
    p.add_argument("--model-max-spend-usd", type=_usd, required=True)
    p.add_argument("--model-max-tokens", type=_positive_int)
    p.add_argument("--judge-samples", type=_rounds, default=3,  # critique.DEFAULT_JUDGE_SAMPLES
                   help="critique/refine: judge calls per version, scored by the median (1-5, default 3)")
    p.add_argument("--noise-margin", type=_margin, default=2,  # critique.DEFAULT_NOISE_MARGIN
                   help="refine: rubric points a round may drop before it is rejected (0-10, default 2)")
    p.add_argument("--judge-deployment",
                   help="critique/refine: judge deployment on the connected account (default: the connected one)")
    p.add_argument("--judge-reasoning-effort", choices=("minimal", "low", "medium", "high"),
                   help="critique/refine: judge reasoning effort (default: --reasoning-effort)")
    p.add_argument("--judge-input-price-per-1m", type=_usd,
                   help="critique/refine: judge input price (default: the connected deployment's)")
    p.add_argument("--judge-output-price-per-1m", type=_usd,
                   help="critique/refine: judge output price (default: the connected deployment's)")

    p = verb("propose", "run an approved plan (rerun to resume)")
    p.add_argument("--plan-id", required=True)
    p.add_argument("--approved-budget-usd", type=_usd)
    p.add_argument("--approve-model-calls", action="store_true")

    p = verb("review", "summarize a version before approval")
    p.add_argument("--version", type=_non_negative_int, dest="version_n")
    p.add_argument("--details", action="store_true")

    p = verb("approve", "approve a version by its schema ID")
    p.add_argument("--version", type=_non_negative_int, dest="version_n", required=True)
    p.add_argument("--schema-id", required=True)

    p = verb("export", "write an approved version as flat-owl RDF/XML or inline-compatible JSON-LD")
    p.add_argument("--version", type=_non_negative_int, dest="version_n")
    p.add_argument("--output", required=True)
    p.add_argument("--format", choices=("owl", "ttl", "jsonld"), default="owl",
                   help="owl writes RDF/XML (default); jsonld writes inline-compatible JSON-LD; ttl is unsupported")
    p.add_argument("--base-iri")
    p.add_argument("--force", action="store_true")

    p = verb("import", "import an ontology file as a new version")
    p.add_argument("file")
    p.add_argument("--as-seed", action="store_true")

    verb("status", "connection, versions, approvals, last run and the next step")

    p = verb("reconcile", "check the journal against the files; release a stale lock")
    p.add_argument("--release-lock", action="store_true")
    verb("current", "the current approved ontology: path, sha256, IRI, counts, source generation")

    p = verb("critique", "lint and judge a version (N judge samples, median score; approved critique plan)")
    p.add_argument("--plan-id", required=True)
    p.add_argument("--approved-budget-usd", type=_usd)
    p.add_argument("--approve-model-calls", action="store_true")

    p = verb("revise", "apply a critique's change ops as a new version")
    p.add_argument("--from-critique", required=True)
    p.add_argument("--accept", help="comma-separated finding fingerprints, or `all` (default: high and medium)")

    p = verb("refine", "lint, judge and revise in rounds under one approved refine plan (rerun to resume)")
    p.add_argument("--plan-id", required=True)
    p.add_argument("--approved-budget-usd", type=_usd)
    p.add_argument("--approve-model-calls", action="store_true")
    return parser


def summary_for(verb: str) -> Callable[[dict[str, Any]], str] | None:
    try:
        from ontology_build import summaries

        def render(result: dict[str, Any]) -> str:
            try:
                return summaries.render(verb, result)
            except NotImplementedError:
                return output.dumps(result)

        return render
    except ImportError:  # pragma: no cover
        return None


def safe_stdout() -> None:
    """A cp1252 pipe must not crash a verb: unencodable characters become backslash escapes (still valid JSON)."""
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None and (sys.stdout.encoding or "").lower().replace("-", "") != "utf8":
        reconfigure(errors="backslashreplace")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    safe_stdout()
    result, code = output.run_verb(HANDLERS[args.verb], args, json_mode=args.json)
    if args.verb == "doctor" and "checks" in result:
        from ontology_build import summaries
        from ontology_core import doctor as checks

        # read-only: exit 0 even when not ready; --json is the cross-plugin doctor shape
        print(output.dumps(checks.report(result)) if args.json else summaries.render("doctor", result))
        return 0
    output.emit(result, args.json, summary_for(args.verb))
    return code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
