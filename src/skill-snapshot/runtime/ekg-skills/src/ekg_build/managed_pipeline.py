from __future__ import annotations

import hashlib
from urllib.parse import urlparse

from ekg_core import grounding
from ekg_core.models import BuildSpec, Ontology

SEARCH_API_VERSION = "2026-08-01-preview"

# The service resolves nothing against a grounding index without a non-empty cascade.
GROUNDING_CASCADE = ("exact", "smart", "starts_with")

EDGE_FIELDS = {
    "assertionIdField": "id",
    "factIdField": "id",
    "subjectField": "subject",
    "predicateField": "predicate",
    "objectField": "object",
    "objectStringField": "object_string",
    "objectDoubleField": "object_double",
    "objectBoolField": "object_bool",
    "objectDateTimeField": "object_datetime",
    "subjectTypeField": "subject_type",
    "subjectIdField": "subject_id",
    "objectTypeField": "object_type",
    "objectIdField": "object_id",
    "confidenceField": "edge_confidence",
    "subjectConfidenceField": "s_confidence",
    "predicateConfidenceField": "p_confidence",
    "objectConfidenceField": "o_confidence",
    "sourceChunkIdField": "chunk_id",
    "sourceParentIdField": "parent_id",
    "graphNameField": "graph_name",
    "subjectIdDisplayNameField": "subject_id_display_name",
    "objectIdDisplayNameField": "object_id_display_name",
}


# Concurrent extraction calls when the BuildSpec does not set one. Live measurement showed
# one call at a time left 50K TPM deployments about 25% utilized with no throttling; see
# docs/performance.md for how to size this against deployment capacity.
DEFAULT_EXTRACTION_PARALLELISM = 4
# Reasoning effort for graph extraction when the BuildSpec does not set one. Unset, the
# service omits the parameter and the model default (medium for gpt-5 family) applies;
# live, low cut per-call latency ~2.6x and answered all demo questions as well as the default.
DEFAULT_EXTRACTION_REASONING_EFFORT = "low"


def extraction_settings(spec: BuildSpec) -> dict:
    """Effective graphExtraction settings apply writes, with defaults resolved.

    The Build plan ID includes this, so changing a default changes the approved payload's ID.
    """
    return {
        "pageDegreeOfParallelism": spec.extraction_parallelism or DEFAULT_EXTRACTION_PARALLELISM,
        "extraction": {"reasoningEffort": (spec.extraction_reasoning_effort
                                           or DEFAULT_EXTRACTION_REASONING_EFFORT)},
    }

def ontology_index(name: str) -> dict:
    text_fields = (
        "id", "subject", "predicate", "object", "object_string",
        "subject_type", "subject_id", "object_type", "object_id",
        "graph_name", "namespace", "parent_id", "chunk_id",
        "subject_id_display_name", "object_id_display_name",
    )
    fields = [
        {"name": field, "type": "Edm.String", "retrievable": True,
         "filterable": field not in {"subject_id_display_name", "object_id_display_name"},
         "sortable": True, "facetable": field != "id",
         "searchable": field in {"id", "subject", "predicate", "object",
                                  "subject_id_display_name", "object_id_display_name"},
         **({"key": True} if field == "id" else {})}
        for field in text_fields
    ]
    fields.extend(
        {"name": field, "type": typ, "retrievable": True, "filterable": True,
         **({"sortable": True} if typ != "Edm.Boolean" else {}),
         **({"facetable": True} if typ == "Edm.Double" else {})}
        for field, typ in (
            ("object_double", "Edm.Double"),
            ("object_bool", "Edm.Boolean"),
            ("object_datetime", "Edm.DateTimeOffset"),
            ("edge_confidence", "Edm.Double"),
            ("s_confidence", "Edm.Double"),
            ("p_confidence", "Edm.Double"),
            ("o_confidence", "Edm.Double"),
        )
    )
    return {"name": name, "fields": fields,
            "graphProfile": {"kind": "edgeList", "fields": dict(EDGE_FIELDS)}}


def ontology_rows(ontology: Ontology, graph_name: str) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()

    def add(subject: str, subject_type: str, predicate: str,
            obj: str, object_type: str) -> None:
        identity = f"{graph_name}|{subject}|{subject_type}|{predicate}|{obj}"
        row_id = hashlib.sha256(identity.encode()).hexdigest()
        # A predicate with several domain/range pairs repeats rows; the index keys on id.
        if row_id in seen:
            return
        seen.add(row_id)
        rows.append({
            "id": row_id,
            "subject": subject, "subject_type": subject_type,
            "predicate": predicate, "object": obj, "object_type": object_type,
            "subject_id": "", "object_id": "", "object_string": obj,
            "object_double": None, "object_bool": None, "object_datetime": None,
            "edge_confidence": 1.0, "s_confidence": 1.0,
            "p_confidence": 1.0, "o_confidence": 1.0,
            "graph_name": graph_name, "namespace": "",
            "parent_id": "", "chunk_id": "",
            "subject_id_display_name": "", "object_id_display_name": "",
        })

    for node in ontology.node_types:
        add(node, "NodeType", "rdf:type", "rdfs:Class", "Literal")
    for domain, predicate, range_name in ontology.edge_types:
        if any("`" in part for part in (domain, predicate, range_name)):
            raise ValueError("ontology graph labels cannot contain GQL delimiters")
        add(predicate, "EdgeType", "rdfs:domain", domain, "NodeType")
        add(predicate, "EdgeType", "rdfs:range", range_name, "NodeType")
    for subject, subject_type, text in ontology.descriptions:
        add(subject, subject_type, "rdfs:comment", text, "Literal")
    if not ontology.edge_types:
        raise ValueError("managed graph extraction requires ontology entity relationships")
    return rows


def knowledge_source(spec: BuildSpec, *, name: str, ontology_name: str,
                     graph_name: str, prefix: str) -> dict:
    target = spec.target
    if not target.subscription_id or not target.resource_group:
        raise ValueError("managed Blob ingestion needs explicit subscription and resource group")
    if not target.storage_endpoint or not target.storage_endpoint.startswith("https://"):
        raise ValueError("managed Blob ingestion needs an HTTPS Storage endpoint")
    host = urlparse(target.storage_endpoint).hostname or ""
    if not host.endswith(".blob.core.windows.net"):
        raise ValueError("managed Blob ingestion requires an Azure Storage account endpoint")
    if not target.openai_endpoint or not target.openai_endpoint.startswith("https://"):
        raise ValueError("managed graph ingestion needs an HTTPS Azure OpenAI endpoint")
    if not all((spec.embedding_deployment, spec.embedding_model, spec.chat_deployment,
                spec.chat_model, spec.embedding_dimensions)):
        raise ValueError("managed graph ingestion needs explicit model names, deployments and dimensions")
    if not spec.search_identity_resource_id:
        raise ValueError("managed graph ingestion requires a Search user-assigned identity")
    identity = {"@odata.type": "#Microsoft.Azure.Search.DataUserAssignedIdentity",
                "userAssignedIdentity": spec.search_identity_resource_id}

    def model(deployment: str, model_name: str) -> dict:
        return {"kind": "azureOpenAI",
                "azureOpenAIParameters": {
                    "resourceUri": target.openai_endpoint.rstrip("/"),
                    "deploymentId": deployment, "modelName": model_name,
                    "authIdentity": identity,
                }}

    storage_name = host.split(".", 1)[0]
    storage_id = (
        target.storage_resource_id if spec.source_manifest is not None else
        f"/subscriptions/{target.subscription_id}/resourceGroups/"
        f"{target.resource_group}/providers/Microsoft.Storage/storageAccounts/{storage_name}"
    )
    if not storage_id or storage_id.rsplit("/", 1)[-1].casefold() != storage_name.casefold():
        raise ValueError("managed Blob ingestion needs the exact destination Storage ARM ID")
    return {
        "name": name, "kind": "azureBlob",
        "azureBlobParameters": {
            "connectionString": f"ResourceId={storage_id}",
            "containerName": spec.storage_container, "folderPath": prefix,
            "ingestionParameters": {
                "identity": identity,
                "embeddingModel": model(spec.embedding_deployment, spec.embedding_model),
                "chatCompletionModel": model(spec.chat_deployment, spec.chat_model),
                "disableImageVerbalization": True,
                "contentExtractionMode": "minimal",
                "graphExtraction": {
                    "graphName": graph_name, "ontology": {"indexName": ontology_name},
                    "minEdgeConfidence": 0.0,
                    **({"grounding": {"cascade": list(GROUNDING_CASCADE),
                                  "index": {"indexName": spec.grounding_index}}}
                       if spec.grounding_index else {}),
                    **extraction_settings(spec),
                },
                **({"ingestionSchedule": {"interval": spec.ingestion_interval}}
                   if spec.ingestion_interval else {}),
            },
        },
    }


def grounding_live_blocker(adapter, spec: BuildSpec) -> str | None:
    """One read-only GET of the grounding index definition; None when it is usable."""
    from .adapters import SearchRequestError
    if not spec.grounding_index:
        return None
    try:
        definition = adapter.get_index(spec.grounding_index)
    except SearchRequestError as error:
        return grounding.classify(spec.grounding_index, None, status=error.status)
    return grounding.classify(
        spec.grounding_index, definition,
        profile_returned=getattr(adapter, "search_api_version", SEARCH_API_VERSION)
        == SEARCH_API_VERSION)


def generated(live: dict) -> dict[str, str]:
    blob = live.get("azureBlobParameters") or {}
    resources = blob.get("createdResources") or live.get("createdResources") or {}
    expected = {"datasource", "skillset", "indexer", "index", "graphIndex"}
    if not isinstance(resources, dict) or not expected.issubset(resources):
        raise ValueError("managed Knowledge Source did not report all generated resources")
    if any(not isinstance(resources[key], str) or not resources[key] for key in expected):
        raise ValueError("managed Knowledge Source reported invalid generated resource names")
    if resources["index"] == resources["graphIndex"]:
        raise ValueError("managed content and graph indexes must differ")
    name = live.get("name")
    if not isinstance(name, str) or (
        resources["index"] != f"{name}-index" or
        resources["graphIndex"] != f"{name}-graph-index"
    ):
        raise ValueError("managed generated index names differ from the versioned source")
    return {key: resources[key] for key in expected}
