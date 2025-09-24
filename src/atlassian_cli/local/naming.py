"""Utilities for mapping Confluence page titles to filesystem-friendly names."""

from __future__ import annotations

import re


_NON_WORD_RE = re.compile(r"[^a-z0-9]+")


def slugify(value: str, *, fallback: str = "page") -> str:
    """Return a filesystem-safe slug derived from ``value``.

    This helper keeps the implementation intentionally small to avoid pulling
    in a dedicated slugification dependency. It lowercases the input, replaces
    non-alphanumeric characters with hyphens, and collapses consecutive
    separators.
    """

    value = value.lower().strip()
    value = _NON_WORD_RE.sub("-", value)
    value = value.strip("-")
    if not value:
        return fallback
    # Guard against hidden files and overly long names.
    if value.startswith("."):
        value = value.lstrip(".") or fallback
    return value[:120]
