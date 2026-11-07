"""Write deployment outputs and API keys to the repository's local .env file."""

import argparse
import os
from pathlib import Path

import requests
from azure.identity import AzureCliCredential, AzureDeveloperCliCredential
from dotenv import set_key


OUTPUT_NAMES = (
    "AZURE_SEARCH_SERVICE_ENDPOINT",
    "AZURE_SEARCH_SERVICE_NAME",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_SERVICE_NAME",
    "AZURE_OPENAI_CHATGPT_DEPLOYMENT",
    "AZURE_OPENAI_CHATGPT_MODEL_NAME",
    "AZURE_DECISION_DEPLOYMENT",
    "AZURE_OPENAI_EMBEDDING_DEPLOYMENT",
    "AZURE_TENANT_ID",
    "MICROSOFT_FOUNDRY_PROJECT_ENDPOINT",
    "MICROSOFT_FOUNDRY_PROJECT_ID",
    "INDEXING_STORAGE_ACCOUNT_ID",
    "INDEXING_STORAGE_ACCOUNT_NAME",
    "CONTENTUNDERSTANDING_ENDPOINT",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credential", choices=("azd", "cli"), default="azd")
    args = parser.parse_args()
    credential = AzureCliCredential() if args.credential == "cli" else AzureDeveloperCliCredential()
    try:
        token = credential.get_token("https://management.azure.com/.default").token
        subscription = os.environ["AZURE_SUBSCRIPTION_ID"]
        resource_group = os.environ["AZURE_RESOURCE_GROUP"]
        base_url = (
            f"https://management.azure.com/subscriptions/{subscription}"
            f"/resourceGroups/{resource_group}/providers"
        )
        headers = {"Authorization": f"Bearer {token}"}
        search_response = requests.post(
            f"{base_url}/Microsoft.Search/searchServices/"
            f"{os.environ['AZURE_SEARCH_SERVICE_NAME']}/listAdminKeys?api-version=2026-09-01-preview",
            headers=headers,
            timeout=120,
        )
        search_response.raise_for_status()
        foundry_response = requests.post(
            f"{base_url}/Microsoft.CognitiveServices/accounts/"
            f"{os.environ['AZURE_OPENAI_SERVICE_NAME']}/listKeys?api-version=2025-04-01-preview",
            headers=headers,
            timeout=120,
        )
        foundry_response.raise_for_status()
        values = {name: os.environ[name] for name in OUTPUT_NAMES}
        values.update(
            AZURE_SEARCH_ADMIN_KEY=search_response.json()["primaryKey"],
            AZURE_OPENAI_KEY=foundry_response.json()["key1"],
            CONTENTUNDERSTANDING_KEY=foundry_response.json()["key1"],
            CONTENTUNDERSTANDING_API_VERSION="2025-11-01",
            RESTORE_INDEX_SNAPSHOTS=os.environ.get("RESTORE_INDEX_SNAPSHOTS", "true"),
        )
        env_path = Path(__file__).resolve().parents[1] / ".env"
        for name, value in values.items():
            set_key(env_path, name, value)
        print("Created local .env with deployment outputs and API keys.")
    finally:
        credential.close()


if __name__ == "__main__":
    main()