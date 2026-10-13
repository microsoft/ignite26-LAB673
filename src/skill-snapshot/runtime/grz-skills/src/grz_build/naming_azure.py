"""Opt-in community naming with an Azure OpenAI chat deployment, bounded by the plan's naming budget."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote, urlparse

import numpy as np

from grz_core.azure_auth import get_token
from grz_core.contracts import ContractError

from .centroids import Centroid
from .inputs import Snapshot
from .naming import NamingResult

PROMPT_VERSION = "grz-naming-v1"
COGNITIVE_SCOPE = "https://cognitiveservices.azure.com/.default"
API_VERSION = "2025-04-01-preview"
MAX_LABEL_CHARS = 60
MAX_THROTTLE_RETRIES = 2
MAX_RETRY_AFTER_SECONDS = 30
SYSTEM_PROMPT = (
    "You name clusters of documents. You get sample documents from one cluster, the ones closest "
    "to its center. Reply with one short topic label of at most six words that covers the cluster "
    "as a whole. Reply with the label only: no quotes, no trailing punctuation, no explanation."
)


def source_title(source: str) -> str:
    path = urlparse(source).path or source
    return unquote(path.rstrip("/").rsplit("/", 1)[-1]).replace("_", " ") or source


def naming_contexts(snapshot: Snapshot, hierarchy: list[dict[str, Centroid]], *,
                    members_per_prompt: int, excerpt_chars: int) -> dict[str, str]:
    """Context per community key, top level first, from the members nearest its centroid."""
    positions = {key: i for i, key in enumerate(snapshot.ids)}
    contexts: dict[str, str] = {}
    for level in reversed(range(len(hierarchy))):
        for local in sorted(hierarchy[level]):
            centroid = hierarchy[level][local]
            members = list(centroid.members)
            scores = snapshot.vectors[[positions[m] for m in members]] @ centroid.vector.astype(np.float32)
            ranked = [members[i] for i in np.lexsort((np.array(members), -scores))]
            lines, seen = [], set()
            for member in ranked:
                row = snapshot.rows[positions[member]]
                title = source_title(row["source"])
                if title in seen:
                    continue
                seen.add(title)
                excerpt = " ".join(row["text"].split())[:excerpt_chars]
                lines.append(f"- {title}: {excerpt}")
                if len(lines) == members_per_prompt:
                    break
            contexts[f"{level}:{local}"] = f"Cluster of {len(members)} documents. Samples:\n" + "\n".join(lines)
    return contexts


def clean_label(text: str | None) -> str | None:
    if not text:
        return None
    line = text.strip().splitlines()[0].strip().strip("\"'`*").rstrip(".").strip()
    if not line or len(line) > MAX_LABEL_CHARS or not any(c.isalpha() for c in line):
        return None
    return line


@dataclass
class AzureOpenAIChatNamer:
    """Calls one chat deployment per community and keeps usage totals for the apply report."""

    endpoint: str
    deployment: str
    tenant_id: str
    credential: Any
    max_output_tokens: int
    input_price_per_1m: float
    output_price_per_1m: float
    post: Any = None
    sleep: Any = time.sleep
    usage: dict[str, float] = field(default_factory=lambda: {"calls": 0, "throttled": 0, "failed": 0,
                                                             "input_tokens": 0, "output_tokens": 0, "spend_usd": 0.0})

    @classmethod
    def from_plan(cls, spec: dict[str, Any], tenant_id: str, credential: Any, **kwargs: Any) -> AzureOpenAIChatNamer:
        return cls(endpoint=spec["endpoint"], deployment=spec["deployment"], tenant_id=tenant_id,
                   credential=credential, max_output_tokens=spec["max_output_tokens"],
                   input_price_per_1m=spec["input_price_per_1m"], output_price_per_1m=spec["output_price_per_1m"],
                   **kwargs)

    def _post(self, url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> Any:
        if self.post is not None:
            return self.post(url, body, headers, timeout)
        import requests

        try:
            return requests.post(url, json=body, headers=headers, timeout=timeout)
        except requests.Timeout as exc:
            raise TimeoutError("naming call timed out") from exc
        except requests.RequestException as exc:
            raise ConnectionError("naming call failed") from exc

    def __call__(self, context: str, timeout_seconds: float) -> NamingResult:
        url = (f"{self.endpoint.rstrip('/')}/openai/deployments/{self.deployment}/chat/completions"
               f"?api-version={API_VERSION}")
        body = {"messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": context}],
                "max_completion_tokens": self.max_output_tokens, "reasoning_effort": "minimal"}
        for attempt in range(MAX_THROTTLE_RETRIES + 1):
            headers = {"Authorization": "Bearer " + get_token(self.credential, COGNITIVE_SCOPE, self.tenant_id)}
            response = self._post(url, body, headers, timeout_seconds)
            if response.status_code != 429:
                break
            # A 429 is refused before any tokens are billed, so waiting and asking again stays in budget.
            self.usage["throttled"] += 1
            if attempt == MAX_THROTTLE_RETRIES:
                self.usage["failed"] += 1
                raise ConnectionError("naming deployment kept throttling")
            self.sleep(min(float(response.headers.get("retry-after") or 5), MAX_RETRY_AFTER_SECONDS))
        self.usage["calls"] += 1
        if response.status_code in (401, 403):
            raise ContractError("NAMING_ACCESS_DENIED", "The naming deployment refused this identity")
        if response.status_code != 200:
            self.usage["failed"] += 1
            raise ConnectionError(f"naming call returned HTTP {response.status_code}")
        data = response.json()
        usage = data.get("usage") or {}
        prompt_tokens, completion_tokens = int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
        spend = (prompt_tokens * self.input_price_per_1m + completion_tokens * self.output_price_per_1m) / 1_000_000
        self.usage["input_tokens"] += prompt_tokens
        self.usage["output_tokens"] += completion_tokens
        self.usage["spend_usd"] = round(self.usage["spend_usd"] + spend, 6)
        choices = data.get("choices") or [{}]
        label = clean_label((choices[0].get("message") or {}).get("content"))
        if label is None:
            self.usage["failed"] += 1
        return NamingResult(label, prompt_tokens + completion_tokens, spend)
