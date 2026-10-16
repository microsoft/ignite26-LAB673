"""`doctor`, `connect`, `inspect` and `plan`.

Glue only: probes and sampling live in grz_reader/sampler, pricing in planning.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from ontology_core import doctor, hashing, state
from ontology_core.errors import Blocked
from ontology_core.journal import Journal, StateLock
from ontology_core.model import Config, GrzBinding, ModelBinding
from ontology_core.state import StatePaths

PLAN_HINT = "ontology-build plan --model-max-spend-usd <usd>"


# --------------------------------------------------------------------------- doctor


def doctor_context(paths: StatePaths, *, tenant_id: str | None = None, grz_descriptor: str | None = None,
                   model_endpoint: str | None = None, model_deployment: str | None = None,
                   subscription_id: str | None = None, model_resource_group: str | None = None,
                   plugin_root: str | None = None) -> doctor.DoctorContext:
    """Flags first, then `config.json` (a broken config is reported by the `state_dir` check, not here)."""
    config: Config | None = None
    try:
        config = state.load_config(paths) if paths.config.is_file() else None
    except Blocked:
        config = None
    descriptor = Path(grz_descriptor) if grz_descriptor else (paths.descriptor if paths.descriptor.is_file() else None)
    same_tenant = config is not None and (tenant_id is None or tenant_id == config.tenant_id)
    return doctor.DoctorContext(
        state_dir=paths.root,
        config=config,
        tenant_id=tenant_id or (config.tenant_id if config else None),
        tenant_name=config.tenant_name if same_tenant and config else None,
        grz_descriptor=descriptor,
        model_endpoint=model_endpoint or (config.model.endpoint if config else None),
        model_deployment=model_deployment or (config.model.deployment if config else None),
        subscription_id=subscription_id or (config.model.subscription_id if config else None),
        model_resource_group=model_resource_group or (config.model.resource_group if config else None),
        plugin_root=doctor.plugin_root_from(plugin_root),
    )


def next_step_after_doctor(paths: StatePaths) -> str:
    from ontology_consume import service

    try:
        return str(service.status(paths)["next_step"])
    except Blocked as exc:
        return exc.next_step


def run_doctor(ctx: doctor.DoctorContext, paths: StatePaths, *,
               checks: tuple[str, ...] = doctor.CHECKS) -> dict[str, Any]:
    results = doctor.run(ctx, checks=checks)
    ok_next = next_step_after_doctor(paths) if checks == doctor.CHECKS else "ontology-consume status"
    return doctor.result(results, next_step_if_ok=ok_next)


# --------------------------------------------------------------------------- connect


def _data(result: dict[str, Any], check: str) -> dict[str, Any]:
    return next((c.get("data", {}) for c in result.get("checks", []) if c["name"] == check), {})


def connect(paths: StatePaths, *, tenant_id: str, grz_descriptor: str, model_endpoint: str, model_deployment: str,
            input_price_per_1m: float, output_price_per_1m: float, subscription_id: str | None = None,
            model_resource_group: str | None = None) -> dict[str, Any]:
    """Refuse a conflicting binding, run every doctor check, and only on a clean doctor write `config.json` and
    the descriptor copy. Journal `artifact_written` and `connected`."""
    from ontology_build import grz_reader

    tenant_id = (tenant_id or "").strip()
    try:
        uuid.UUID(tenant_id)
    except ValueError:
        raise Blocked("TENANT_REQUIRED", f"--tenant-id must be a tenant GUID, got {tenant_id!r}") from None
    source = Path(grz_descriptor).expanduser()
    endpoint = model_endpoint.rstrip("/")
    existing: Config | None = state.load_config(paths) if paths.config.is_file() else None
    if existing is not None:
        descriptor = grz_reader.load_descriptor(source)
        clashes = []
        if existing.grz.generation_id != descriptor.generation_id:
            clashes.append(f"generation {existing.grz.generation_id} -> {descriptor.generation_id}")
        if existing.model.endpoint.rstrip("/") != endpoint or existing.model.deployment != model_deployment:
            clashes.append(f"model {existing.model.deployment} -> {model_deployment}")
        if existing.tenant_id != tenant_id:
            clashes.append(f"tenant {existing.tenant_id} -> {tenant_id}")
        if clashes:
            raise Blocked("CONFIG_CONFLICT", f"{paths.root} is bound to a different " + "; ".join(clashes))

    ctx = doctor.DoctorContext(state_dir=paths.root, tenant_id=tenant_id, grz_descriptor=source,
                               model_endpoint=endpoint, model_deployment=model_deployment,
                               subscription_id=subscription_id, model_resource_group=model_resource_group,
                               plugin_root=doctor.plugin_root_from(None))
    checks = doctor.run(ctx)
    verdict = doctor.result(checks, next_step_if_ok=PLAN_HINT)
    tenant = {"tenant_id": tenant_id, "tenant_name": ctx.tenant_name}
    if verdict["status"] != "ok":
        verdict.update(tenant)
        return verdict

    descriptor = ctx.cache["descriptor"]
    deployment = _data(verdict, "model_deployment")
    paths = state.ensure_state(paths.root)
    raw = source.read_bytes()
    with StateLock(paths, "connect"):
        journal = Journal(paths)
        descriptor_sha = state.atomic_write(paths.descriptor, raw)
        journal.append("artifact_written", path=paths.relative(paths.descriptor), sha256=descriptor_sha)
        config = Config(
            tool_version=state.tool_version(),
            tenant_id=tenant_id,
            tenant_name=ctx.tenant_name,
            created_at=existing.created_at if existing else state.utc_now(),
            grz=GrzBinding(descriptor_sha256=hashing.sha256_bytes(raw), search_endpoint=descriptor.search_endpoint,
                           physical_index=descriptor.physical_index, generation_id=descriptor.generation_id,
                           source_index=descriptor.source_index, embedding_model_id=descriptor.embedding_model_id),
            model=ModelBinding(endpoint=endpoint, deployment=model_deployment, input_price_per_1m=input_price_per_1m,
                               output_price_per_1m=output_price_per_1m, subscription_id=subscription_id,
                               resource_group=model_resource_group, model_name=deployment.get("model_name"),
                               model_version=deployment.get("model_version")),
        )
        config_sha = state.save_config(paths, config)
        journal.append("artifact_written", path=paths.relative(paths.config), sha256=config_sha)
        journal.append("connected", tenant_id=tenant_id, generation_id=descriptor.generation_id,
                       model_deployment=model_deployment)
    return {
        "status": "ok",
        **tenant,
        "generation_id": descriptor.generation_id,
        "physical_index": descriptor.physical_index,
        "model_deployment": model_deployment,
        "model_name": config.model.model_name,
        "model_version": config.model.model_version,
        "reconnected": existing is not None,
        "checks": verdict["checks"],
        "next_step": "ontology-build inspect",
    }


# --------------------------------------------------------------------------- reader


def reader_for(paths: StatePaths, config: Config | None = None) -> tuple[Config, Any]:
    """A live GrzReader for the connected generation. The saved descriptor must still match `config.json`."""
    from ontology_build import grz_reader
    from ontology_core.http import EgressPolicy

    config = config or state.load_config(paths)
    if not paths.descriptor.is_file():
        raise Blocked("GRZ_DESCRIPTOR_UNREADABLE", f"{paths.descriptor} is missing; rerun connect")
    descriptor = grz_reader.load_descriptor(paths.descriptor)
    if descriptor.generation_id != config.grz.generation_id:
        raise Blocked("GRZ_GENERATION_CHANGED", f"descriptor generation {descriptor.generation_id} is not the "
                      f"connected {config.grz.generation_id}")
    policy = EgressPolicy(search_endpoint=descriptor.search_endpoint, physical_index=descriptor.physical_index)
    search = grz_reader.live_search(descriptor, config.tenant_id, policy)
    return config, grz_reader.GrzReader(descriptor, search)


def inspect(paths: StatePaths) -> dict[str, Any]:
    from ontology_build import grz_reader, sampler

    config, reader = reader_for(paths)
    manifest = reader.manifest()
    representatives = reader.representatives()
    members = reader.members(None)
    grz_reader.check_manifest(manifest, representatives, members)
    per_level = sampler.levels(representatives)
    level = sampler.default_level(representatives)
    rows = []
    for n in sorted(per_level):
        reps = [r for r in representatives if r.level == n]
        labeled = sum(1 for r in reps if r.label)
        chunks = {m.chunk_id for m in members if m.level == n}
        rows.append({"level": n, "communities": per_level[n], "members": sum(r.member_count for r in reps),
                     "chunks": len(chunks), "label_coverage": round(labeled / len(reps), 3) if reps else 0.0})
    chunks_at_default = next((r["chunks"] for r in rows if r["level"] == level), 0)
    passages = sampler.default_passages(per_level.get(level, 0), chunks_at_default)
    return {
        "status": "ok",
        "tenant_id": config.tenant_id,
        "tenant_name": config.tenant_name,
        "generation_id": config.grz.generation_id,
        "health": manifest.health,
        "levels": rows,
        "default_level": level,
        "default_passages": passages,
        "next_step": PLAN_HINT,
    }


# --------------------------------------------------------------------------- plan


def plan_request(*, max_spend_usd: float, seed: str | None = None, level: int | None = None,
                 passages: int | None = None, excerpt_chars: int = 1200, shard_chars: int = 60000,
                 reasoning_effort: str = "low", max_output_tokens: int = 8000, max_tokens: int | None = None) -> Any:
    from ontology_build import planning

    return planning.PlanRequest(max_spend_usd=max_spend_usd, seed=Path(seed).expanduser() if seed else None,
                                level=level, passages=passages, excerpt_chars=excerpt_chars, shard_chars=shard_chars,
                                reasoning_effort=reasoning_effort,  # type: ignore[arg-type]
                                max_output_tokens=max_output_tokens, max_tokens=max_tokens)


def plan(paths: StatePaths, request: Any) -> dict[str, Any]:
    from ontology_build import planning

    config, reader = reader_for(paths)
    seed = planning.load_seed(paths, request.seed)
    built, _sample = planning.build_plan(config, reader, request, seed=seed)
    planning.require_within_cap(built, request)
    with StateLock(paths, "plan"):
        planning.save_plan(paths, Journal(paths), built)
    return dict(planning.result(built))
