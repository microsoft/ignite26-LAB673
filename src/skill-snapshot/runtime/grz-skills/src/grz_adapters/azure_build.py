"""Connect separately authorized Search source and publisher adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from grz_adapters.azure_publication import AzurePublicationAdapter
from grz_adapters.azure_source import AzureSourceAdapter
from grz_core.contracts import ContractError, SourceIdentity


class AzureBuildStore:
    def __init__(self, source: AzureSourceAdapter, publisher: AzurePublicationAdapter):
        if source.approval.resource != publisher.approval.resource or source.approval.tenant != publisher.approval.tenant:
            raise ContractError("PLACEMENT_UNSUPPORTED", "Cross-service/tenant publication is not validated")
        self.source = source
        self.publisher = publisher

    def inspect(self, identity: SourceIdentity) -> dict[str, Any]:
        return self.source.inspect(identity)

    def export_snapshot(self, identity: SourceIdentity, destination: Path) -> Path:
        return self.source.export_snapshot(identity, destination)

    def generation_index_name(self, generation_id: str) -> str:
        dataset = self.publisher.approval.dataset
        if not dataset or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in dataset):
            raise ContractError("PUBLICATION_TARGET_INVALID", "Approved dataset must be a Search-safe lowercase slug")
        name = f"grz-{dataset}-{generation_id[:32]}"
        if len(name) > 128:
            raise ContractError("PUBLICATION_TARGET_INVALID", "Generated index name exceeds Search limit")
        return name

    def create_generation_index(self, index: str, dimension: int) -> None:
        self.publisher.create_generation_index(index, dimension)

    def upload_batch(self, index: str, documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self.publisher.upload_batch(index, documents)

    def readback(self, index: str) -> list[dict[str, Any]]:
        return self.publisher.readback(index)

    def verify(self, index: str, expected: list[dict[str, Any]]) -> None:
        self.publisher.verify(index, expected)

    def resolve_alias(self, alias: str) -> str | None:
        return self.publisher.resolve_alias(alias)

    def switch_alias(self, alias: str, expected: str | None, target: str) -> None:
        self.publisher.switch_alias(alias, expected, target)
