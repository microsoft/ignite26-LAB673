"""On-disk records as dataclasses, canonical JSON conversion and a tiny JSON Schema validator.

Every record class has `SCHEMA` (a file in `ontology_core/schemas/`), `to_dict()`
and `from_dict(data, validate=True)`. `from_dict` validates first and raises
`SchemaError` with every violation; `state.read_record` maps that to
`STATE_INCOMPATIBLE`. No record carries a `schema_version`; provenance is
`tool_version` plus `prompt_sha256`.

The validator supports the draft 2020-12 subset the shipped schemas use:
`type` (string or list), `properties`, `required`, `additionalProperties: false`,
`items`, `enum`, `const`, `pattern`, `minimum`, `maximum`, `exclusiveMinimum`,
`minLength`, `maxLength`, `minItems`, `uniqueItems`, and local `$ref` to `#/$defs/<name>`.
"""

from __future__ import annotations

import json
import re
import types
from dataclasses import dataclass, field, fields, is_dataclass
from functools import cache
from importlib import resources
from typing import Any, ClassVar, Literal, Self, Union, get_args, get_origin, get_type_hints

from ontology_core import hashing

# --------------------------------------------------------------------------- validator


class SchemaError(ValueError):
    def __init__(self, schema: str, errors: list[str]) -> None:
        self.schema = schema
        self.errors = errors
        super().__init__(f"{schema}: " + "; ".join(errors[:5]))


_TYPES: dict[str, Any] = {
    "object": dict, "array": list, "string": str, "boolean": bool, "null": type(None),
}


def _is_type(value: Any, name: str) -> bool:
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, _TYPES[name])


def validate(instance: Any, schema: dict[str, Any], *, root: dict[str, Any] | None = None,
             path: str = "$") -> list[str]:
    """Return every violation of `schema` by `instance` as `"<json path>: <message>"`."""
    root = root if root is not None else schema
    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/$defs/"):
            raise ValueError(f"unsupported $ref {ref!r}")
        return validate(instance, root["$defs"][ref.removeprefix("#/$defs/")], root=root, path=path)
    errors: list[str] = []
    expected = schema.get("type")
    if expected is not None:
        names = expected if isinstance(expected, list) else [expected]
        if not any(_is_type(instance, n) for n in names):
            return [f"{path}: expected {'|'.join(names)}, got {type(instance).__name__}"]
    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: must equal {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: must be one of {schema['enum']!r}")
    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append(f"{path}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            errors.append(f"{path}: longer than {schema['maxLength']}")
        if "pattern" in schema and re.search(schema["pattern"], instance) is None:
            errors.append(f"{path}: does not match {schema['pattern']!r}")
    if _is_type(instance, "number"):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: below minimum {schema['minimum']}")
        if "exclusiveMinimum" in schema and instance <= schema["exclusiveMinimum"]:
            errors.append(f"{path}: must be above {schema['exclusiveMinimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: above maximum {schema['maximum']}")
    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path}: fewer than {schema['minItems']} items")
        if schema.get("uniqueItems"):
            seen = [json.dumps(v, sort_keys=True) for v in instance]
            if len(seen) != len(set(seen)):
                errors.append(f"{path}: items are not unique")
        if "items" in schema:
            for i, item in enumerate(instance):
                errors.extend(validate(item, schema["items"], root=root, path=f"{path}[{i}]"))
    if isinstance(instance, dict):
        props = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in instance:
                errors.append(f"{path}: missing required {name!r}")
        if schema.get("additionalProperties") is False:
            for name in instance:
                if name not in props:
                    errors.append(f"{path}: unexpected property {name!r}")
        for name, sub in props.items():
            if name in instance:
                errors.extend(validate(instance[name], sub, root=root, path=f"{path}.{name}"))
    return errors


@cache
def load_schema(name: str) -> dict[str, Any]:
    """Load `ontology_core/schemas/<name>.schema.json` from the installed package."""
    text = resources.files("ontology_core").joinpath("schemas", f"{name}.schema.json").read_text(encoding="utf-8")
    return json.loads(text)


def schema_names() -> list[str]:
    folder = resources.files("ontology_core").joinpath("schemas")
    return sorted(p.name.removesuffix(".schema.json") for p in folder.iterdir() if p.name.endswith(".schema.json"))


def check(name: str, instance: Any) -> None:
    """Raise `SchemaError` if `instance` violates schema `name`."""
    errors = validate(instance, load_schema(name))
    if errors:
        raise SchemaError(name, errors)


# --------------------------------------------------------------------------- conversion


def _to_json(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {f.metadata.get("json", f.name): _to_json(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, (list, tuple)):
        return [_to_json(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_json(v) for k, v in value.items()}
    return value


def _from_json(tp: Any, value: Any) -> Any:
    origin = get_origin(tp)
    if origin in (Union, types.UnionType):
        options = [a for a in get_args(tp) if a is not type(None)]
        if value is None:
            return None
        return _from_json(options[0], value) if len(options) == 1 else value
    if isinstance(tp, type) and is_dataclass(tp):
        hints = get_type_hints(tp)
        kwargs = {}
        for f in fields(tp):
            key = f.metadata.get("json", f.name)
            if key in value:
                kwargs[f.name] = _from_json(hints[f.name], value[key])
        return tp(**kwargs)
    if origin is list:
        (item,) = get_args(tp) or (Any,)
        return [_from_json(item, v) for v in value]
    if origin is dict:
        args = get_args(tp)
        return {k: _from_json(args[1], v) for k, v in value.items()} if args else dict(value)
    if tp is float and isinstance(value, int) and not isinstance(value, bool):
        return float(value)
    return value


class Record:
    """Base for on-disk records: schema-validated JSON in, canonical JSON out."""

    SCHEMA: ClassVar[str]

    def to_dict(self) -> dict[str, Any]:
        return _to_json(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, validate: bool = True) -> Self:
        if validate:
            check(cls.SCHEMA, data)
        return _from_json(cls, data)

    def validate(self) -> None:
        check(self.SCHEMA, self.to_dict())


# --------------------------------------------------------------------------- ontology

PropertyKind = Literal["object", "datatype"]
DATATYPE_RANGES: tuple[str, ...] = ("String", "Double", "Boolean", "DateTime")
Origin = Literal["propose", "import", "revise"]


def _sorted_unique(values: list[str]) -> list[str]:
    return sorted(set(values))


@dataclass
class ClassDef:
    name: str
    description: str
    evidence: list[str] = field(default_factory=list)
    parent: str | None = None
    seed: bool = False


@dataclass
class PropertyDef:
    name: str
    kind: PropertyKind
    domain: str
    range: str
    description: str
    evidence: list[str] = field(default_factory=list)
    seed: bool = False


@dataclass
class Ontology(Record):
    """`ontology.v<N>.json`. `to_dict()` is canonical: types sorted by name, evidence sorted and unique."""

    SCHEMA: ClassVar[str] = "ontology"
    version: int
    classes: list[ClassDef] = field(default_factory=list)
    properties: list[PropertyDef] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        classes = [{**_to_json(c), "evidence": _sorted_unique(c.evidence)}
                   for c in sorted(self.classes, key=lambda c: c.name)]
        properties = [{**_to_json(p), "evidence": _sorted_unique(p.evidence)}
                      for p in sorted(self.properties, key=lambda p: (p.name, p.domain, p.range))]
        return {"version": self.version, "classes": classes, "properties": properties}

    def canonical(self) -> Self:
        return type(self).from_dict(self.to_dict(), validate=False)

    def to_bytes(self) -> bytes:
        """The exact bytes of `ontology.v<N>.json`."""
        return hashing.canonical_bytes(self.to_dict())

    def schema_id(self) -> str:
        return hashing.schema_id_of_bytes(self.to_bytes())

    def class_names(self) -> list[str]:
        return sorted(c.name for c in self.classes)

    def find_class(self, name: str) -> ClassDef | None:
        return next((c for c in self.classes if c.name == name), None)

    def find_property(self, name: str) -> PropertyDef | None:
        return next((p for p in self.properties if p.name == name), None)


# --------------------------------------------------------------------------- config


@dataclass
class GrzBinding:
    descriptor_sha256: str
    search_endpoint: str
    physical_index: str
    generation_id: str
    source_index: str
    embedding_model_id: str


@dataclass
class ModelBinding:
    endpoint: str
    deployment: str
    input_price_per_1m: float
    output_price_per_1m: float
    subscription_id: str | None = None
    resource_group: str | None = None
    model_name: str | None = None
    model_version: str | None = None


@dataclass
class Config(Record):
    SCHEMA: ClassVar[str] = "config"
    tool_version: str
    tenant_id: str
    grz: GrzBinding
    model: ModelBinding
    created_at: str
    tenant_name: str | None = None


# --------------------------------------------------------------------------- plan


@dataclass
class PlanGrz:
    search_endpoint: str
    physical_index: str
    generation_id: str
    manifest_digest: str


@dataclass
class PlanSeed:
    path: str
    sha256: str
    format: str


@dataclass
class Sampling:
    level: int
    communities_at_level: int
    passages: int
    excerpt_chars: int
    shard_chars: int
    shards: int
    audit_mode: Literal["full", "cited"]


@dataclass
class PlanModel:
    endpoint: str
    deployment: str
    reasoning_effort: Literal["minimal", "low", "medium", "high"]
    proposal_max_output_tokens: int
    audit_max_output_tokens: int
    input_price_per_1m: float
    output_price_per_1m: float
    model_name: str | None = None
    model_version: str | None = None


@dataclass
class Estimate:
    calls: int
    input_tokens: int
    output_tokens: int
    usd: float


@dataclass
class Caps:
    max_spend_usd: float
    max_tokens: int | None = None


@dataclass
class PlanQueries:
    path: str
    sha256: str
    count: int


@dataclass
class PlanCritique:
    """A critique/refine plan: judges `base_version` (by schema ID) for up to `max_rounds` rounds of
    `judge_samples` model calls each, scored by the median. `judge_deployment`/`judge_reasoning_effort` are
    None when the judge uses the connected deployment and `--reasoning-effort`; `plan.model` holds the
    resolved judge deployment, effort and prices either way."""

    kind: Literal["critique", "refine"]
    base_version: int
    base_schema_id: str
    max_rounds: int
    max_output_tokens: int
    queries: PlanQueries | None = None
    judge_samples: int = 1
    noise_margin: int = 0
    judge_deployment: str | None = None
    judge_reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = None


@dataclass
class Plan(Record):
    """`plans/<plan_id>.json`. `plan_id` is derived by `compute_id()`; use `with_id()` before saving.

    A propose plan has `grz` and `sampling` and no `critique`; a critique/refine plan has `critique` and
    `grz = sampling = None` (it reads only local state). `critique` is omitted from the JSON when None so
    propose plan IDs are unchanged."""

    SCHEMA: ClassVar[str] = "plan"
    tool_version: str
    plan_id: str
    created_at: str
    tenant_id: str
    grz: PlanGrz | None
    seed: PlanSeed | None
    sampling: Sampling | None
    model: PlanModel
    prompt_sha256: str
    estimate: Estimate
    caps: Caps
    critique: PlanCritique | None = None

    def to_dict(self) -> dict[str, Any]:
        data = _to_json(self)
        if self.critique is None:
            data.pop("critique")
        return data

    def compute_id(self) -> str:
        return hashing.plan_id(self.to_dict())

    def with_id(self) -> Self:
        self.plan_id = self.compute_id()
        return self

    def id_matches(self) -> bool:
        return self.plan_id == self.compute_id()


# --------------------------------------------------------------------------- versions


@dataclass
class Drop:
    name: str
    reason: str


@dataclass
class HygieneReport:
    """`dropped`: removed types; `renamed`/`qualified`: `{"from", "to"}` pairs; `warnings`: free text codes."""

    dropped: list[Drop] = field(default_factory=list)
    renamed: list[dict[str, str]] = field(default_factory=list)
    qualified: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class VersionModel:
    deployment: str
    model_name: str | None = None
    model_version: str | None = None


@dataclass
class Version(Record):
    """`versions/v<N>/version.json`."""

    SCHEMA: ClassVar[str] = "version"
    version: int
    schema_id: str
    origin: Origin
    tool_version: str
    created_at: str
    hygiene: HygieneReport = field(default_factory=HygieneReport)
    parent_version: int | None = None
    plan_id: str | None = None
    grz_generation_id: str | None = None
    prompt_sha256: str | None = None
    model: VersionModel | None = None


@dataclass
class EvidenceRecord(Record):
    """One line of `evidence.v<N>.jsonl`."""

    SCHEMA: ClassVar[str] = "evidence"
    evidence_id: str
    chunk_id: str
    source_id: str
    community_id: str
    level: int
    excerpt: str


@dataclass
class Approval(Record):
    SCHEMA: ClassVar[str] = "approval"
    version: int
    schema_id: str
    approved_at: str
    actor: str


@dataclass
class TypeNames:
    classes: list[str] = field(default_factory=list)
    properties: list[str] = field(default_factory=list)


@dataclass
class Change:
    kind: Literal["class", "property"]
    name: str
    field: str
    before: Any
    after: Any


@dataclass
class CoverageRegression:
    name: str
    kind: Literal["class", "property"]
    had_evidence: int


@dataclass
class Diff(Record):
    """`versions/v<N>/diff.v<N>.json`. `from_version` is null when there is no parent."""

    SCHEMA: ClassVar[str] = "diff"
    to_version: int
    from_version: int | None = None
    added: TypeNames = field(default_factory=TypeNames)
    removed: TypeNames = field(default_factory=TypeNames)
    changed: list[Change] = field(default_factory=list)
    coverage_regressions: list[CoverageRegression] = field(default_factory=list)
    seed_violations: list[str] = field(default_factory=list)


@dataclass
class ExportGrz:
    search_endpoint: str
    physical_index: str
    generation_id: str
    source_index: str


@dataclass
class ExportManifest(Record):
    """`exports/export-manifest.<hash12>.json`. `grz`/`model` are null for import-only versions."""

    SCHEMA: ClassVar[str] = "export-manifest"
    schema_id: str
    version: int
    format: Literal["owl", "ttl"]
    owl_sha256: str
    output: str
    base_iri: str
    tool_version: str
    created_at: str
    profile: Literal["flat-owl"] = "flat-owl"
    plan_id: str | None = None
    prompt_sha256: str | None = None
    model: VersionModel | None = None
    grz: ExportGrz | None = None


@dataclass
class JsonLdExportManifest(Record):
    """`exports/jsonld-export-manifest.<hash12>.json`; never replaces the OWL manifest or current pointer."""

    SCHEMA: ClassVar[str] = "jsonld-export-manifest"
    schema_id: str
    version: int
    format: Literal["jsonld"]
    jsonld_sha256: str
    output: str
    base_iri: str
    tool_version: str
    created_at: str
    profile: Literal["inline-jsonld-v1"] = "inline-jsonld-v1"
    plan_id: str | None = None
    prompt_sha256: str | None = None
    model: VersionModel | None = None
    grz: ExportGrz | None = None


# --------------------------------------------------------------------------- run files


@dataclass
class Passage:
    """One sampled chunk. `source_id` and `excerpt` are null until `propose` fetches the text."""

    evidence_id: str
    chunk_id: str
    community_id: str
    level: int
    source_id: str | None = None
    excerpt: str | None = None


@dataclass
class Shard:
    index: int
    community_ids: list[str]
    evidence_ids: list[str]


@dataclass
class Sample(Record):
    """`runs/<plan_id>/sample.json`: the passages chosen and how they are packed into shards."""

    SCHEMA: ClassVar[str] = "sample"
    plan_id: str
    level: int
    excerpt_chars: int
    shard_chars: int
    passages: list[Passage] = field(default_factory=list)
    shards: list[Shard] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class LockInfo(Record):
    """`.lock` contents."""

    SCHEMA: ClassVar[str] = "lock"
    pid: int
    host: str
    verb: str
    started_at: str


RECORDS: dict[str, type[Record]] = {
    cls.SCHEMA: cls for cls in (Ontology, Config, Plan, Version, EvidenceRecord, Approval, Diff,
                                ExportManifest, JsonLdExportManifest, Sample, LockInfo)
}
