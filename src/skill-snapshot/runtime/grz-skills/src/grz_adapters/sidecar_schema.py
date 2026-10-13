"""Sidecar Search index definition, created-index checks and upload document shape."""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

from grz_core.contracts import ContractError, SIDECAR_VERSION, canonical_json, require_public

from .azure_source import get_field

KINDS = {"representative", "membership", "evidence", "manifest"}
REQUIRED_FIELDS = {
    "representative": ("community_id", "level", "member_count", "centroid", "embedding_model_id", "label_status"),
    "membership": ("community_id", "level", "chunk_id"),
    "evidence": ("chunk_id", "source_id", "text", "chunk_vector", "community_ids"),
    "manifest": ("payload",),
}
SCHEMA_RESOURCE = "sidecar-index.schema.json"


def load_sidecar_schema() -> dict[str, Any]:
    """Load the versioned sidecar Search definition shipped as package data."""
    try:
        schema = json.loads(resources.files(__package__).joinpath(SCHEMA_RESOURCE).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ContractError("SIDECAR_SCHEMA_UNAVAILABLE", "Cannot read versioned sidecar Search definition") from exc
    if schema.get("version") != SIDECAR_VERSION or schema.get("vector_algorithm") != "exhaustiveKnn":
        raise ContractError("SCHEMA_UNSUPPORTED", "Unsupported sidecar Search definition")
    return schema


def generation_index_definition(index: str, dimension: int, schema: dict[str, Any]) -> dict[str, Any]:
    fields = []
    for field in schema["fields"]:
        definition = {key: value for key, value in field.items() if key not in {"dimensions", "vectorSearchProfile"}}
        if field.get("dimensions") == "source.dimension":
            definition["vectorSearchDimensions"] = dimension
        if "vectorSearchProfile" in field:
            definition["vectorSearchProfile"] = field["vectorSearchProfile"]
        fields.append(definition)
    return {
        "name": index,
        "fields": fields,
        "vectorSearch": {
            "algorithms": [{"name": schema["vector_profile"], "kind": "exhaustiveKnn",
                            "exhaustiveKnnParameters": {"metric": "cosine"}}],
            "profiles": [{"name": schema["vector_profile"], "algorithm": schema["vector_profile"]}],
        },
    }


def sdk_index_model(definition: dict[str, Any]) -> Any:
    """Use SDK models only for a real Azure client; offline fakes take dictionaries."""
    from azure.search.documents.indexes.models import (
        ExhaustiveKnnAlgorithmConfiguration, ExhaustiveKnnParameters, SearchField,
        SearchIndex, VectorSearch, VectorSearchProfile,
    )

    fields = []
    for field in definition["fields"]:
        fields.append(SearchField(
            name=field["name"], type=field["type"],
            key=field.get("key", False), searchable=field.get("searchable", False),
            filterable=field.get("filterable", False), sortable=field.get("sortable", False),
            hidden=not field.get("retrievable", True),
            vector_search_dimensions=field.get("vectorSearchDimensions"),
            vector_search_profile_name=field.get("vectorSearchProfile"),
        ))
    profile = definition["vectorSearch"]["profiles"][0]["name"]
    return SearchIndex(
        name=definition["name"], fields=fields,
        vector_search=VectorSearch(
            algorithms=[ExhaustiveKnnAlgorithmConfiguration(
                name=profile, parameters=ExhaustiveKnnParameters(metric="cosine"))],
            profiles=[VectorSearchProfile(name=profile, algorithm_configuration_name=profile)],
        ),
    )


def check_created_index(observed: Any, definition: dict[str, Any], dimension: int, vector_profile: str) -> None:
    """Search can silently normalize a definition; confirm every flag, type and the vector config survived."""
    fields = definition["fields"]
    actual_fields = {get_field(f, "name"): f for f in get_field(observed, "fields", [])}
    if set(actual_fields) != {f["name"] for f in fields}:
        raise ContractError("SIDECAR_SCHEMA_MISMATCH", "Created index fields differ from candidate contract")
    for field in fields:
        observed_field = actual_fields[field["name"]]
        for flag in ("key", "searchable", "filterable", "sortable"):
            if bool(get_field(observed_field, flag, False)) != bool(field.get(flag, False)):
                raise ContractError("SIDECAR_SCHEMA_MISMATCH", f"Created field {field['name']!r} changed {flag}")
        if bool(get_field(observed_field, "hidden", False)) == bool(field.get("retrievable", True)):
            raise ContractError("SIDECAR_SCHEMA_MISMATCH", f"Created field {field['name']!r} changed retrievability")
        if str(get_field(observed_field, "type")) != field["type"]:
            raise ContractError("SIDECAR_SCHEMA_MISMATCH", f"Created field {field['name']!r} changed type")
    for field in fields:
        if field.get("vectorSearchDimensions") is None and field.get("vectorSearchProfile") is None:
            continue
        vector = actual_fields[field["name"]]
        if (get_field(vector, "vector_search_dimensions", get_field(vector, "vectorSearchDimensions")) != dimension
                or get_field(vector, "vector_search_profile_name", get_field(vector, "vectorSearchProfile")) != vector_profile):
            raise ContractError("SIDECAR_SCHEMA_MISMATCH", "Created index vector profile/dimension does not match")
    search = get_field(observed, "vector_search", get_field(observed, "vectorSearch"))
    algorithms = get_field(search, "algorithms", [])
    if not any(get_field(a, "kind") == "exhaustiveKnn" and get_field(a, "name") == vector_profile for a in algorithms):
        raise ContractError("SIDECAR_SCHEMA_MISMATCH", "Created index did not retain exhaustiveKnn")


def prepare_document(doc: dict[str, Any]) -> dict[str, Any]:
    """Validate one sidecar document and encode the manifest payload as retrievable JSON text."""
    fields = {f["name"] for f in load_sidecar_schema()["fields"]}
    if set(doc) - fields or not all(doc.get(name) for name in ("id", "sort_key", "generation_id")):
        raise ContractError("SIDECAR_DOCUMENT_INVALID", "Unknown field or missing stable identity")
    if doc.get("kind") not in KINDS:
        raise ContractError("SIDECAR_DOCUMENT_INVALID", "Unknown sidecar document kind")
    require_public(doc.get("visibility"))
    if any(field not in doc or doc[field] is None for field in REQUIRED_FIELDS[doc["kind"]]):
        raise ContractError("SIDECAR_DOCUMENT_INVALID", "Document kind has missing required fields")
    result = dict(doc)
    if result["kind"] == "manifest":
        result["payload"] = canonical_json(result["payload"]) if isinstance(result["payload"], dict) else result["payload"]
        if not isinstance(result["payload"], str):
            raise ContractError("SIDECAR_DOCUMENT_INVALID", "Manifest payload must encode as retrievable JSON text")
    return result