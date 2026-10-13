"""Page sizes, opaque keyset cursors and bounded parallel reads."""

from __future__ import annotations

import base64
import binascii
import bisect
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from grz_core.contracts import ContractError

MAX_PAGE_SIZE = 1000
MAX_READ_WORKERS = 8


def parallel_reads(fn: Any, items: list[Any]) -> list[Any]:
    """Run independent bounded reads concurrently; results keep input order, first error propagates."""
    if len(items) <= 1:
        return [fn(item) for item in items]
    with ThreadPoolExecutor(max_workers=min(MAX_READ_WORKERS, len(items))) as pool:
        return list(pool.map(fn, items))


def check_page_size(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_PAGE_SIZE:
        raise ContractError("PAGE_SIZE_INVALID", "page_size must be between 1 and 1000")
    return value


def decode_cursor(value: str | None, context: list[Any]) -> str | None:
    """Return the last sort key, rejecting cursors minted for another generation or query."""
    if value is None:
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(value.encode("ascii")).decode("utf-8"))
        if data["context"] != context or not isinstance(data["last"], str):
            raise ValueError("cursor context mismatch")
        return data["last"]
    except (ValueError, KeyError, TypeError, UnicodeError, binascii.Error) as exc:
        raise ContractError("CURSOR_INVALID", "Invalid or mismatched continuation cursor") from exc


def encode_cursor(last: str, context: list[Any]) -> str:
    data = json.dumps({"context": context, "last": last}, separators=(",", ":"))
    return base64.urlsafe_b64encode(data.encode("utf-8")).decode("ascii")


def page_in_memory(rows: list[dict[str, Any]], page_size: int, cursor: str | None,
                   context: list[Any]) -> dict[str, Any]:
    size = check_page_size(page_size)
    last = decode_cursor(cursor, context)
    rows = sorted(rows, key=lambda row: row["sort_key"])
    keys = [row["sort_key"] for row in rows]
    start = bisect.bisect_right(keys, last) if last is not None else 0
    page = rows[start : start + size]
    return {
        "items": page,
        "next_cursor": encode_cursor(page[-1]["sort_key"], context) if start + size < len(rows) else None,
    }
