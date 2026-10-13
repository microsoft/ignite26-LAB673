from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from urllib.parse import urlsplit


class OntologyMode(str, Enum):
    NONE = "none"
    SCHEMA_ORG = "schema_org"
    OWL_FILE = "owl_file"


class Capability(str, Enum):
    DOCUMENT_RETRIEVAL = "document_retrieval"
    GRAPH_RETRIEVAL = "graph_retrieval"
    AGENTIC_RETRIEVAL = "agentic_retrieval"


class SourceKind(str, Enum):
    LOCAL_PATH = "local_path"
    ZIP_ARCHIVE = "zip_archive"
    BLOB_PREFIX = "blob_prefix"
    SHAREPOINT_LIBRARY = "sharepoint_library"


class RequestedOutcome(str, Enum):
    GRAPH_BUILD = "graph_build"
    KB_HANDOFF = "kb_handoff"


class KnowledgeSourceKind(str, Enum):
    AZURE_BLOB = "azure_blob"
    FILE = "file"
    SHAREPOINT = "sharepoint"


@dataclass(frozen=True)
class SourceLocator:
    kind: SourceKind
    reference: str
    resource_id: str | None = None
    container: str | None = None
    prefix: str | None = None
    library_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, SourceKind) or not isinstance(self.reference, str) or not self.reference.strip():
            raise ValueError("source requires a known kind and nonempty reference")
        if self.kind in {SourceKind.BLOB_PREFIX, SourceKind.SHAREPOINT_LIBRARY}:
            parsed = urlsplit(self.reference)
            if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                    or parsed.password or parsed.query or parsed.fragment):
                raise ValueError("remote source reference must be credential-free HTTPS without query or fragment")
        if self.kind is SourceKind.BLOB_PREFIX:
            if (not isinstance(self.resource_id, str) or not self.resource_id
                    or not isinstance(self.container, str)
                    or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])", self.container)
                    or not isinstance(self.prefix, str)):
                raise ValueError("blob source requires account resource ID, container and explicit prefix")
            if (self.prefix.startswith("/") or "\\" in self.prefix
                    or any(part in {".", ".."} for part in self.prefix.split("/"))):
                raise ValueError("blob prefix must be a relative, forward-slash-separated scope")
        elif self.kind is SourceKind.SHAREPOINT_LIBRARY:
            if (not isinstance(self.library_id, str) or not self.library_id.strip()
                    or any(value is not None for value in (
                        self.resource_id, self.container, self.prefix,
                    ))):
                raise ValueError("SharePoint source requires site reference and library ID")
        elif any(value is not None for value in (
            self.resource_id, self.container, self.prefix, self.library_id,
        )):
            raise ValueError("local source does not accept remote scope fields")
        if self.kind is SourceKind.BLOB_PREFIX and self.library_id is not None:
            raise ValueError("blob source does not accept a SharePoint library ID")

    @property
    def source_id(self) -> str:
        return stable_id("source", self)


@dataclass(frozen=True)
class ManifestItem:
    source_id: str
    original_uri: str
    citation_uri: str
    media_type: str
    version_or_hash: str
    materialized_blob_path: str | None = None
    transform_id: str | None = None
    transform_version: str | None = None
    observed_classification: str | None = None
    observed_permissions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value.strip() for value in (
            self.source_id, self.original_uri, self.citation_uri, self.media_type,
            self.version_or_hash,
        )):
            raise ValueError("manifest item requires source ID, origin, citation, media type and version")
        if self.materialized_blob_path is not None and (
            not isinstance(self.materialized_blob_path, str)
            or not self.materialized_blob_path
            or self.materialized_blob_path.startswith("/")
            or "\\" in self.materialized_blob_path
            or any(part in {".", ".."} for part in self.materialized_blob_path.split("/"))
        ):
            raise ValueError("materialized Blob path must be a relative path")


def manifest_item_from_json(item: dict[str, Any]) -> ManifestItem:
    if not isinstance(item, dict):
        raise ValueError("manifest item must be an object")
    permissions = item.get("observed_permissions", [])
    if not isinstance(permissions, list) or any(
        not isinstance(permission, str) for permission in permissions
    ):
        raise ValueError("manifest observed_permissions must be a list of strings")
    return ManifestItem(**{**item, "observed_permissions": tuple(permissions)})


@dataclass(frozen=True)
class SourceManifest:
    version: Literal["1"]
    source: SourceLocator
    observed_at: str
    items: tuple[ManifestItem, ...]
    transform_config_id: str = "identity"

    def __post_init__(self) -> None:
        if self.version != "1" or not isinstance(self.source, SourceLocator):
            raise ValueError("unsupported source manifest version or locator")
        if (not isinstance(self.observed_at, str) or not self.observed_at
                or not isinstance(self.transform_config_id, str) or not self.transform_config_id):
            raise ValueError("manifest requires observation time and transform configuration ID")
        try:
            observed = datetime.fromisoformat(self.observed_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("manifest observation must be an ISO 8601 timestamp") from error
        if observed.tzinfo is None:
            raise ValueError("manifest observation requires a timezone")
        if any(not isinstance(item, ManifestItem) for item in self.items):
            raise ValueError("manifest items must be typed")
        if len({item.source_id for item in self.items}) != len(self.items):
            raise ValueError("manifest source IDs must be unique")

    @property
    def digest(self) -> str:
        payload = {
            "source": asdict(self.source),
            "items": [asdict(item) for item in sorted(self.items, key=lambda item: item.source_id)],
            "transform_config_id": self.transform_config_id,
            "version": self.version,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return f"sha256:{hashlib.sha256(raw).hexdigest()}"

    @property
    def document_count(self) -> int:
        return len(self.items)


@dataclass(frozen=True)
class Target:
    subscription_id: str | None = None
    resource_group: str | None = None
    location: str | None = None
    search_endpoint: str | None = None
    storage_endpoint: str | None = None
    openai_endpoint: str | None = None
    content_understanding_endpoint: str | None = None
    search_resource_id: str | None = None
    storage_resource_id: str | None = None
    openai_resource_id: str | None = None

    def __repr__(self) -> str:
        return _legacy_compatible_repr(self, {
            "search_resource_id", "storage_resource_id", "openai_resource_id",
        })


@dataclass(frozen=True)
class Ontology:
    schema_id: str
    source_kind: Literal["schema_org", "owl_file"]
    source_reference: str
    node_types: tuple[str, ...] = ()
    edge_types: tuple[tuple[str, str, str], ...] = ()
    properties: tuple["OntologyProperty", ...] = ()
    # (name, "NodeType" | "EdgeType", text) rows sent to extraction as rdfs:comment.
    descriptions: tuple[tuple[str, str, str], ...] = ()


@dataclass(frozen=True)
class OntologyProperty:
    name: str
    domain: str | None = None
    range: str | None = None
    value_kind: Literal["literal", "entity"] = "literal"
    description: str = ""


@dataclass(frozen=True)
class NetworkSpec:
    vnet_name: str
    subnet_name: str
    vnet_cidr: str
    subnet_cidr: str


@dataclass(frozen=True)
class PublicTestSpec:
    tenant_id: str
    egress_ips: tuple[str, ...]
    expires_at: str
    synthetic_data_only: bool = False
    mode: Literal["ip_allowlist", "entra_only"] = "ip_allowlist"


# Token-based deployment SKUs, where capacity is thousands of tokens per minute. Provisioned
# SKUs measure capacity in PTUs and are out of scope for Provision.
MODEL_DEPLOYMENT_SKUS = ("GlobalStandard", "DataZoneStandard", "Standard")


@dataclass(frozen=True)
class ModelDeploymentSpec:
    role: Literal["embedding", "chat"]
    name: str
    model: str
    version: str
    sku: str = "GlobalStandard"
    capacity: int = 50  # thousands of tokens per minute

    def __post_init__(self) -> None:
        if self.role not in ("embedding", "chat"):
            raise ValueError("model deployment role must be embedding or chat")
        if not isinstance(self.name, str) or not re.fullmatch(
                r"[a-zA-Z0-9][a-zA-Z0-9_.-]{1,63}", self.name):
            raise ValueError("invalid model deployment name")
        if any(not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value)
               for value in (self.model, self.version)):
            raise ValueError("model deployment needs an explicit model name and version")
        if self.sku not in MODEL_DEPLOYMENT_SKUS:
            raise ValueError(f"model deployment SKU must be one of {', '.join(MODEL_DEPLOYMENT_SKUS)}")
        if (not isinstance(self.capacity, int) or isinstance(self.capacity, bool)
                or not 1 <= self.capacity <= 10_000):
            raise ValueError("model deployment capacity must be 1..10000 thousand TPM")


@dataclass(frozen=True)
class BuildAccessSpec:
    """What Build needs beyond the three services: the Search identity, the private
    container and the six role assignments (operator x4, Search identity x2)."""
    search_identity_name: str
    storage_container: str
    operator_object_id: str
    operator_principal_type: Literal["User", "ServicePrincipal"] = "User"

    def __post_init__(self) -> None:
        if not isinstance(self.search_identity_name, str) or not re.fullmatch(
                r"[a-zA-Z0-9][a-zA-Z0-9_-]{2,127}", self.search_identity_name):
            raise ValueError("invalid Search identity name")
        if (not isinstance(self.storage_container, str)
                or not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", self.storage_container)
                or "--" in self.storage_container):
            raise ValueError("invalid Blob container name")
        if not isinstance(self.operator_object_id, str) or not re.fullmatch(
                r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}",
                self.operator_object_id):
            raise ValueError("operator object ID must be the exact Entra object ID GUID")
        if self.operator_principal_type not in ("User", "ServicePrincipal"):
            raise ValueError("operator principal type must be User or ServicePrincipal")


@dataclass(frozen=True)
class ProvisioningSpec:
    target: Target
    search_name: str
    storage_name: str
    openai_name: str
    content_understanding_name: str | None = None
    search_sku: str = "basic"
    create_resource_group: bool = False
    network: NetworkSpec | None = None
    public_test: PublicTestSpec | None = None
    model_deployments: tuple[ModelDeploymentSpec, ...] = ()
    build_access: BuildAccessSpec | None = None

    def __post_init__(self) -> None:
        roles = [item.role for item in self.model_deployments]
        names = [item.name.lower() for item in self.model_deployments]
        if len(set(roles)) != len(roles) or len(set(names)) != len(names):
            raise ValueError("model deployments need unique roles and names")


@dataclass(frozen=True)
class TrialSample:
    """A trial build extracts a deterministic sample of a larger approved manifest."""
    size: int
    corpus_documents: int
    corpus_digest: str
    selection: str = "sha256-rank-v1"

    def __post_init__(self) -> None:
        if (not isinstance(self.size, int) or isinstance(self.size, bool) or self.size < 1
                or not isinstance(self.corpus_documents, int)
                or self.corpus_documents < 1):
            raise ValueError("trial sample size and corpus document count must be positive")
        if not isinstance(self.corpus_digest, str) or not self.corpus_digest:
            raise ValueError("trial sample requires the full corpus manifest digest")


@dataclass(frozen=True)
class BuildSpec:
    target: Target
    corpus_source: str
    ontology_mode: OntologyMode = OntologyMode.NONE
    ontology_path: str | None = None
    schema_org_profile: str | None = None
    schema_org_version: str | None = None
    resolve_imports: bool = False
    vector_retrieval: bool = True
    graph_retrieval: bool = False
    agentic_retrieval: bool = False
    embedding_deployment: str | None = None
    embedding_model: str | None = None
    embedding_dimensions: int | None = None
    chat_deployment: str | None = None
    chat_model: str | None = None
    search_identity_resource_id: str | None = None
    tenant_id: str | None = None
    search_sku: str | None = None
    build_journal: str | None = None
    storage_container: str = "source-documents"
    source: SourceLocator | None = None
    source_manifest: SourceManifest | None = None
    requested_outcome: RequestedOutcome | None = None
    knowledge_source_kind: KnowledgeSourceKind | None = None
    # Concurrent managed graph-extraction LLM calls (KS graphExtraction.pageDegreeOfParallelism).
    extraction_parallelism: int | None = None
    extraction_reasoning_effort: str | None = None
    # Knowledge Source ingestionSchedule interval (ISO 8601, PT5M..P1D); unset uses the
    # service default of one day, so a build longer than one 2-hour run waits a day per run.
    ingestion_interval: str | None = None
    # Existing Search index with an edgeList graph profile; validated, never created.
    grounding_index: str | None = None
    # `<object-id>:<principal type>` readers granted on the new generation's indexes.
    readers: tuple[str, ...] = ()
    trial: TrialSample | None = None

    def __post_init__(self) -> None:
        if self.trial is not None and (
                not isinstance(self.trial, TrialSample) or self.source_manifest is None):
            raise ValueError("a trial build needs a typed TrialSample and a source manifest")
        if isinstance(self.readers, str) or any(not isinstance(item, str) or not re.fullmatch(
                r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}:(User|ServicePrincipal|Group)",
                item) for item in self.readers or ()):
            raise ValueError("readers must be lowercase <object-id>:User|ServicePrincipal|Group")
        object.__setattr__(self, "readers", tuple(sorted(set(self.readers or ()))))
        if self.extraction_parallelism is not None and (
                not isinstance(self.extraction_parallelism, int)
                or isinstance(self.extraction_parallelism, bool)
                or not 1 <= self.extraction_parallelism <= 256):
            raise ValueError("extraction_parallelism must be an integer from 1 to 256")
        if self.extraction_reasoning_effort not in (None, "minimal", "low", "medium", "high"):
            raise ValueError("extraction_reasoning_effort must be minimal, low, medium or high")
        if self.ingestion_interval is not None:
            ingestion_interval_minutes(self.ingestion_interval)
        if self.grounding_index is not None and not isinstance(self.grounding_index, str):
            raise ValueError("grounding_index must be a string")
        if self.source is not None and not isinstance(self.source, SourceLocator):
            raise ValueError("source must be a typed SourceLocator")
        if self.source_manifest is not None and not isinstance(self.source_manifest, SourceManifest):
            raise ValueError("source_manifest must be a typed SourceManifest")
        if self.source_manifest is not None and self.source_manifest.source != self.source:
            raise ValueError("manifest locator differs from build source")
        if self.requested_outcome is not None and not isinstance(self.requested_outcome, RequestedOutcome):
            raise ValueError("requested_outcome must be a known outcome")
        if self.knowledge_source_kind is not None and not isinstance(self.knowledge_source_kind, KnowledgeSourceKind):
            raise ValueError("knowledge_source_kind must be a known Knowledge Source kind")

    def __repr__(self) -> str:
        return _legacy_compatible_repr(self, {
            "source", "source_manifest", "requested_outcome", "knowledge_source_kind",
            "extraction_parallelism", "extraction_reasoning_effort", "ingestion_interval",
            "grounding_index", "readers", "trial",
        })


def ingestion_interval_minutes(value: str) -> int:
    """Minutes in a Knowledge Source ingestion interval: PT<n>M, PT<n>H or P1D, 5..1440."""
    match = re.fullmatch(r"PT(\d+)M|PT(\d+)H|P1D", value) if isinstance(value, str) else None
    minutes = (None if match is None else 1440 if value == "P1D" else
               int(match[1]) if match[1] else int(match[2]) * 60)
    if minutes is None or not 5 <= minutes <= 1440:
        raise ValueError("ingestion_interval must be PT<n>M, PT<n>H or P1D, from 5 minutes "
                         "to 1 day (for example PT5M)")
    return minutes


@dataclass(frozen=True)
class RouteDecision:
    outcome: RequestedOutcome
    knowledge_source_kind: KnowledgeSourceKind
    capability: Literal["verified_path", "contract_only", "unsupported"]
    evidence: tuple[str, ...] = ()
    uncertainty: tuple[str, ...] = ()
    blocked_by: tuple[str, ...] = ()


@dataclass(frozen=True)
class PreflightResult:
    plan_id: str
    status: Literal["blocked", "unverified"]
    code: str
    next_action: str
    route: RouteDecision | None
    scope: dict[str, Any]
    events: tuple["Event", ...]
    phase: Literal["preflight"] = "preflight"
    observed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Operation:
    id: str
    plane: Literal["provision", "build", "consume"]
    action: str
    resource: str
    name: str
    risk: str = "read_only"
    reversible: bool = False
    requires_approval: bool = False
    evidence: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class Plan:
    plan_id: str
    operations: tuple[Operation, ...]
    required_permissions: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    blocked_by: tuple[str, ...] = ()
    route: RouteDecision | None = None
    scope: dict[str, Any] = field(default_factory=dict)
    # Planning estimates only; never part of plan_id or journaled scope.
    estimates: dict[str, Any] = field(default_factory=dict)
    # Grounding alignment instructions only; derived from the spec, so not part of plan_id.
    grounding: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        if not result["grounding"]:
            del result["grounding"]
        return result


@dataclass(frozen=True)
class Event:
    operation_id: str
    status: Literal["planned", "started", "verified", "blocked", "failed", "completed"]
    message: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DeploymentDescriptor:
    deployment_id: str
    build_id: str
    ontology: dict[str, Any] | None
    capabilities: dict[str, bool]
    endpoints: dict[str, str]
    source_provenance: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        if self.source_provenance is None:
            result.pop("source_provenance")
        return result


def _legacy_compatible_repr(value: Any, appended_fields: set[str]) -> str:
    parts = (
        f"{item.name}={getattr(value, item.name)!r}"
        for item in fields(value)
        if item.name not in appended_fields or getattr(value, item.name) not in (None, ())
    )
    return f"{type(value).__name__}({', '.join(parts)})"


def stable_id(prefix: str, value: Any) -> str:
    payload = asdict(value) if hasattr(value, "__dataclass_fields__") else value
    if isinstance(value, Target):
        for name in ("search_resource_id", "storage_resource_id", "openai_resource_id"):
            if getattr(value, name) is None:
                payload.pop(name)
    elif isinstance(value, (BuildSpec, ProvisioningSpec)):
        for name in ("search_resource_id", "storage_resource_id", "openai_resource_id"):
            if getattr(value.target, name) is None:
                payload["target"].pop(name)
        if isinstance(value, BuildSpec):
            for name in ("source", "source_manifest", "requested_outcome", "knowledge_source_kind",
                         "extraction_parallelism", "extraction_reasoning_effort",
                         "ingestion_interval", "grounding_index", "trial"):
                if getattr(value, name) is None:
                    payload.pop(name)
            if not value.readers:
                payload.pop("readers")
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=lambda item: item.value if isinstance(item, Enum) else str(item),
    ).encode()
    return f"{prefix}-{hashlib.sha256(raw).hexdigest()[:16]}"
