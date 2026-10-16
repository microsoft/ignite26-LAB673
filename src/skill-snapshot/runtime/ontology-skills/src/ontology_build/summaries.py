"""Human summaries (at most 6 lines) for every verb result.

`output.emit(result, json_mode, summary=summaries.render(verb, result))`. Blocked results use
`output.blocked_summary` and never come here. Two exceptions to the line cap: `doctor` prints one line
per check, and a result carrying an `approval` card (plan, review) prints the whole card.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

MAX_LINES = 6

Lines = list[str]


def _usd(value: Any) -> str:
    try:
        return f"${float(value):.2f}"
    except (TypeError, ValueError):
        return "$?"


def _tenant(result: dict[str, Any]) -> str:
    name = result.get("tenant_name")
    return f"Tenant: {result.get('tenant_id')}" + (f" ({name})" if name else "")


def _doctor(result: dict[str, Any]) -> str:
    rows = result.get("checks", [])
    width = max((len(c["name"]) for c in rows), default=0)
    lines = [f"{c['status']:<4}  {c['name']:<{width}}  {c.get('detail', '')}".rstrip() for c in rows]
    lines.append(f"Next step: {result.get('next_step', '')}")
    return "\n".join(lines)


def _connect(r: dict[str, Any]) -> Lines:
    model = " ".join(x for x in (r.get("model_name"), r.get("model_version")) if x)
    counts = {s: sum(1 for c in r.get("checks", []) if c["status"] == s) for s in ("ok", "skip")}
    return [_tenant(r),
            f"Connected to GRZ generation {r.get('generation_id')} ({r.get('physical_index')}).",
            f"Model deployment: {r.get('model_deployment')}" + (f" ({model})" if model else ""),
            f"Doctor: {counts['ok']} ok, {counts['skip']} skipped, 0 failed."]


def _inspect(r: dict[str, Any]) -> Lines:
    levels = ", ".join(f"L{x['level']}: {x['communities']}" for x in r.get("levels", []))
    return [_tenant(r),
            f"Generation {r.get('generation_id')}, manifest {r.get('health')}.",
            f"Communities per level: {levels}",
            f"Default: level {r.get('default_level')}, {r.get('default_passages')} passages."]


def _plan(r: dict[str, Any]) -> Lines:
    est, caps = r.get("estimate") or {}, r.get("caps") or {}
    if r.get("kind") in ("critique", "refine"):
        scope = (f"Critique of v{r.get('version')}: 1 judge call" if r["kind"] == "critique" else
                 f"Refine from v{r.get('version')}: up to {r.get('rounds')} rounds, {r.get('calls')} judge calls")
        scope += f", {r['queries']} competency questions." if r.get("queries") else "."
    else:
        scope = f"{r.get('passages')} passages at level {r.get('level')}, {r.get('calls', est.get('calls'))} model calls."
    lines = [f"Plan {r['plan_id']}" if r.get("plan_id") else "Estimate (no plan saved)",
             scope,
             f"Estimated cost: up to {_usd(est.get('usd'))}"
             + (f" (expected ~{_usd(est['expected_usd'])})" if est.get("expected_usd") is not None else "")
             + f"; cap {_usd(caps.get('max_spend_usd'))}.",
             "The upper bound prices every token at the higher of the input/output prices.",
             "Approve? Running it needs your explicit yes for that amount."]
    return lines


def _propose(r: dict[str, Any]) -> Lines:
    lines = []
    if r.get("version") is not None:
        lines.append(f"Proposed v{r['version']}: {r.get('classes', '?')} classes, {r.get('properties', '?')} properties.")
    if r.get("spent_usd") is not None:
        lines.append(f"Spent {_usd(r['spent_usd'])} of {_usd(r.get('approved_budget_usd'))} approved.")
    if r.get("schema_id"):
        lines.append(f"Schema ID: {r['schema_id']}")
    return lines or ["Proposal finished."]


def _findings(counts: dict[str, Any]) -> str:
    return f"{counts.get('high', 0)} high, {counts.get('medium', 0)} medium, {counts.get('low', 0)} low"


def _critique(r: dict[str, Any]) -> Lines:
    lines = [f"v{r['version']} scored {r['total']}/{r['max_total']}; findings: {_findings(r['findings'])}."]
    for f in r.get("top_findings", [])[:3]:
        text = " ".join(str(f.get("rationale") or "").split())
        lines.append(f"- {f['severity']}: {f['fingerprint']}: {text[:90]}" + ("..." if len(text) > 90 else ""))
    lines.append(f"{r['ops']} proposed changes; spent {_usd(r.get('spent_usd'))}.")
    return lines


def _revise(r: dict[str, Any]) -> Lines:
    if r.get("version") is None:
        lines = [f"No changes applied to v{r['parent_version']}; nothing new was written."]
    else:
        lines = [f"Revised v{r['parent_version']} -> v{r['version']}: {r['classes']} classes, "
                 f"{r['properties']} properties (not approved)."]
    lines.append(f"Applied {len(r.get('applied') or [])} changes; skipped {len(r.get('skipped') or [])}.")
    lines += [f"Warning: {w}" for w in (r.get("warnings") or [])[:2]]
    return lines


def _refine(r: dict[str, Any]) -> Lines:
    rounds = r.get("rounds") or []
    scores = " -> ".join(f"{x['total']}/{x['max_total']}" for x in rounds) or "-"
    stop = r.get("stop_reason")
    lines = [f"Refined v{r['start_version']} -> v{r['final_version']} in {len(rounds)} rounds; scores {scores}.",
             f"Stopped: {str(stop).replace('_', ' ')}"
             + (f" ({', '.join(r['repeated'][:3])} came back)" if r.get("repeated") else "") + ".",
             f"Spent {_usd(r.get('spent_usd'))} of {_usd(r.get('approved_budget_usd'))} approved."]
    if rounds:
        lines.insert(1, f"Last judged: {_findings(rounds[-1]['findings'])}.")
    warned = [w for x in rounds for w in x.get("warnings") or []]
    if warned:
        reasons = [w.split(": ", 1)[1] for w in warned if ": " in w]
        codes = sorted({r.split(":", 1)[0] if re.match(r"^[a-z_]+:", r) else "other" for r in reasons})
        lines.append(f"Skipped {len(warned)} judge ops ({', '.join(codes[:4])}); see rounds[].warnings.")
    return lines


def _refinement(x: dict[str, Any]) -> Lines:
    if "critique" in x:
        c = x["critique"]
        return [f"From a critique of v{c['version']} scored {c['total']}/{c['max_total']} "
                f"({_findings(c['findings'])})."]
    rounds = x.get("rounds") or []
    scores = " -> ".join(f"{r['total']}/{r['max_total']}" for r in rounds) or "-"
    return [f"Refined from v{x['start_version']} ({len(rounds)} rounds, scores {scores}); "
            f"stopped: {str(x.get('stop_reason')).replace('_', ' ')}.",
            f"Findings fixed: {len(x.get('fixed') or [])}; remaining: {len(x.get('remaining') or [])}."]


def _review(r: dict[str, Any]) -> Lines:
    classes, props, diff, hygiene = r["classes"], r["properties"], r.get("diff"), r.get("hygiene") or {}
    top = ", ".join(c["name"] for c in classes.get("top", [])[:5])
    lines = [f"v{r['version']} ({r.get('origin')}): {classes['count']} classes, {props['count']} properties"
             + (", approved" if r.get("approved") else ", not approved") + ".",
             f"Top classes: {top or '-'}"]
    if diff and diff.get("from_version") is not None:
        a, rm = diff["added"], diff["removed"]
        lines.append(f"Since v{diff['from_version']}: +{a['classes']}/-{rm['classes']} classes, "
                     f"+{a['properties']}/-{rm['properties']} properties, {diff['changed']} changed.")
    dropped = sum((hygiene.get("dropped") or {}).values())
    regressions = len(r.get("coverage_regressions") or [])
    lines.append(f"Hygiene dropped {dropped}; {len(hygiene.get('warnings') or [])} warnings; "
                 f"{regressions} coverage regressions.")
    if r.get("refinement"):
        lines[1:2] = _refinement(r["refinement"])
    else:
        lines.append(f"Schema ID: {r['schema_id']}")
    return lines


def _approve(r: dict[str, Any]) -> Lines:
    verb = "was already approved" if r.get("already_approved") else "approved"
    lines = [f"v{r['version']} {verb} ({r['schema_id']})."]
    if r.get("warnings"):
        lines.append(f"{len(r['warnings'])} hygiene warnings; see `ontology-build review --version {r['version']}`.")
    return lines


def _export(r: dict[str, Any]) -> Lines:
    digest = r.get("owl_sha256") or r.get("jsonld_sha256")
    return [f"Exported v{r['version']} to {r['output']}", f"sha256: {digest}",
            f"Schema ID: {r['schema_id']}"]


def _import(r: dict[str, Any]) -> Lines:
    kind = "seed v0" if r.get("seed") else f"v{r['version']}"
    hygiene = r.get("hygiene") or {}
    return [f"Imported {r.get('file')} as {kind}: {r['classes']} classes, {r['properties']} properties.",
            f"Hygiene dropped {hygiene.get('dropped', 0)}; {len(hygiene.get('warnings') or [])} warnings.",
            f"Schema ID: {r['schema_id']}"]


def _status(r: dict[str, Any]) -> Lines:
    lines = []
    conn = r.get("connection")
    if conn:
        lines.append(_tenant(conn))
        lines.append(f"Generation {conn['generation_id']}; model {conn['model_deployment']}.")
    else:
        lines.append(f"Not connected ({r.get('state_dir')}).")
    versions = r.get("versions") or []
    approved = r.get("approved")
    if versions:
        lines.append(f"Versions: {', '.join('v%d' % v['version'] for v in versions[-6:])}; approved: "
                     + (f"v{approved['version']}" if approved else "none") + ".")
    run = r.get("last_run")
    if run:
        lines.append(f"Last run: {run['status']}, spent {_usd(run['spent_usd'])} of "
                     f"{_usd(run['approved_budget_usd'])}.")
    crit = r.get("latest_critique")
    if crit:
        lines.append(f"Latest critique: v{crit['version']} scored {crit['total']}/{crit['max_total']} "
                     f"({_findings(crit['findings'])}).")
    return lines


def _reconcile(r: dict[str, Any]) -> Lines:
    lines = [f"No drift; {len(r.get('open_runs') or [])} unfinished run(s)."]
    if r.get("lock_released"):
        lock = r["lock_released"]
        lines.append(f"Released a stale lock (pid {lock.get('pid')} on {lock.get('host')}).")
    return lines


def _show(r: dict[str, Any]) -> Lines:
    if r.get("mermaid"):
        return [r["mermaid"].rstrip("\n")]
    total = r["total"]
    names = [c["name"] for c in r.get("classes", [])] + [p["name"] for p in r.get("properties", [])]
    shown = ", ".join(names[:12]) + (" ..." if len(names) > 12 else "")
    return [f"v{r['version']}: {total['classes']} classes, {total['properties']} properties"
            + (" (approved)." if r.get("approved") else "."),
            f"Showing {len(names)} from offset {r.get('offset', 0)}: {shown or '-'}"]


def _evidence(r: dict[str, Any]) -> Lines:
    lines = [f"{r['type']} ({r['kind']}, v{r['version']}): {r['total']} cited passages."]
    for p in r.get("passages", [])[:3]:
        text = " ".join(str(p.get("excerpt") or "").split())
        lines.append(f"- {p['evidence_id']}: {text[:100]}" + ("..." if len(text) > 100 else ""))
    return lines


def _diff(r: dict[str, Any]) -> Lines:
    d = r["diff"]
    a, rm = d.get("added") or {}, d.get("removed") or {}
    return [f"v{r['a']} -> v{r['b']}: +{len(a.get('classes', []))}/-{len(rm.get('classes', []))} classes, "
            f"+{len(a.get('properties', []))}/-{len(rm.get('properties', []))} properties, "
            f"{len(d.get('changed') or [])} changed.",
            f"Coverage regressions: {len(d.get('coverage_regressions') or [])}."]


def _check(r: dict[str, Any]) -> Lines:
    return [f"{r['file']} passes the flat-owl profile.", f"sha256: {r['owl_sha256']}"]


def _diagram(r: dict[str, Any]) -> Lines:
    if not r.get("output"):
        return [r["mermaid"].rstrip("\n")]
    return [f"Wrote the v{r['version']} diagram ({r['classes']} classes, {r['edges']} relationship edges) "
            f"to {r['output']}."]


RENDERERS: dict[str, Callable[[dict[str, Any]], Lines]] = {
    "connect": _connect, "inspect": _inspect, "plan": _plan, "propose": _propose, "review": _review,
    "approve": _approve, "export": _export, "import": _import, "status": _status, "reconcile": _reconcile,
    "show": _show, "diagram": _diagram, "evidence": _evidence, "diff": _diff, "check": _check,
    "critique": _critique, "revise": _revise, "refine": _refine,
}


def render(verb: str, result: dict[str, Any]) -> str:
    """At most `MAX_LINES` lines ending with `Next step: ...` when the result has one."""
    if verb == "doctor":
        return _doctor(result)
    body = RENDERERS.get(verb, lambda r: [f"{verb}: {r.get('status', 'ok')}"])(result)
    if (verb == "show" and result.get("mermaid")) or (verb == "diagram" and not result.get("output")):
        return body[0]  # the diagram is the output; never truncated
    tail = [f"Next step: {result['next_step']}"] if result.get("next_step") else []
    if result.get("approval"):
        head = [] if verb == "plan" else body[:MAX_LINES - 2]  # the plan's card already says it all
        return "\n".join(head + list(result["approval"]) + tail)
    room = MAX_LINES - len(tail)
    return "\n".join(body[:room] + tail)
