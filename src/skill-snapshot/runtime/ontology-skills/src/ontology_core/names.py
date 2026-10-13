"""Name normalization."""

from __future__ import annotations

import re

VALID = r"^[A-Za-z][A-Za-z0-9_]*$"
RESERVED = frozenset({
    "string", "double", "boolean", "datetime", "integer", "decimal", "float", "date", "time", "anyuri",
    "literal", "thing", "class", "property", "resource",
})
SLUG_MAX = 48

_VALID_RE = re.compile(VALID)
_SEPARATORS = re.compile(r"[_\-\s]+")
_NOT_ALNUM = re.compile(r"[^A-Za-z0-9]")
_WORD = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")
_NOT_SLUG = re.compile(r"[^a-z0-9]+")


def is_valid(name: str) -> bool:
    """`name` matches `VALID` and is not `RESERVED` (case-insensitive)."""
    return isinstance(name, str) and _VALID_RE.match(name) is not None and not is_reserved(name)


def is_reserved(name: str) -> bool:
    """Case-insensitive membership in `RESERVED`."""
    return name.lower() in RESERVED


def split_words(s: str) -> list[str]:
    """Split on `_`, `-`, whitespace and camel boundaries; strip chars outside `[A-Za-z0-9]`."""
    words: list[str] = []
    for token in _SEPARATORS.split(s or ""):
        words.extend(_WORD.findall(_NOT_ALNUM.sub("", token)))
    return words


def _words_without_leading_digits(s: str) -> list[str]:
    words = split_words(s)
    while words and words[0].isdigit():
        words.pop(0)
    return words


def to_pascal(s: str) -> str:
    """`legal entity` -> `LegalEntity`. Leading digits are dropped; may return `""`."""
    return "".join(w[0].upper() + w[1:].lower() for w in _words_without_leading_digits(s))


def to_lower_camel(s: str) -> str:
    """`WORKS_FOR` -> `worksFor`. Leading digits are dropped; may return `""`."""
    pascal = to_pascal(s)
    words = _words_without_leading_digits(s)
    if not words:
        return ""
    return words[0].lower() + pascal[len(words[0]):]


def normalize_class(s: str) -> str:
    """`to_pascal(s)`."""
    return to_pascal(s)


def normalize_property(s: str) -> str:
    """`to_lower_camel(s)`."""
    return to_lower_camel(s)


def slug(s: str) -> str:
    """Lowercase; runs outside `[a-z0-9]` become `-`; trimmed of `-`; at most `SLUG_MAX` chars."""
    return _NOT_SLUG.sub("-", (s or "").lower()).strip("-")[:SLUG_MAX].strip("-")
