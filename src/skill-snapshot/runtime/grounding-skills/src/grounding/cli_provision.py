"""grounding-provision CLI: connect | doctor | create."""

from __future__ import annotations

import sys

from . import provision, state
from .azure import Azure
from .cli_common import (add_endpoint_arg, add_identity_args, identity, parser, resolve_endpoint, run, say)
from .errors import GroundingError


def main(argv: list[str] | None = None) -> int:
    p = parser("grounding-provision", "Connect to or create the Azure AI Search service for grounding indexes.")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("connect", help="read-only: list/inspect Search services and save the chosen endpoint")
    add_identity_args(c)
    add_endpoint_arg(c)
    c.add_argument("--service", default="", help="Search service name to select")
    c.add_argument("--no-save", action="store_true", help="do not save the selected endpoint locally")
    d = sub.add_parser("doctor", help="read-only: roles, preview API availability, Entra auth for a service")
    add_identity_args(d)
    add_endpoint_arg(d)
    k = sub.add_parser("create", help="create-if-not-exists resource group + Search service (dry-run by default)")
    add_identity_args(k)
    k.add_argument("--resource-group", required=True)
    k.add_argument("--service-name", required=True)
    k.add_argument("--location", required=True)
    k.add_argument("--sku", default=provision.DEFAULT_SKU, choices=provision.SKUS)
    k.add_argument("--plan-id", default="", help="exact plan ID shown by the dry run; required to write")
    a = p.parse_args(argv)

    def go():
        az = Azure()
        ident = identity(az, a)
        if a.cmd == "connect":
            out = provision.connect(az, ident, a.service, a.endpoint)
            sel = out.get("selected")
            if sel and not a.no_save:
                path = state.save_connection({"endpoint": sel["endpoint"], "service": sel["name"],
                                              "resource_group": sel["resource_group"]})
                out["saved_connection"] = True
                say(f"Saved endpoint {sel['endpoint']} to local state ({path.name}).")
            return out
        if a.cmd == "doctor":
            return provision.doctor(az, ident, resolve_endpoint(a.endpoint))
        kw = dict(resource_group=a.resource_group, service_name=a.service_name, location=a.location, sku=a.sku)
        if not a.plan_id:
            plan = provision.create_plan(az, ident, **kw)
            plan["dry_run"] = True
            return plan
        return provision.create_apply(az, ident, a.plan_id, **kw)

    return run(go)


if __name__ == "__main__":
    sys.exit(main())
