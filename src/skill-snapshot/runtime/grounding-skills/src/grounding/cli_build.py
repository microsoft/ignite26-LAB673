"""grounding-build CLI: plan | apply --plan-id | status | resume --plan-id."""

from __future__ import annotations

import sys

from . import align, build
from .azure import Azure
from .cli_common import (add_endpoint_arg, add_identity_args, identity, parser, resolve_endpoint, run)
from .names import default_index_name


def add_source_args(p) -> None:
    p.add_argument("--file", default="", help="bring-your-own edge file (CSV, JSONL or Parquet)")
    p.add_argument("--format", default=None, choices=["csv", "jsonl", "parquet"])
    p.add_argument("--wikidata", action="store_true", help="Wikidata bootstrap from bounded --seed values")
    p.add_argument("--seed", action="append", default=[], help="Wikidata QID or title (repeatable)")
    p.add_argument("--depth", type=int, default=1, help="Wikidata hops from the seeds (1..2, default 1)")
    p.add_argument("--edge-cap", type=int, default=None, help="max edges (default 200000 BYO, 50000 Wikidata)")
    p.add_argument("--index", default="", help="grounding index name (default: grounding-<source>)")
    p.add_argument("--source-label", default="byo", help="origin label stamped in namespace for BYO edges")
    p.add_argument("--graph-name", default="", help="stamp every edge with this graph name; set it to the target build's graph name")
    p.add_argument("--with-labels", dest="with_labels", action="store_true", default=None,
                   help="force rdfs:label rows (default: automatic when edges carry subject_id/object_id)")
    p.add_argument("--no-labels", dest="with_labels", action="store_false", help="never add rdfs:label rows")
    p.add_argument("--license", default="", dest="license_text", help="licence summary recorded in the descriptor")


def make_plan(a, az, ident, persist: bool) -> dict:
    seeds = a.seed if a.wikidata else None
    edges, extra = build.load_edges(file=a.file, fmt=a.format, wikidata_seeds=seeds, depth=a.depth,
                                    edge_cap=a.edge_cap, source_label=a.source_label, graph_name=a.graph_name, with_labels=a.with_labels,
                                    license_text=a.license_text)
    seed_text = "-".join(a.seed) if a.wikidata else (a.source_label or "edges")
    index = a.index or default_index_name(seed_text)
    return build.make_plan(az, ident, endpoint=resolve_endpoint(a.endpoint, a.index), index_name=index, edges=edges,
                           extra=extra, persist=persist)


def main(argv: list[str] | None = None) -> int:
    p = parser("grounding-build", "Plan and load a grounding index from an edge file or a Wikidata seed.")
    sub = p.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("plan", help="dry run: normalize, validate, report counts and the plan ID (no Azure writes)")
    add_identity_args(pl)
    add_endpoint_arg(pl)
    add_source_args(pl)
    ap = sub.add_parser("apply", help="create the index and upload edges; needs the exact approved --plan-id")
    add_identity_args(ap)
    ap.add_argument("--plan-id", default="")
    ap.add_argument("--batch-size", type=int, default=build.MAX_BATCH)
    ap.add_argument("--stop-after-batches", type=int, default=None,
                    help="pause after N upload batches (resume later with `resume`)")
    al = sub.add_parser("align", help="re-stamp graph_name on every row of an existing grounding index "
                                       "(dry run without --plan-id)")
    add_identity_args(al)
    add_endpoint_arg(al)
    al.add_argument("--index", required=True)
    al.add_argument("--graph-name", required=True, help="graph name of the graph-extraction build that will use the index")
    al.add_argument("--plan-id", default="")
    al.add_argument("--batch-size", type=int, default=build.MAX_BATCH)
    al.add_argument("--stop-after-batches", type=int, default=None, help="pause after N batches; re-run with the same plan ID")
    st = sub.add_parser("status", help="local journal status (no Azure calls)")
    st.add_argument("--plan-id", default="")
    rs = sub.add_parser("resume", help="re-verify remote state, then continue an interrupted apply")
    add_identity_args(rs)
    rs.add_argument("--plan-id", default="")
    rs.add_argument("--batch-size", type=int, default=build.MAX_BATCH)
    a = p.parse_args(argv)

    def go():
        if a.cmd == "status":
            return build.status(a.plan_id or None)
        az = Azure()
        ident = identity(az, a)
        if a.cmd == "align":
            if a.plan_id:
                return align.apply_align(az, ident, a.plan_id, batch_size=a.batch_size,
                                         stop_after_batches=a.stop_after_batches)
            plan = align.make_align_plan(az, ident, endpoint=resolve_endpoint(a.endpoint, a.index), index=a.index,
                                         graph_name=a.graph_name)
            plan["dry_run"] = True
            return plan
        if a.cmd == "plan":
            plan = make_plan(a, az, ident, persist=True)
            plan["dry_run"] = True
            return plan
        return build.apply(az, ident, a.plan_id, batch_size=a.batch_size,
                           stop_after_batches=getattr(a, "stop_after_batches", None), resume=a.cmd == "resume")

    return run(go)


if __name__ == "__main__":
    sys.exit(main())
