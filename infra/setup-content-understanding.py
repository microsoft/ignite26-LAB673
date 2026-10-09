"""Connect Content Understanding to the lab's Foundry model deployments."""

import os
import time

import requests
from dotenv import load_dotenv
from pathlib import Path


def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)
    endpoint = os.environ["CONTENTUNDERSTANDING_ENDPOINT"].rstrip("/")
    api_version = os.environ.get("CONTENTUNDERSTANDING_API_VERSION", "2025-11-01")
    completion_model = os.environ["AZURE_OPENAI_CHATGPT_MODEL_NAME"]
    completion_deployment = os.environ["AZURE_OPENAI_CHATGPT_DEPLOYMENT"]
    embedding_deployment = os.environ["AZURE_OPENAI_EMBEDDING_DEPLOYMENT"]
    payload = {
        "modelDeployments": {
            completion_model: completion_deployment,
            "text-embedding-3-large": embedding_deployment,
            "prebuilt-analyzer-completion": completion_deployment,
            "prebuilt-analyzer-completion-mini": completion_deployment,
            "prebuilt-analyzer-embedding": embedding_deployment,
        }
    }
    for attempt in range(6):
        response = requests.patch(
            f"{endpoint}/contentunderstanding/defaults?api-version={api_version}",
            headers={"Ocp-Apim-Subscription-Key": os.environ["CONTENTUNDERSTANDING_KEY"]},
            json=payload,
            timeout=120,
        )
        if response.status_code not in (429, 500, 502, 503, 504) or attempt == 5:
            response.raise_for_status()
            break
        time.sleep(min(10 * (attempt + 1), 60))
    print("Configured Content Understanding completion and embedding defaults.")


if __name__ == "__main__":
    main()