"""`export` and `import`."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Literal

from ontology_core import diff as diff_mod
from ontology_core import hygiene, jsonld_profile, jsonld_write, owl_read, owl_write, profile, state
from ontology_core.errors import Blocked
from ontology_core.journal import Journal, StateLock
from ontology_core.model import ExportGrz, ExportManifest, JsonLdExportManifest, Ontology, Version
from ontology_core.state import StatePaths

ExportFormat = Literal["owl", "ttl", "jsonld"]
FALLBACK_SOURCE = "ontology"


def _export_version(paths: StatePaths, version: int | None) -> int:
    if version is not None:
        n = state.resolve_version(paths, version)
        approval = state.load_approval(paths, n)
        if approval is None:
            meta = state.read_record(paths.version_json(n), Version)
            raise Blocked("NOT_APPROVED", f"v{n} is not approved", n=n, id=meta.schema_id)
        return n
    approved = state.latest_approved_version(paths)
    if approved is not None:
        return approved
    latest = state.resolve_version(paths, None)
    meta = state.read_record(paths.version_json(latest), Version)
    raise Blocked("NOT_APPROVED", "no version is approved yet", n=latest, id=meta.schema_id)


def _base_iri(paths: StatePaths, base_iri: str | None) -> str:
    if base_iri:
        return owl_write.validate_base_iri(base_iri)
    source = FALLBACK_SOURCE
    if paths.config.is_file():
        source = state.load_config(paths).grz.source_index or FALLBACK_SOURCE
    return owl_write.default_base_iri(source)


def record_current(paths: StatePaths, n: int, meta: Version, ontology: Ontology, approved_at: str, *,
                   data: bytes | None = None, iri: str | None = None, exported_to: str | None = None) -> dict[str, Any]:
    """Point the per-user `current` record at approved version `n` (see `ontology_core.current`)."""
    from ontology_core import current

    iri = iri or _base_iri(paths, None)
    if data is None:
        data = owl_write.write(ontology, base_iri=iri, version_info=owl_write.version_info(n, meta.schema_id))
    generation = meta.grz_generation_id
    if generation is None and meta.origin != "import" and paths.config.is_file():
        generation = state.load_config(paths).grz.generation_id
    return current.record(owl=data, ontology_iri=iri, classes=len(ontology.classes),
                          properties=len(ontology.properties), source_generation=generation,
                          approved_at=approved_at, schema_id=meta.schema_id, version=n, state_dir=paths.root,
                          exported_to=exported_to)


# Output names that promise a syntax other than RDF/XML; writing RDF/XML under them misleads every reader.
_OTHER_RDF_SUFFIXES = frozenset({".ttl", ".nt", ".n3", ".nq", ".trig", ".jsonld"})


def export(paths: StatePaths, *, output: Path, version: int | None = None, fmt: ExportFormat = "owl",
           base_iri: str | None = None, force: bool = False) -> dict[str, Any]:
    """Write the approved version in the requested format with a format-specific manifest.
    `version=None` means latest approved. The profile is validated before writing.

    Returns an OWL or JSON-LD format-specific digest and manifest. JSON-LD is a separate artifact and does not
    replace the approved OWL `current` pointer.

    Raises: EXPORT_FORMAT_UNSUPPORTED, VERSION_NOT_FOUND, NOT_APPROVED, SCHEMA_ID_MISMATCH, OUTPUT_EXISTS,
        BASE_IRI_INVALID, PROFILE_VIOLATION, JSONLD_EXPORT_UNSUPPORTED, JSONLD_PROFILE_VIOLATION, STATE_LOCKED.
    """
    if fmt == "jsonld":
        return _export_jsonld(paths, output=output, version=version, base_iri=base_iri, force=force)
    if fmt != "owl":
        raise Blocked("EXPORT_FORMAT_UNSUPPORTED", f"`--format {fmt}` is not available")
    if Path(output).suffix.lower() in _OTHER_RDF_SUFFIXES:
        raise Blocked("EXPORT_FORMAT_UNSUPPORTED",
                      f"{Path(output).name} names another syntax, but `--format owl` writes RDF/XML")
    n = _export_version(paths, version)
    meta, ontology = state.load_version(paths, n)
    approval = state.load_approval(paths, n)
    if approval is None or approval.schema_id != meta.schema_id:
        raise Blocked("NOT_APPROVED", f"the approval for v{n} is for a different schema ID", n=n, id=meta.schema_id)
    target = Path(output).expanduser().resolve()
    if target.exists() and not force:
        raise Blocked("OUTPUT_EXISTS", f"{target} already exists")
    iri = _base_iri(paths, base_iri)
    data = owl_write.write(ontology, base_iri=iri, version_info=owl_write.version_info(n, meta.schema_id))
    profile.require_valid(data, file=str(target))
    with StateLock(paths, "export"):
        owl_sha = _write_output(target, data)
        grz = None
        if meta.origin == "propose" and paths.config.is_file():
            binding = state.load_config(paths).grz
            grz = ExportGrz(search_endpoint=binding.search_endpoint, physical_index=binding.physical_index,
                            generation_id=meta.grz_generation_id or binding.generation_id,
                            source_index=binding.source_index)
        manifest = ExportManifest(schema_id=meta.schema_id, version=n, format="owl", owl_sha256=owl_sha,
                                  output=str(target), base_iri=iri, tool_version=state.tool_version(),
                                  created_at=state.utc_now(), plan_id=meta.plan_id, prompt_sha256=meta.prompt_sha256,
                                  model=meta.model, grz=grz)
        manifest_path = paths.export_manifest(meta.schema_id)
        journal = Journal(paths)
        sha = state.write_record(manifest_path, manifest)
        journal.append("artifact_written", path=paths.relative(manifest_path), sha256=sha)
        journal.append("export_written", version=n, schema_id=meta.schema_id, format="owl", output=str(target),
                       sha256=owl_sha)
    pointer = record_current(paths, n, meta, ontology, approval.approved_at, data=data, iri=iri,
                             exported_to=str(target))
    return {
        "status": "ok",
        "version": n,
        "schema_id": meta.schema_id,
        "format": "owl",
        "output": str(target),
        "owl_sha256": owl_sha,
        "base_iri": iri,
        "current": pointer["path"],
        "manifest": str(manifest_path),
        "next_step": f"ontology-consume check {target}",
    }


def _export_jsonld(paths: StatePaths, *, output: Path, version: int | None, base_iri: str | None,
                   force: bool) -> dict[str, Any]:
    if Path(output).suffix.lower() != ".jsonld":
        raise Blocked("EXPORT_FORMAT_UNSUPPORTED", "JSON-LD export requires a .jsonld output path")
    n = _export_version(paths, version)
    meta, ontology = state.load_version(paths, n)
    approval = state.load_approval(paths, n)
    if approval is None or approval.schema_id != meta.schema_id:
        raise Blocked("NOT_APPROVED", f"the approval for v{n} is for a different schema ID", n=n, id=meta.schema_id)
    target = Path(output).expanduser().resolve()
    if target.exists() and not force:
        raise Blocked("OUTPUT_EXISTS", f"{target} already exists")
    iri = _base_iri(paths, base_iri)
    data = jsonld_write.write(ontology, base_iri=iri, version_info=owl_write.version_info(n, meta.schema_id))
    jsonld_profile.require_valid(data, file=str(target))
    with StateLock(paths, "export"):
        jsonld_sha = _write_output(target, data)
        grz = None
        if meta.origin == "propose" and paths.config.is_file():
            binding = state.load_config(paths).grz
            grz = ExportGrz(search_endpoint=binding.search_endpoint, physical_index=binding.physical_index,
                            generation_id=meta.grz_generation_id or binding.generation_id,
                            source_index=binding.source_index)
        manifest = JsonLdExportManifest(
            schema_id=meta.schema_id, version=n, format="jsonld", jsonld_sha256=jsonld_sha,
            output=str(target), base_iri=iri, tool_version=state.tool_version(),
            created_at=state.utc_now(), plan_id=meta.plan_id, prompt_sha256=meta.prompt_sha256,
            model=meta.model, grz=grz)
        manifest_path = paths.jsonld_export_manifest(meta.schema_id)
        journal = Journal(paths)
        sha = state.write_record(manifest_path, manifest)
        journal.append("artifact_written", path=paths.relative(manifest_path), sha256=sha)
        journal.append("export_written", version=n, schema_id=meta.schema_id, format="jsonld", output=str(target),
                       sha256=jsonld_sha)
    return {
        "status": "ok",
        "version": n,
        "schema_id": meta.schema_id,
        "format": "jsonld",
        "output": str(target),
        "jsonld_sha256": jsonld_sha,
        "base_iri": iri,
        "manifest": str(manifest_path),
        "next_step": f"provide {target} contents as ontology.inlineJsonLd with graphName to compatible graph extraction",
    }


def _write_output(target: Path, data: bytes) -> str:
    """Atomic write of a user-chosen file: its directory is created with default permissions, not user-only."""
    state.ensure_dir(target.parent, private=False)
    return state.atomic_write(target, data)


def import_file(paths: StatePaths, file: Path, *, as_seed: bool = False) -> dict[str, Any]:
    """Import an ontology file as a new version (origin `import`), or as `v0` with every item `seed=True` when
    `as_seed` and no v0 exists. Runs hygiene with `evidence_ids=None`.

    Returns `{status:"ok", version, schema_id, classes, properties, hygiene, next_step}`.

    Raises: IMPORT_UNSUPPORTED_FORMAT, IMPORT_INVALID, IMPORT_HAS_IMPORTS, EMPTY_ONTOLOGY, STATE_LOCKED.
    """
    source = Path(file).expanduser()
    if not source.is_file():
        raise Blocked("IMPORT_INVALID", f"{source} does not exist or is not a file",
                      next_step="pass the path of an existing .owl, .rdf or .ttl file")
    read = owl_read.read_file(source)
    paths = state.ensure_state(paths.root)
    with StateLock(paths, "import"):
        existing = state.list_versions(paths)
        seed_slot = as_seed and 0 not in existing
        n = 0 if seed_slot else state.next_version(paths)
        ontology, report = hygiene.clean(read.raw, None, None, version=n, origin="import")
        if seed_slot:
            ontology = _as_seed(ontology)
        warnings = list(read.warnings) + list(report.warnings)
        if as_seed and not seed_slot:
            warnings.append("seed_exists: v0 already exists; imported as a normal version")
        report = dataclasses.replace(report, warnings=warnings)
        parent = existing[-1] if existing else None
        prev = state.load_version(paths, parent)[1] if parent is not None else None
        change = None if n == 0 else diff_mod.diff(prev, ontology)
        schema_id = ontology.schema_id()
        meta = Version(version=n, schema_id=schema_id, origin="import", tool_version=state.tool_version(),
                       created_at=state.utc_now(), hygiene=report, parent_version=parent)
        state.write_version(paths, Journal(paths), version=meta, ontology=ontology, evidence=[], diff=change)
    return {
        "status": "ok",
        "version": n,
        "schema_id": schema_id,
        "seed": seed_slot,
        "file": str(source),
        "classes": len(ontology.classes),
        "properties": len(ontology.properties),
        "hygiene": {"dropped": len(report.dropped), "renamed": len(report.renamed), "warnings": warnings},
        "next_step": f"ontology-build review --version {n}",
    }


def _as_seed(ontology: Ontology) -> Ontology:
    return dataclasses.replace(
        ontology,
        classes=[dataclasses.replace(c, seed=True) for c in ontology.classes],
        properties=[dataclasses.replace(p, seed=True) for p in ontology.properties],
    )
