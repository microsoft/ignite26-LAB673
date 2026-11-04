"""Shared SDK setup and resource ownership for the LAB673 notebooks."""

import importlib.metadata
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from azure.core import MatchConditions
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
import azure.search.documents as search_documents
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import KnowledgeBase, KnowledgeSource


SDK_VERSION = "12.1.0a20261027002"
DEFAULT_PREVIEW_INDEX_PREFIX = "lab673-preview-cocoarynth"


def _check_response(response) -> None:
    status = response.http_response.status_code
    if status == 206:
        raise RuntimeError("Search returned HTTP 206: these results are incomplete.")
    if status < 400:
        return
    try:
        detail = json.loads(response.http_response.text())["error"]["message"]
    except (json.JSONDecodeError, KeyError, TypeError):
        detail = "The service did not return a JSON error message."
    if not isinstance(detail, str):
        detail = "The service did not return a text error message."
    for secret in (
        response.http_request.headers.get("api-key", ""),
        os.environ.get("AZURE_OPENAI_KEY", ""),
    ):
        if secret:
            detail = detail.replace(secret, "[REDACTED]")
    guidance = {
        402: " Ask the service owner about the Standard Knowledge Retrieval prerequisite.",
        412: " Another request changed this resource. Rerun the cell to read its current state.",
        429: " The service is busy or its allowance is exhausted. Retry later.",
    }.get(status, "")
    error_type = ResourceNotFoundError if status == 404 else HttpResponseError
    raise error_type(f"Search returned HTTP {status}: {detail}{guidance}") from None


CLIENT_OPTIONS = {
    "retry_total": 0,
    "permit_redirects": False,
    "connection_timeout": 15,
    "read_timeout": 120,
    "raw_response_hook": _check_response,
}


def load_environment(repo_root: Path) -> None:
    version = importlib.metadata.version("azure-search-documents")
    if version != SDK_VERSION or search_documents.__version__ != SDK_VERSION:
        raise RuntimeError(
            f"Use the prepared notebook kernel with azure-search-documents=={SDK_VERSION}; "
            f"found installed {version}, imported {search_documents.__version__}. "
            "Install the notebook requirements, restart the kernel, "
            "and run the cells in order."
        )
    env_file = repo_root / ".env"
    if env_file.is_file():
        from dotenv import load_dotenv

        load_dotenv(env_file, override=False)


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value or "your-" in value:
        raise RuntimeError(f"Set {name} in your environment or the root .env file.")
    return value


def service_endpoint(value: str) -> str:
    origin = urlsplit(value)
    if (
        origin.scheme != "https"
        or not origin.hostname
        or origin.username
        or origin.password
        or origin.port not in (None, 443)
        or origin.path not in ("", "/")
        or origin.query
        or origin.fragment
    ):
        raise ValueError("The Search endpoint must be an HTTPS service origin.")
    return value.rstrip("/")


class NotebookResources:
    def __init__(self, client: SearchIndexClient, resource_prefix: str):
        if not re.fullmatch(r"lab673-[a-z0-9](?:[a-z0-9-]{0,40}[a-z0-9])?", resource_prefix):
            raise ValueError("Use a unique lab673- resource prefix of at most 49 characters.")
        self.client = client
        self.resource_prefix = resource_prefix
        self.owner = f"LAB673 SDK notebooks: {resource_prefix} | "
        # Preserve ownership of resources created by the earlier REST notebooks.
        self.legacy_owner = f"LAB673 REST notebooks: {resource_prefix} | "

    def _current(self, name, get):
        if not re.fullmatch(r"[a-z0-9-]+", name) or not name.startswith(f"{self.resource_prefix}-"):
            raise ValueError("Only this notebook prefix's knowledge sources and bases may be changed.")
        try:
            current = get(name)
        except ResourceNotFoundError:
            return None
        if not (current.description or "").startswith((self.owner, self.legacy_owner)):
            raise RuntimeError(f"Refusing to change a resource not owned by these notebooks: {name}")
        if not current.e_tag:
            raise RuntimeError(f"Cannot safely change a resource without its ETag: {name}")
        return current

    def _save(self, definition, get, save):
        current = self._current(definition.name, get)
        if not (definition.description or "").startswith(self.owner):
            definition.description = self.owner + (definition.description or "")
        definition.e_tag = current.e_tag if current is not None else None
        condition = MatchConditions.IfNotModified if current is not None else MatchConditions.IfMissing
        return save(definition, match_condition=condition)

    def _delete(self, name, get, delete):
        current = self._current(name, get)
        if current is not None:
            delete(current, match_condition=MatchConditions.IfNotModified)

    def save_source(self, source: KnowledgeSource) -> KnowledgeSource:
        return self._save(
            source, self.client.get_knowledge_source, self.client.create_or_update_knowledge_source
        )

    def save_base(self, base: KnowledgeBase) -> KnowledgeBase:
        return self._save(base, self.client.get_knowledge_base, self.client.create_or_update_knowledge_base)

    def delete_source(self, name: str) -> None:
        self._delete(name, self.client.get_knowledge_source, self.client.delete_knowledge_source)

    def delete_base(self, name: str) -> None:
        self._delete(name, self.client.get_knowledge_base, self.client.delete_knowledge_base)
