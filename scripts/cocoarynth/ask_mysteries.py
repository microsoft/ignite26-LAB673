"""Ask every mystery in questions.yaml against a knowledge base set up like notebook 1, and score the citations.

Run with the lab environment after ingestion: .venv/bin/python scripts/cocoarynth/ask_mysteries.py [--effort auto|low|medium] [M1 M2 ...]
Evidence recall is the share of a mystery's evidence items with at least one valid document among the references.
Results go to /tmp/cocoarynth-mysteries-<effort>.json for comparison with the expected answers.
"""

import json
import os
import sys
import time
from pathlib import Path

import yaml
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import HttpResponseError
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    AzureOpenAIVectorizerParameters,
    KnowledgeBase,
    KnowledgeBaseAzureOpenAIModel,
    KnowledgeSourceReference,
    SearchIndexFieldReference,
    SearchIndexKnowledgeSource,
    SearchIndexKnowledgeSourceParameters,
)
from azure.search.documents.knowledgebases import KnowledgeBaseRetrievalClient
from azure.search.documents.knowledgebases.models import (
    KnowledgeBaseMessage,
    KnowledgeBaseMessageTextContent,
    KnowledgeBaseRetrievalRequest,
    KnowledgeRetrievalAutoReasoningEffort,
    KnowledgeRetrievalLowReasoningEffort,
    KnowledgeRetrievalMediumReasoningEffort,
    KnowledgeRetrievalOutputMode,
    SearchIndexKnowledgeSourceParams,
)
from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[2]
load_dotenv(REPO / ".env", override=True)

# Keep in sync with notebook 1 so the test matches what attendees see.
INDEX_DESCRIPTIONS = {
    "cocoarynth-origins": "Cocoarynth origin and farm records, partly in Spanish: supplier profiles, collection tickets, fermentation and drying logs, farm inspections, organic certificates, and sourcing prices",
    "cocoarynth-quality": "Cocoarynth factory quality and production records: bean receiving tests, holds, lab certificates, tasting panels, batch records, and nonconformance reports",
    "cocoarynth-logistics-retail": "Cocoarynth shipping and sales records: bills of lading, carrier and depot logs, retailer emails and complaints, agreements, launch plans, price lists, and sales",
    "cocoarynth-policies": "Cocoarynth company-wide policies, guides, and reference material, including storage, labeling, and data-sharing rules",
}
KNOWLEDGE_BASE_NAME = "cocoarynth-all-knowledge-base"
EFFORTS = {"auto": KnowledgeRetrievalAutoReasoningEffort, "low": KnowledgeRetrievalLowReasoningEffort, "medium": KnowledgeRetrievalMediumReasoningEffort}


def setup(endpoint: str, credential: AzureKeyCredential, effort: str) -> list[str]:
    client = SearchIndexClient(endpoint=endpoint, credential=credential)
    names = []
    for index_name, description in INDEX_DESCRIPTIONS.items():
        source = SearchIndexKnowledgeSource(
            name=f"{index_name}-knowledge-source",
            description=description,
            search_index_parameters=SearchIndexKnowledgeSourceParameters(
                search_index_name=index_name,
                source_data_fields=[SearchIndexFieldReference(name=n) for n in ("blob_path", "title", "page_number_from", "page_number_to")],
                search_fields=[SearchIndexFieldReference(name="chunk")],
                semantic_configuration_name="semantic-configuration",
            ),
        )
        client.create_or_update_knowledge_source(knowledge_source=source)
        names.append(source.name)
    model = AzureOpenAIVectorizerParameters(
        resource_url=os.environ["AZURE_OPENAI_ENDPOINT"],
        deployment_name=os.environ["AZURE_OPENAI_CHATGPT_DEPLOYMENT"],
        model_name=os.environ["AZURE_OPENAI_CHATGPT_MODEL_NAME"],
        api_key=os.environ["AZURE_OPENAI_KEY"],
    )
    client.create_or_update_knowledge_base(
        KnowledgeBase(
            name=KNOWLEDGE_BASE_NAME,
            description="Cocoarynth knowledge base over origin, quality, logistics and retail, and policy records",
            models=[KnowledgeBaseAzureOpenAIModel(azure_open_ai_parameters=model)],
            knowledge_sources=[KnowledgeSourceReference(name=n) for n in names],
            retrieval_reasoning_effort=EFFORTS[effort](),
            output_mode=KnowledgeRetrievalOutputMode.ANSWER_SYNTHESIS,
        )
    )
    return names


def retrieve(retriever: KnowledgeBaseRetrievalClient, request: KnowledgeBaseRetrievalRequest):
    for attempt in range(5):
        try:
            return retriever.retrieve(retrieval_request=request)
        except HttpResponseError as error:
            if "429" not in str(error) or attempt == 4:
                raise
            print("Rate limited; retrying in 60 seconds", flush=True)
            time.sleep(60)


def main(args: list[str]) -> None:
    effort = "auto"
    if "--effort" in args:
        effort = args.pop(args.index("--effort") + 1)
        args.remove("--effort")
    selected = args
    endpoint = os.environ["AZURE_SEARCH_SERVICE_ENDPOINT"]
    credential = AzureKeyCredential(os.environ["AZURE_SEARCH_ADMIN_KEY"])
    source_names = setup(endpoint, credential, effort)
    retriever = KnowledgeBaseRetrievalClient(endpoint=endpoint, knowledge_base_name=KNOWLEDGE_BASE_NAME, credential=credential)
    mysteries = yaml.safe_load((REPO / "data" / "cocoarynth" / "questions.yaml").read_text(encoding="utf-8"))["mysteries"]
    results = []
    for mystery in mysteries:
        if selected and mystery["id"] not in selected:
            continue
        response = retrieve(
            retriever,
            KnowledgeBaseRetrievalRequest(
                messages=[KnowledgeBaseMessage(role="user", content=[KnowledgeBaseMessageTextContent(text=mystery["question"])])],
                knowledge_source_params=[
                    SearchIndexKnowledgeSourceParams(knowledge_source_name=n, include_references=True, include_reference_source_data=True)
                    for n in source_names
                ],
                include_activity=True,
            )
        )
        answer = response.response[0].content[0].text if response.response and response.response[0].content else ""
        documents = sorted({Path((ref.source_data or {}).get("blob_path", "")).name for ref in response.references or []})
        queries = [
            (activity.as_dict().get("knowledgeSourceName"), activity.as_dict().get("searchIndexArguments", {}).get("search"))
            for activity in response.activity or []
            if activity.as_dict().get("type") == "searchIndex"
        ]
        results.append({"id": mystery["id"], "question": mystery["question"], "expected": mystery["answer"],
                        "answer": answer, "documents": documents, "queries": queries})
        cited = [any(d in documents for d in e["documents"]) for e in mystery["evidence"]]
        missed = [e["fact"] for e, hit in zip(mystery["evidence"], cited) if not hit]
        results[-1] |= {"evidence_recall": sum(cited) / len(cited), "missed_evidence": missed}
        print(f"\n=== {mystery['id']}: {mystery['title']}\n{answer}\nDocuments: {', '.join(documents)}", flush=True)
        print(f"Evidence cited: {sum(cited)}/{len(cited)}" + "".join(f"\n  missed: {fact}" for fact in missed), flush=True)
    Path(f"/tmp/cocoarynth-mysteries-{effort}.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:])
