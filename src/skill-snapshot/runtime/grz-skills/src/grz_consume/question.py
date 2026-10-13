"""Question embedding helpers for ranked member browsing."""

from __future__ import annotations

import math
from typing import Any

from grz_core.contracts import ContractError

KNOWN_EMBEDDERS = {"bge-small-en-v1.5@5c38ec7c405e": ("BAAI/bge-small-en-v1.5", 384)}
_CACHE: dict[str, Any] = {}
MAX_QUESTION_CHARS = 2000


def normalize_vector(vector: Any, dimension: int) -> list[float]:
    if (
        not isinstance(vector, (list, tuple)) or len(vector) != dimension
        or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in vector)
    ):
        raise ContractError("QUERY_VECTOR_INVALID", "Question vector must be finite and match descriptor dimension")
    norm = math.sqrt(sum(float(x) * float(x) for x in vector))
    if not norm or not math.isfinite(norm):
        raise ContractError("QUERY_VECTOR_INVALID", "Question vector must have finite nonzero norm")
    return [float(x) / norm for x in vector]


def _model(embedding_model_id: str) -> Any:
    if embedding_model_id not in KNOWN_EMBEDDERS:
        raise ContractError(
            "QUESTION_EMBEDDER_UNSUPPORTED",
            "Unknown embedding model; pass a precomputed vector with --question-vector / question_vector",
        )
    model_name, _ = KNOWN_EMBEDDERS[embedding_model_id]
    if embedding_model_id not in _CACHE:
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise ContractError("FASTEMBED_MISSING", "install the embed extra: grz-skills[azure,embed]") from exc
        _CACHE[embedding_model_id] = TextEmbedding(model_name)
    return _CACHE[embedding_model_id]


def embed_question(text: str, embedding_model_id: str, dimension: int, embedder: Any | None = None) -> list[float]:
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_QUESTION_CHARS:
        raise ContractError("QUESTION_INVALID", "Question text must be 1..2000 characters")
    if embedding_model_id not in KNOWN_EMBEDDERS:
        raise ContractError(
            "QUESTION_EMBEDDER_UNSUPPORTED",
            "Unknown embedding model; pass a precomputed vector with --question-vector / question_vector",
        )
    _model_name, expected_dimension = KNOWN_EMBEDDERS[embedding_model_id]
    if expected_dimension != dimension:
        raise ContractError("QUERY_VECTOR_INVALID", "Question embedder dimension does not match descriptor")
    model = embedder if embedder is not None else _model(embedding_model_id)
    try:
        raw = next(iter(model.query_embed([text])))
    except AttributeError:
        raw = next(iter(model([text])))
    return normalize_vector([float(x) for x in raw], dimension)
