"""Build the Cocoarynth Search indexing pipelines for snapshot capture or lab setup."""

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from azure.core.credentials import AzureKeyCredential
from azure.core.rest import HttpRequest
from azure.identity.aio import DefaultAzureCredential
from azure.search.documents.aio import SearchClient
from azure.search.documents.indexes.aio import SearchIndexClient, SearchIndexerClient
from azure.search.documents.indexes.models import SearchIndex
from azure.storage.blob.aio import BlobServiceClient
from dotenv import load_dotenv


load_dotenv(override=True)

REPO_ROOT = Path(__file__).parents[1]
DATA_ROOT = REPO_ROOT / "data" / "cocoarynth"
CORPORA_PATH = DATA_ROOT / "corpora.json"
CONTAINER_NAME = "knowledge"
SEARCH_API_VERSION = "2026-05-01-preview"
EMBEDDING_DIMENSIONS = 3072
SEMANTIC_CONFIGURATION_NAME = "semantic-configuration"
VECTOR_PROFILE_NAME = "vector-search-profile"
INDEXER_POLL_SECONDS = 10
INDEXER_TIMEOUT_SECONDS = 30 * 60
CORPUS_COUNTS = {
    "cocoarynth-logistics-retail": 16,
    "cocoarynth-origins": 16,
    "cocoarynth-policies": 8,
    "cocoarynth-quality": 15,
}
FILE_SOURCE_PDF = "documents/cocoarynth-policies/label-claims-policy.pdf"


def load_corpora() -> dict[str, list[Path]]:
    try:
        manifest = json.loads(CORPORA_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as error:
        raise RuntimeError(
            "The Cocoarynth corpus manifest is missing or invalid."
        ) from error

    selected: dict[str, list[Path]] = {}
    indexed_paths: set[str] = set()
    for corpus_name, expected_count in CORPUS_COUNTS.items():
        relative_paths = manifest.get(corpus_name)
        if not isinstance(relative_paths, list) or not all(
            isinstance(path, str) for path in relative_paths
        ):
            raise RuntimeError(f"Corpus '{corpus_name}' must be a list of paths.")
        if len(relative_paths) != expected_count or len(relative_paths) != len(set(relative_paths)):
            raise RuntimeError(
                f"Corpus '{corpus_name}' must contain {expected_count} unique PDFs."
            )
        if indexed_paths.intersection(relative_paths):
            raise RuntimeError(f"Corpus '{corpus_name}' overlaps another indexed corpus.")
        paths = [(DATA_ROOT / relative_path).resolve() for relative_path in relative_paths]
        if any(
            not pdf_path.is_relative_to(DATA_ROOT.resolve()) or pdf_path.suffix != ".pdf"
            for pdf_path in paths
        ):
            raise RuntimeError(f"Corpus '{corpus_name}' must contain local PDF paths.")
        missing = [str(path) for path in paths if not path.is_file()]
        if missing:
            raise RuntimeError(f"Corpus '{corpus_name}' has missing files: {missing}")
        selected[corpus_name] = paths
        indexed_paths.update(relative_paths)

    file_sources = manifest.get("file-source")
    if file_sources != [FILE_SOURCE_PDF]:
        raise RuntimeError("The file-source exercise must use the label-claims policy PDF.")
    if not (DATA_ROOT / file_sources[0]).is_file():
        raise RuntimeError("The file-source policy PDF is missing.")
    return selected


def build_index(index_name: str, openai_endpoint: str, embedding_deployment: str) -> SearchIndex:
    return SearchIndex(
        {
            "name": index_name,
            "fields": [
                {
                    "name": "chunk_id",
                    "type": "Edm.String",
                    "key": True,
                    "searchable": True,
                    "retrievable": True,
                    "stored": True,
                    "sortable": True,
                    "analyzer": "keyword",
                },
                {
                    "name": "parent_id",
                    "type": "Edm.String",
                    "filterable": True,
                    "retrievable": True,
                    "stored": True,
                },
                {
                    "name": "title",
                    "type": "Edm.String",
                    "searchable": True,
                    "retrievable": True,
                    "stored": True,
                },
                {
                    "name": "blob_path",
                    "type": "Edm.String",
                    "filterable": True,
                    "retrievable": True,
                    "stored": True,
                },
                {
                    "name": "chunk",
                    "type": "Edm.String",
                    "searchable": True,
                    "retrievable": True,
                    "stored": True,
                },
                {
                    "name": "page_number_from",
                    "type": "Edm.Int32",
                    "filterable": True,
                    "retrievable": True,
                    "stored": True,
                    "sortable": True,
                },
                {
                    "name": "page_number_to",
                    "type": "Edm.Int32",
                    "filterable": True,
                    "retrievable": True,
                    "stored": True,
                    "sortable": True,
                },
                {
                    "name": "text_vector",
                    "type": "Collection(Edm.Single)",
                    "searchable": True,
                    "retrievable": True,
                    "stored": True,
                    "dimensions": EMBEDDING_DIMENSIONS,
                    "vectorSearchProfile": VECTOR_PROFILE_NAME,
                },
            ],
            "semantic": {
                "defaultConfiguration": SEMANTIC_CONFIGURATION_NAME,
                "configurations": [
                    {
                        "name": SEMANTIC_CONFIGURATION_NAME,
                        "prioritizedFields": {
                            "titleField": {"fieldName": "title"},
                            "prioritizedContentFields": [{"fieldName": "chunk"}],
                        },
                    }
                ],
            },
            "vectorSearch": {
                "profiles": [
                    {
                        "name": VECTOR_PROFILE_NAME,
                        "algorithm": "vector-search-algorithm",
                        "vectorizer": "azure-openai-vectorizer",
                    }
                ],
                "algorithms": [
                    {
                        "name": "vector-search-algorithm",
                        "kind": "hnsw",
                        "hnswParameters": {"metric": "cosine"},
                    }
                ],
                "vectorizers": [
                    {
                        "name": "azure-openai-vectorizer",
                        "kind": "azureOpenAI",
                        "azureOpenAIParameters": {
                            "resourceUri": openai_endpoint,
                            "deploymentId": embedding_deployment,
                            "modelName": "text-embedding-3-large",
                        },
                    }
                ],
            },
        }
    )


def build_pipeline(
    index_name: str,
    storage_resource_id: str,
    foundry_endpoint: str,
    openai_endpoint: str,
    chat_deployment: str,
    embedding_deployment: str,
) -> dict[str, tuple[str, dict[str, Any]]]:
    data_source_name = f"{index_name}-blob-source"
    skillset_name = f"{index_name}-content-understanding"
    indexer_name = f"{index_name}-blob-indexer"
    return {
        "datasources": (
            data_source_name,
            {
                "name": data_source_name,
                "type": "azureblob",
                "credentials": {"connectionString": f"ResourceId={storage_resource_id};"},
                "container": {"name": CONTAINER_NAME, "query": index_name},
            },
        ),
        "skillsets": (
            skillset_name,
            {
                "name": skillset_name,
                "description": f"Semantic PDF chunking and vectorization for {index_name}.",
                "skills": [
                    {
                        "@odata.type": "#Microsoft.Skills.Util.ContentUnderstandingSkill",
                        "name": "content-understanding",
                        "context": "/document",
                        "modelName": os.environ.get("AZURE_OPENAI_CHATGPT_MODEL_NAME", "gpt-5.4"),
                        "modelDeployment": chat_deployment,
                        "chunkingProperties": {
                            "method": "semantic",
                            "unit": "tokens",
                            "maximumLength": 700,
                        },
                        "extractionOptions": ["locationMetadata"],
                        "inputs": [{"name": "file_data", "source": "/document/file_data"}],
                        "outputs": [{"name": "text_sections", "targetName": "text_sections"}],
                    },
                    {
                        "@odata.type": "#Microsoft.Skills.Text.AzureOpenAIEmbeddingSkill",
                        "name": "azure-openai-embedding",
                        "context": "/document/text_sections/*",
                        "resourceUri": openai_endpoint,
                        "deploymentId": embedding_deployment,
                        "modelName": "text-embedding-3-large",
                        "dimensions": EMBEDDING_DIMENSIONS,
                        "inputs": [
                            {"name": "text", "source": "/document/text_sections/*/content"}
                        ],
                        "outputs": [{"name": "embedding", "targetName": "text_vector"}],
                    },
                ],
                "cognitiveServices": {
                    "@odata.type": "#Microsoft.Azure.Search.AIServicesByIdentity",
                    "subdomainUrl": foundry_endpoint,
                    "identity": None,
                },
                "indexProjections": {
                    "selectors": [
                        {
                            "targetIndexName": index_name,
                            "parentKeyFieldName": "parent_id",
                            "sourceContext": "/document/text_sections/*",
                            "mappings": [
                                {"name": "chunk", "source": "/document/text_sections/*/content"},
                                {
                                    "name": "text_vector",
                                    "source": "/document/text_sections/*/text_vector",
                                },
                                {
                                    "name": "page_number_from",
                                    "source": "/document/text_sections/*/locationMetadata/pageNumberFrom",
                                },
                                {
                                    "name": "page_number_to",
                                    "source": "/document/text_sections/*/locationMetadata/pageNumberTo",
                                },
                                {"name": "title", "source": "/document/metadata_storage_name"},
                                {"name": "blob_path", "source": "/document/metadata_storage_path"},
                            ],
                        }
                    ],
                    "parameters": {"projectionMode": "skipIndexingParentDocuments"},
                },
            },
        ),
        "indexers": (
            indexer_name,
            {
                "name": indexer_name,
                "dataSourceName": data_source_name,
                "targetIndexName": index_name,
                "skillsetName": skillset_name,
                "parameters": {
                    "batchSize": 1,
                    "configuration": {
                        "dataToExtract": "contentAndMetadata",
                        "parsingMode": "default",
                        "allowSkillsetToReadFileData": True,
                        "indexedFileNameExtensions": ".pdf",
                    },
                },
                "fieldMappings": [],
                "outputFieldMappings": [],
            },
        ),
    }


async def upload_pdfs(
    storage_name: str, credential: Any, corpus_name: str, pdfs: list[Path]
) -> int:
    account_url = f"https://{storage_name}.blob.core.windows.net"
    async with BlobServiceClient(account_url=account_url, credential=credential) as service:
        container = service.get_container_client(CONTAINER_NAME)
        stale_blobs = [
            blob.name async for blob in container.list_blobs(name_starts_with=f"{corpus_name}/")
        ]
        for blob_name in stale_blobs:
            await container.delete_blob(blob_name)
        for pdf_path in pdfs:
            print(f"{corpus_name}: uploading {pdf_path.name}", flush=True)
            blob = container.get_blob_client(f"{corpus_name}/{pdf_path.name}")
            with pdf_path.open("rb") as pdf_file:
                await blob.upload_blob(pdf_file, overwrite=True)
    return len(pdfs)


async def clear_index(endpoint: str, index_name: str, credential: Any) -> int:
    async with SearchClient(
        endpoint=endpoint, index_name=index_name, credential=credential
    ) as client:
        results = await client.search("*", select=["chunk_id"])
        documents = [{"chunk_id": result["chunk_id"]} async for result in results]
        for offset in range(0, len(documents), 1000):
            delete_results = await client.delete_documents(documents[offset : offset + 1000])
            failures = [result for result in delete_results if not result.succeeded]
            if failures:
                raise RuntimeError(f"Failed to clear stale chunks from '{index_name}'.")
    return len(documents)


async def put_resource(
    client: SearchIndexerClient,
    endpoint: str,
    collection: str,
    name: str,
    payload: dict[str, Any],
) -> None:
    url = (
        f"{endpoint.rstrip('/')}/{collection}/{quote(name, safe='')}"
        f"?api-version={SEARCH_API_VERSION}"
    )
    response = await client.send_request(
        HttpRequest("PUT", url, headers={"Content-Type": "application/json"}, json=payload)
    )
    response.raise_for_status()


async def wait_for_indexer(
    client: SearchIndexerClient, indexer_name: str, started_after: datetime
) -> tuple[int, int]:
    try:
        async with asyncio.timeout(INDEXER_TIMEOUT_SECONDS):
            while True:
                indexer_status = await client.get_indexer_status(indexer_name)
                result = indexer_status.last_result
                if result is None or result.start_time is None or result.start_time < started_after:
                    print(f"{indexer_name}: waiting for the new run to start", flush=True)
                    await asyncio.sleep(INDEXER_POLL_SECONDS)
                    continue
                status = getattr(result.status, "value", result.status)
                print(
                    f"{indexer_name}: status={status}, processed={result.item_count}, "
                    f"failed={result.failed_item_count}",
                    flush=True,
                )
                if status == "success":
                    if result.failed_item_count:
                        raise RuntimeError(
                            f"Indexer '{indexer_name}' reported {result.failed_item_count} failures."
                        )
                    if not result.item_count:
                        raise RuntimeError(f"Indexer '{indexer_name}' completed without indexing items.")
                    return result.item_count, result.failed_item_count
                if status not in {"inProgress", "reset"}:
                    raise RuntimeError(
                        f"Indexer '{indexer_name}' ended with '{status}': "
                        f"{result.error_message or 'no error message'}"
                    )
                await asyncio.sleep(INDEXER_POLL_SECONDS)
    except TimeoutError as error:
        raise TimeoutError(
            f"Indexer '{indexer_name}' did not finish within "
            f"{INDEXER_TIMEOUT_SECONDS // 60} minutes. The server-side run may still be active; "
            "check its execution status before rebuilding the corpus."
        ) from error


async def wait_until_idle(client: SearchIndexerClient, indexer_name: str) -> None:
    try:
        async with asyncio.timeout(INDEXER_TIMEOUT_SECONDS):
            while True:
                indexer_status = await client.get_indexer_status(indexer_name)
                result = indexer_status.last_result
                if result is None:
                    return
                status = getattr(result.status, "value", result.status)
                if status != "inProgress":
                    return
                print(
                    f"{indexer_name}: waiting for an existing run, "
                    f"processed={result.item_count}, failed={result.failed_item_count}",
                    flush=True,
                )
                await asyncio.sleep(INDEXER_POLL_SECONDS)
    except TimeoutError as error:
        raise TimeoutError(
            f"Indexer '{indexer_name}' is still running after "
            f"{INDEXER_TIMEOUT_SECONDS // 60} minutes. The server-side run was not cancelled; "
            "check its execution status before rebuilding the corpus."
        ) from error


async def main() -> None:
    endpoint = os.environ["AZURE_SEARCH_SERVICE_ENDPOINT"]
    storage_id = os.environ.get("INDEXING_STORAGE_ACCOUNT_ID", "")
    storage_name = os.environ.get("INDEXING_STORAGE_ACCOUNT_NAME", "")
    if not storage_id or not storage_name:
        raise RuntimeError(
            "Indexing storage outputs are missing. Provision the lab environment first."
        )
    openai_endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
    chat_deployment = os.environ.get("AZURE_OPENAI_CHATGPT_DEPLOYMENT", "gpt-5.4")
    embedding_deployment = os.environ.get(
        "AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-large"
    )
    openai_hostname = urlparse(openai_endpoint).hostname
    if not openai_hostname:
        raise RuntimeError("AZURE_OPENAI_ENDPOINT is not a valid URL.")
    foundry_account_name = openai_hostname.split(".")[0]
    foundry_endpoint = f"https://{foundry_account_name}.services.ai.azure.com"
    corpora = load_corpora()
    identity_credential = DefaultAzureCredential()
    search_key = os.environ.get("AZURE_SEARCH_ADMIN_KEY")
    search_credential: Any = (
        AzureKeyCredential(search_key) if search_key else identity_credential
    )

    try:
        for index_name, pdfs in corpora.items():
            print(f"{index_name}: preparing {len(pdfs)} PDFs", flush=True)
            uploaded = await upload_pdfs(storage_name, identity_credential, index_name, pdfs)
            index = build_index(index_name, openai_endpoint, embedding_deployment)
            print(f"{index_name}: creating or updating the index", flush=True)
            async with SearchIndexClient(endpoint, search_credential) as index_client:
                await index_client.create_or_update_index(index)
            print(f"{index_name}: clearing previous document chunks", flush=True)
            removed = await clear_index(endpoint, index_name, search_credential)
            pipeline = build_pipeline(
                index_name,
                storage_id,
                foundry_endpoint,
                openai_endpoint,
                chat_deployment,
                embedding_deployment,
            )
            async with SearchIndexerClient(endpoint, search_credential) as indexer_client:
                for collection, (name, payload) in pipeline.items():
                    print(f"{index_name}: configuring {collection}/{name}", flush=True)
                    await put_resource(indexer_client, endpoint, collection, name, payload)
                indexer_name = pipeline["indexers"][0]
                print(f"{indexer_name}: checking for an existing run", flush=True)
                await wait_until_idle(indexer_client, indexer_name)
                print(f"{indexer_name}: resetting the indexer", flush=True)
                await indexer_client.reset_indexer(indexer_name)
                await wait_until_idle(indexer_client, indexer_name)
                started_after = datetime.now(UTC) - timedelta(seconds=5)
                print(f"{indexer_name}: starting a new run", flush=True)
                await indexer_client.run_indexer(indexer_name)
                indexed, failed = await wait_for_indexer(
                    indexer_client, indexer_name, started_after
                )
            print(
                f"{index_name}: uploaded {uploaded} PDFs, removed {removed} stale chunks, "
                f"indexed {indexed} items with {failed} failures.",
                flush=True,
            )
    finally:
        await identity_credential.close()


if __name__ == "__main__":
    asyncio.run(main())