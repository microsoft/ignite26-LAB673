"""Azure OpenAI chat-completions client.

Sends via `ontology_core.http.request` only. No temperature. Token from `azure_auth.token(tenant, "aoai")`.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlparse

from ontology_core import azure_auth, http
from ontology_core.errors import Blocked
from ontology_core.http import EgressPolicy

API_VERSION = "2025-04-01-preview"
MODELS_API_VERSION = "2024-10-21"
MAX_429_RETRIES = 2
UNBILLED_STATUSES = frozenset({400, 401, 403, 404, 429})
ReasoningEffort = Literal["minimal", "low", "medium", "high"]
OPTIONAL_FIELDS = ("reasoning_effort", "response_format")
DEFAULT_RETRY_AFTER_S = 5.0

sleep: Callable[[float], None] = time.sleep
"""Backoff sleep; tests replace it."""


@dataclass(frozen=True)
class Attempt:
    """One HTTP attempt, reported through `on_attempt` so the caller can journal `call_failed`."""

    http_status: int
    billed: bool
    removed_field: str | None = None


@dataclass(frozen=True)
class ChatResult:
    content: str
    finish_reason: str
    prompt_tokens: int | None
    """None when the response had no usage (the caller then charges the full reservation)."""
    completion_tokens: int | None
    raw: dict[str, Any]
    """Full response JSON, saved by the caller before parsing."""
    request_body: dict[str, Any]
    """The body actually sent (after any 400 fallback)."""


class ModelClient:
    def __init__(self, *, endpoint: str, deployment: str, tenant_id: str, policy: EgressPolicy) -> None:
        self.endpoint = endpoint
        self.deployment = deployment
        self.tenant_id = tenant_id
        self.policy = policy

    def request_body(self, messages: list[dict[str, str]], *, max_completion_tokens: int,
                     reasoning_effort: ReasoningEffort) -> dict[str, Any]:
        """The request body with `response_format: {"type": "json_object"}`."""
        return {"messages": messages, "max_completion_tokens": max_completion_tokens,
                "reasoning_effort": reasoning_effort, "response_format": {"type": "json_object"}}

    @property
    def chat_url(self) -> str:
        return (f"{self.endpoint.rstrip('/')}/openai/deployments/{self.deployment}/chat/completions"
                f"?api-version={API_VERSION}")

    @property
    def account(self) -> str:
        return self.policy.account_name or (urlparse(self.endpoint).hostname or self.endpoint).split(".")[0]

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {azure_auth.token(self.tenant_id, 'aoai')}",
                "Content-Type": "application/json"}

    def complete(self, messages: list[dict[str, str]], *, max_completion_tokens: int,
                 reasoning_effort: ReasoningEffort,
                 on_attempt: Callable[[Attempt], None] | None = None) -> ChatResult:
        """POST chat/completions. 400 mentioning `reasoning_effort`/`response_format` drops that field and
        retries once; 429 retries `MAX_429_RETRIES` times (retry-after <= 30 s).

        Raises:
            Blocked("MODEL_ACCESS_DENIED", account=...): 401/403.
            Blocked("MODEL_DEPLOYMENT_NOT_FOUND"): 404.
            Blocked("MODEL_THROTTLED"): 429 after retries.
            Blocked("MODEL_OUTPUT_INVALID"): other 4xx/5xx.
            ontology_core.http.EgressUnknownOutcome: timeout/drop after send (caller journals `call_unknown`).
        """
        body = self.request_body(messages, max_completion_tokens=max_completion_tokens,
                                 reasoning_effort=reasoning_effort)
        report = on_attempt or (lambda _attempt: None)
        dropped_field = False
        throttled = 0
        while True:
            # EgressUnknownOutcome propagates: an unknown outcome is never retried here
            resp = http.request(self.policy, "POST", self.chat_url, headers=self._headers(), json_body=body)
            status = resp.status
            if status == 200:
                return _chat_result(resp, body)
            text = resp.body.decode("utf-8", errors="replace")
            if status == 400 and not dropped_field:
                field = next((f for f in OPTIONAL_FIELDS if f in text and f in body), None)
                if field is not None:
                    report(Attempt(status, billed=False, removed_field=field))
                    body = {k: v for k, v in body.items() if k != field}
                    dropped_field = True
                    continue
            report(Attempt(status, billed=status not in UNBILLED_STATUSES))
            if status in (401, 403):
                raise Blocked("MODEL_ACCESS_DENIED", f"model endpoint returned HTTP {status}", account=self.account,
                              details={"http_status": status})
            if status == 404:
                raise Blocked("MODEL_DEPLOYMENT_NOT_FOUND",
                              f"deployment {self.deployment!r} was not found on {self.endpoint}")
            if status == 429:
                if throttled < MAX_429_RETRIES:
                    throttled += 1
                    sleep(http.retry_after_seconds(resp.headers, DEFAULT_RETRY_AFTER_S))
                    continue
                raise Blocked("MODEL_THROTTLED", f"model endpoint still throttling after {MAX_429_RETRIES} retries")
            raise Blocked("MODEL_OUTPUT_INVALID", f"model endpoint returned HTTP {status}",
                          details={"http_status": status, "body": text[:500]})

    def list_models(self) -> int:
        """`GET {endpoint}/openai/models?api-version=MODELS_API_VERSION`; returns the HTTP status (doctor)."""
        url = f"{self.endpoint.rstrip('/')}/openai/models?api-version={MODELS_API_VERSION}"
        return http.request(self.policy, "GET", url, headers=self._headers()).status


def _chat_result(resp: http.Response, body: dict[str, Any]) -> ChatResult:
    try:
        raw = json.loads(resp.body.decode("utf-8"))
        choice = raw["choices"][0]
        content = choice["message"].get("content") or ""
        finish_reason = choice.get("finish_reason") or ""
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
        raise Blocked("MODEL_OUTPUT_INVALID", f"chat completion response is not the expected shape: {exc}") from exc
    usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
    prompt, completion = usage.get("prompt_tokens"), usage.get("completion_tokens")
    if not isinstance(prompt, int) or not isinstance(completion, int):
        prompt = completion = None
    return ChatResult(content=content, finish_reason=finish_reason, prompt_tokens=prompt,
                      completion_tokens=completion, raw=raw, request_body=body)


def parse_ontology_json(result: ChatResult) -> dict[str, Any]:
    """The `{classes:[...], properties:[...]}` object from `result.content`, with one repair pass (strip code
    fences, take the outermost `{...}`).

    Raises:
        Blocked("MODEL_OUTPUT_TRUNCATED"): `finish_reason == "length"`.
        Blocked("MODEL_OUTPUT_INVALID"): not a JSON object with list `classes` and `properties` after repair.
    """
    if result.finish_reason == "length":
        raise Blocked("MODEL_OUTPUT_TRUNCATED", "the model stopped at the output token limit")
    parsed = _loads(result.content)
    if parsed is None:
        parsed = _loads(_repair(result.content))
    if not isinstance(parsed, dict) or not isinstance(parsed.get("classes"), list) \
            or not isinstance(parsed.get("properties"), list):
        raise Blocked("MODEL_OUTPUT_INVALID", "model output is not a JSON object with `classes` and `properties` lists")
    return parsed


def parse_json_object(result: ChatResult) -> dict[str, Any]:
    """Any JSON object from `result.content`, with the same truncation check and repair pass as
    `parse_ontology_json`. Raises MODEL_OUTPUT_TRUNCATED or MODEL_OUTPUT_INVALID."""
    if result.finish_reason == "length":
        raise Blocked("MODEL_OUTPUT_TRUNCATED", "the model stopped at the output token limit")
    parsed = _loads(result.content)
    if parsed is None:
        parsed = _loads(_repair(result.content))
    if not isinstance(parsed, dict):
        raise Blocked("MODEL_OUTPUT_INVALID", "model output is not a JSON object")
    return parsed


def _loads(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return None


_FENCE = re.compile(r"^\s*```[A-Za-z0-9_-]*\s*\n?|\n?\s*```\s*$")


def _repair(text: str) -> str:
    """Strip code fences, keep the outermost `{...}`, and drop trailing commas outside strings."""
    text = _FENCE.sub("", text.strip())
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return text
    return _drop_trailing_commas(text[start:end + 1])


def _drop_trailing_commas(text: str) -> str:
    out: list[str] = []
    in_string = escaped = False
    for i, ch in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch == ",":
            rest = text[i + 1:].lstrip()
            if rest[:1] in ("}", "]"):
                continue
        out.append(ch)
    return "".join(out)
