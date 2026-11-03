"""Shared connection, evidence display, and preview transport for the lab notebooks."""

from dataclasses import dataclass, field
from html import escape
from importlib.metadata import version
import json
import os
from pathlib import Path
import re
from time import perf_counter
from typing import Any
from urllib.parse import urlsplit

from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import AzureError, ResourceNotFoundError
from azure.core.rest import HttpRequest
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import KnowledgeBase, SearchIndexKnowledgeSource
from azure.search.documents.knowledgebases import KnowledgeBaseRetrievalClient
from dotenv import load_dotenv
from IPython.display import HTML, SVG, display


API_VERSION = "2026-11-01-preview"
SDK_VERSION = "12.1.0a20260811002"
CLIENT_OPTIONS = {
    "retry_total": 0,
    "permit_redirects": False,
    "connection_timeout": 15,
    "read_timeout": 90,
    "logging_enable": False,
}


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value or "your-" in value:
        raise RuntimeError(f"Set {name} in the environment or the repository's .env file.")
    return value


def resource_name(value: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,127}", value):
        raise ValueError(f"Invalid Search resource name: {value!r}")
    return value


@dataclass(frozen=True)
class LabSettings:
    root: Path
    endpoint: str
    prefix: str
    content_prefix: str
    graph_prefix: str
    credential: AzureKeyCredential = field(repr=False)
    secrets: tuple[str, ...] = field(repr=False)

    def content_index(self, domain: str) -> str:
        return resource_name(f"{self.content_prefix}-{domain}")

    def graph_index(self, logical_name: str) -> str:
        name = f"{self.graph_prefix}-{logical_name}" if self.graph_prefix else logical_name
        return resource_name(name)

    def source_name(self, domain: str) -> str:
        return resource_name(f"{self.prefix}-lab-{domain}-source")

    def kb_name(self, kind: str) -> str:
        return resource_name(f"{self.prefix}-lab-{kind}")

    def search_client(self, index: str) -> SearchClient:
        return SearchClient(
            self.endpoint, resource_name(index), self.credential,
            api_version=API_VERSION, **CLIENT_OPTIONS,
        )

    def index_client(self) -> SearchIndexClient:
        return SearchIndexClient(
            self.endpoint, self.credential, api_version=API_VERSION, **CLIENT_OPTIONS,
        )

    def model(self) -> dict[str, Any]:
        return {
            "kind": "azureOpenAI",
            "azureOpenAIParameters": {
                "resourceUri": required_env("AZURE_OPENAI_ENDPOINT"),
                "apiKey": required_env("AZURE_OPENAI_KEY"),
                "deploymentId": required_env("AZURE_OPENAI_CHATGPT_DEPLOYMENT"),
                "modelName": required_env("AZURE_OPENAI_CHATGPT_MODEL_NAME"),
            },
        }

    def redact(self, text: str) -> str:
        for secret in self.secrets:
            if secret:
                text = text.replace(secret, "[REDACTED]")
        return text


def load_settings() -> LabSettings:
    root = next(
        (path for path in (Path.cwd(), *Path.cwd().parents)
         if (path / ".env.sample").is_file() and (path / "data" / "graph-data").is_dir()),
        None,
    )
    if root is None:
        raise RuntimeError("Open the notebook from inside the LAB673 repository.")
    load_dotenv(root / ".env", override=False)
    if version("azure-search-documents") != SDK_VERSION:
        raise RuntimeError(
            f"Select the prepared graph-lab kernel with azure-search-documents=={SDK_VERSION}. "
            "Its requirements are in src/notebooks/lab/requirements.txt; "
            "the earlier notebooks use a different SDK."
        )
    endpoint = required_env("AZURE_SEARCH_SERVICE_ENDPOINT").rstrip("/")
    origin = urlsplit(endpoint)
    if (
        origin.scheme != "https" or not origin.hostname or origin.username or origin.password
        or origin.port not in (None, 443) or origin.path or origin.query or origin.fragment
    ):
        raise ValueError("AZURE_SEARCH_SERVICE_ENDPOINT must be an HTTPS Search service root.")
    prefix = required_env("AZURE_SEARCH_LAB_RESOURCE_PREFIX")
    if not re.fullmatch(r"lab673-[a-z0-9]+(?:-[a-z0-9]+)*", prefix) or len(prefix) > 60:
        raise ValueError("Use your own lab673- resource prefix, at most 60 characters.")
    content_prefix = resource_name(os.environ.get("AZURE_SEARCH_CONTENT_INDEX_PREFIX", "cocoarynth"))
    graph_prefix = os.environ.get("AZURE_SEARCH_GRAPH_INDEX_PREFIX", "").strip()
    if graph_prefix and not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", graph_prefix):
        raise ValueError("AZURE_SEARCH_GRAPH_INDEX_PREFIX must match the loader's --prefix.")
    key = required_env("AZURE_SEARCH_ADMIN_KEY")
    return LabSettings(
        root, endpoint, prefix, content_prefix, graph_prefix, AzureKeyCredential(key),
        (key, os.environ.get("AZURE_OPENAI_KEY", "")),
    )


def require_complete(pipeline_response) -> None:
    if pipeline_response.http_response.status_code == 206:
        raise RuntimeError("Search returned HTTP 206. These results are incomplete; retry later.")


def _same_definition(expected: Any, actual: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key == "apiKey" or key in actual and _same_definition(value, actual[key])
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and len(expected) == len(actual) and all(
            _same_definition(left, right) for left, right in zip(expected, actual)
        )
    return expected == actual


def create_owned(settings: LabSettings, indexes: SearchIndexClient, kind: str,
                 definition: dict[str, Any]) -> str:
    """Create, or reuse an identical owned object; never update an existing object."""
    name = resource_name(definition["name"])
    if not name.startswith(settings.prefix + "-lab-"):
        raise ValueError("Only this attendee's lab-prefixed sources and bases may be created.")
    if kind == "source":
        getter, creator, model = (
            indexes.get_knowledge_source, indexes.create_knowledge_source, SearchIndexKnowledgeSource,
        )
    elif kind == "kb":
        getter, creator, model = indexes.get_knowledge_base, indexes.create_knowledge_base, KnowledgeBase
    else:
        raise ValueError("Expected source or kb.")
    owned = {
        **definition,
        "description": f"LAB673 SDK notebooks | {settings.prefix} | {definition.get('description', '')}",
    }
    try:
        try:
            current = getter(name)
        except ResourceNotFoundError:
            creator(model(owned), headers={"If-None-Match": "*"})
        else:
            if not _same_definition(owned, current.as_dict()):
                raise RuntimeError(
                    f"{name} already exists with a different definition or owner. "
                    "Choose a new AZURE_SEARCH_LAB_RESOURCE_PREFIX; nothing was overwritten."
                )
    except AzureError as error:
        raise RuntimeError(settings.redact(str(error))) from None
    return name


def retrieve(settings: LabSettings, name: str, request) -> tuple[dict[str, Any], float]:
    try:
        with KnowledgeBaseRetrievalClient(
            endpoint=settings.endpoint, credential=settings.credential,
            knowledge_base_name=resource_name(name),
            api_version=API_VERSION, **CLIENT_OPTIONS,
        ) as client:
            start = perf_counter()
            result = client.retrieve(request, raw_response_hook=require_complete)
            elapsed_ms = (perf_counter() - start) * 1000
    except AzureError as error:
        raise RuntimeError(settings.redact(str(error))) from None
    data = result.as_dict()
    if not data.get("references"):
        raise RuntimeError("Retrieval returned no references. Inspect the source configuration and question.")
    return data, elapsed_ms


def graph_query(settings: LabSettings, indexes: SearchIndexClient, index: str, gql: str,
                *, plan_only: bool = False) -> tuple[dict[str, Any], float]:
    """The pinned SDK has no typed GQL operation; keep its transport and credential."""
    body = {
        "gql": gql,
        "executionMode": "planOnly" if plan_only else "execute",
        "explain": ["physicalPlan"],
        "includeStatistics": True,
        "includeDiagnostics": True,
        "provenance": {"kind": "ids", "maxEvidencePerRow": 20},
    }
    request = HttpRequest(
        "POST",
        f"{settings.endpoint}/indexes('{resource_name(index)}')/docs/search.graph?api-version={API_VERSION}",
        json=body,
    )
    try:
        start = perf_counter()
        with indexes.send_request(request) as response:
            response.raise_for_status()
            if response.status_code != 200:
                raise RuntimeError(f"Graph query returned HTTP {response.status_code}, not a complete result.")
            data = response.json()
        elapsed_ms = (perf_counter() - start) * 1000
    except AzureError as error:
        raise RuntimeError(settings.redact(str(error))) from None
    errors = [
        item for item in data.get("@search.graphDiagnostics", [])
        if item.get("severity", "").lower() == "error"
    ]
    if errors:
        raise RuntimeError(settings.redact(json.dumps(errors)))
    return data, elapsed_ms


def show_table(rows: list[dict[str, Any]], columns: list[str], caption: str) -> None:
    header = "".join(f"<th>{escape(column)}</th>" for column in columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{escape(str(row.get(column, '')))}</td>" for column in columns) + "</tr>"
        for row in rows
    )
    display(HTML(
        f"<table><caption>{escape(caption)}</caption><thead><tr>{header}</tr></thead>"
        f"<tbody>{body}</tbody></table>"
    ))


def show_json(value: Any) -> None:
    display(HTML("<pre style='white-space:pre-wrap'>" + escape(json.dumps(value, indent=2)) + "</pre>"))


def show_retrieval(data: dict[str, Any]) -> None:
    for message in data.get("response", []):
        for content in message.get("content", []):
            if content.get("text"):
                display(HTML("<pre style='white-space:pre-wrap'>" + escape(content["text"]) + "</pre>"))
    show_table(
        [
            {
                "reference": item.get("id"), "kind": item.get("type"),
                "title": (item.get("sourceData") or {}).get("title", ""),
                "path": (item.get("sourceData") or {}).get("blob_path", ""),
                "passage": (item.get("sourceData") or {}).get("chunk", ""),
            }
            for item in data.get("references", [])
        ],
        ["reference", "kind", "title", "path", "passage"],
        "Actual returned references; open the matching original document before trusting an answer",
    )
    show_table(
        [
            {
                "id": item.get("id"), "activity": item.get("type"),
                "source": item.get("knowledgeSourceName", ""), "returned": item.get("count", ""),
                "elapsed ms": item.get("elapsedMs", ""),
            }
            for item in data.get("activity", [])
        ],
        ["id", "activity", "source", "returned", "elapsed ms"],
        "Service activity; overlapping activity durations must not be added as wall-clock time",
    )


def _svg_start(title: str, description: str, height: int) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 {height}" role="img">',
        f"<title>{escape(title)}</title><desc>{escape(description)}</desc>",
        '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" '
        'orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="#6a4b35"/></marker></defs>',
        f'<rect width="960" height="{height}" fill="#fbf8f2"/>',
        '<g font-family="Segoe UI, Arial, sans-serif" fill="#35251d">',
        f'<text x="28" y="34" font-size="21" font-weight="600">{escape(title)}</text>',
    ]


def show_farm_paths(rows: list[dict[str, Any]]) -> None:
    if not rows or len(rows) > 6:
        raise ValueError("The path diagram requires one to six returned batch/lot/farm rows.")
    batches = {(row["batch_id"], row["batch"]) for row in rows}
    lots = {(row["lot_id"], row["lot"]) for row in rows}
    if len(batches) != 1 or len(lots) != 1:
        raise ValueError("The diagram expects one shared batch and bean lot; inspect the returned table.")
    farms = sorted({(row["farm_id"], row["farm"]) for row in rows})
    height = max(300, 120 + 100 * len(farms))
    middle = (100 + 100 * len(farms)) / 2
    parts = _svg_start(
        "Two facts join through the same bean lot",
        "A Batch points to a BeanLot through madeFrom. Each returned Farm points to that "
        "same BeanLot through contributedTo. The accompanying table contains the exact IDs.",
        height,
    )

    def node(x: int, y: float, kind: str, label: str, color: str) -> None:
        parts.extend([
            f'<rect x="{x}" y="{y - 34}" width="214" height="68" rx="8" fill="white" '
            f'stroke="{color}" stroke-width="2"/>',
            f'<text x="{x + 107}" y="{y - 8}" text-anchor="middle" font-size="13" fill="{color}">'
            f"{escape(kind)}</text>",
            f'<text x="{x + 107}" y="{y + 17}" text-anchor="middle" font-size="16">'
            f"{escape(label)}</text>",
        ])

    parts.append(
        f'<path d="M244,{middle} H366" fill="none" stroke="#6a4b35" stroke-width="2" '
        'marker-end="url(#arrow)"/>'
    )
    parts.append(f'<text x="304" y="{middle - 12}" text-anchor="middle" font-size="14">madeFrom</text>')
    for number, (_, farm) in enumerate(farms):
        y = 100 + 100 * number
        parts.append(
            f'<path d="M716,{y} L580,{middle}" fill="none" stroke="#6a4b35" '
            'stroke-width="2" marker-end="url(#arrow)"/>'
        )
        parts.append(
            f'<rect x="588" y="{(y + middle) / 2 - 26}" width="120" height="19" fill="#fbf8f2"/>'
        )
        parts.append(
            f'<text x="648" y="{(y + middle) / 2 - 12}" text-anchor="middle" '
            'font-size="13">contributedTo</text>'
        )
        node(716, y, "Farm", farm, "#166454")
    node(30, middle, "Batch", next(iter(batches))[1], "#805124")
    node(366, middle, "BeanLot", next(iter(lots))[1], "#146c94")
    parts.append("</g></svg>")
    display(SVG("".join(parts)))


def show_topic_hierarchy(representatives: list[dict[str, Any]]) -> None:
    if not representatives:
        raise ValueError("No topic representatives were returned.")
    by_id = {row["community_id"]: row for row in representatives}
    roots = sorted(
        (row for row in representatives if not row.get("parent_id")),
        key=lambda row: row["community_id"],
    )
    if not roots or any(row.get("parent_id") and row["parent_id"] not in by_id for row in representatives):
        raise ValueError("The topic hierarchy has missing parents; inspect the restored sidecar.")
    if any(row.get("parent_id") in {child["community_id"] for child in representatives
                                  if child.get("parent_id")} for row in representatives):
        raise ValueError("This diagram expects the captured two-level hierarchy.")
    height = 100 + 112 * sum(
        max(1, sum(row.get("parent_id") == root["community_id"] for row in representatives))
        for root in roots
    )
    parts = _svg_start(
        "A topic groups passages, not business entities",
        "Parent representatives connect to their captured child communities. Labels use stored "
        "names when present and community ID prefixes otherwise. Counts are stored membership counts.",
        height,
    )
    offset = 84

    def label(row: dict[str, Any]) -> str:
        return row.get("label") or f"Unnamed {row['community_id'][:10]}"

    def node(x: int, y: float, row: dict[str, Any]) -> None:
        parts.extend([
            f'<rect x="{x}" y="{y - 28}" width="316" height="64" rx="8" '
            'fill="white" stroke="#805124" stroke-width="2"/>',
            f'<text x="{x + 16}" y="{y - 2}" font-size="16">{escape(label(row))}</text>',
            f'<text x="{x + 16}" y="{y + 22}" font-size="13">'
            f"level {row['level']} | {row['member_count']} memberships</text>",
        ])

    for root in roots:
        children = sorted(
            (row for row in representatives if row.get("parent_id") == root["community_id"]),
            key=lambda row: row["community_id"],
        )
        middle = offset + 56 * (max(1, len(children)) - 1)
        for number, child in enumerate(children):
            y = offset + 112 * number
            parts.append(
                f'<path d="M352,{middle} L580,{y}" fill="none" stroke="#6a4b35" '
                'stroke-width="2" marker-end="url(#arrow)"/>'
            )
            node(580, y, child)
        node(36, middle, root)
        offset += 112 * max(1, len(children))
    parts.append("</g></svg>")
    display(SVG("".join(parts)))
