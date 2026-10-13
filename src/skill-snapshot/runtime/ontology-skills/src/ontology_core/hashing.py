"""Canonical JSON and the hashes built on it (schema_id, plan_id, evidence IDs).

Hashed files are written as `canonical_json(obj) + "\\n"`; their identity is the
SHA-256 of exactly those bytes. Human-facing files use `pretty_json`.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA_ID_PREFIX = "sha256:"
PLAN_ID_PREFIX = "oplan-"
PLAN_ID_EXCLUDED = ("plan_id", "created_at", "estimate")


def canonical_json(value: Any) -> str:
    """Sorted keys, no whitespace, UTF-8 text (no ASCII escaping), NaN refused."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def canonical_bytes(value: Any) -> bytes:
    """The exact bytes of a hashed file: canonical JSON plus one trailing LF."""
    return (canonical_json(value) + "\n").encode("utf-8")


def pretty_json(value: Any) -> bytes:
    """Human-facing JSON: sorted keys, 2-space indent, one trailing LF."""
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_json(value: Any) -> str:
    """SHA-256 of `canonical_json(value)` (no trailing LF), e.g. the GRZ manifest digest."""
    return sha256_text(canonical_json(value))


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def schema_id_of_bytes(data: bytes) -> str:
    return SCHEMA_ID_PREFIX + sha256_bytes(data)


def schema_id(ontology_dict: dict[str, Any]) -> str:
    """`"sha256:" + sha256(canonical bytes of ontology.v<N>.json)`."""
    return schema_id_of_bytes(canonical_bytes(ontology_dict))


def schema_hash12(schema_id_value: str) -> str:
    """The 12-hex suffix used in `exports/export-manifest.<hash12>.json`."""
    return schema_id_value.removeprefix(SCHEMA_ID_PREFIX)[:12]


def plan_id(plan_dict: dict[str, Any]) -> str:
    """`"oplan-" + sha256(canonical_json(plan minus {plan_id, created_at, estimate}))[:16]`."""
    body = {k: v for k, v in plan_dict.items() if k not in PLAN_ID_EXCLUDED}
    return PLAN_ID_PREFIX + sha256_json(body)[:16]


def sampling_seed(*, generation_id: str, manifest_digest: str, level: int, passages: int,
                  excerpt_chars: int, shard_chars: int) -> str:
    """The sampler's `plan_id_seed`: fixed by the generation and the resolved sampling inputs only,
    so a prompt or price edit changes the plan ID but never the passages chosen."""
    return sha256_json({"generation_id": generation_id, "manifest_digest": manifest_digest, "level": level,
                        "passages": passages, "excerpt_chars": excerpt_chars, "shard_chars": shard_chars})


def evidence_id(chunk_id: str, length: int = 10) -> str:
    """`"E" + sha256(chunk_id)[:10]`; the sampler falls back to length 12 on a collision."""
    return "E" + sha256_text(chunk_id)[:length]
