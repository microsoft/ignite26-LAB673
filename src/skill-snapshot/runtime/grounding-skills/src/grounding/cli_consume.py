"""grounding-consume CLI: check | inspect | sample (read-only)."""

from __future__ import annotations

import sys

from . import consume
from .azure import Azure
from .cli_common import add_endpoint_arg, add_identity_args, identity, parser, resolve_endpoint, run


def main(argv: list[str] | None = None) -> int:
    p = parser("grounding-consume", "Read-only checks of a grounding index.")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, helptext in (("check", "validate the edgeList profile, count and a sample query"),
                           ("inspect", "show profile mapping, counts and sampled provenance"),
                           ("sample", "return a few edges"),
                           ("ready", "PASS/FAIL: can a graph-extraction build resolve names against this index?")):
        s = sub.add_parser(name, help=helptext)
        add_identity_args(s)
        add_endpoint_arg(s)
        s.add_argument("--index", required=True)
        if name == "ready":
            s.add_argument("--graph-name", default="", help="graph name of the graph-extraction build that will use the index")
        if name == "sample":
            s.add_argument("-n", type=int, default=10)
            s.add_argument("--query", default="*")
            s.add_argument("--predicate", default="")
    a = p.parse_args(argv)

    def go():
        az = Azure()
        identity(az, a, need_subscription=False)
        ep = resolve_endpoint(a.endpoint, a.index)
        if a.cmd == "check":
            return consume.check(az, ep, a.index)
        if a.cmd == "ready":
            return consume.ready(az, ep, a.index, a.graph_name)
        if a.cmd == "inspect":
            return consume.inspect(az, ep, a.index)
        return consume.sample(az, ep, a.index, a.n, a.query, a.predicate)

    return run(go)


if __name__ == "__main__":
    sys.exit(main())
