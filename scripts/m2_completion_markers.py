"""Shared completion-marker matching for M2 live acceptance evidence."""

from __future__ import annotations

import re
from collections.abc import Iterable

_MARKDOWN_WRAPPER_RE = re.compile(r"^[\s`*_~]+|[\s`*_~]+$")


def collapse_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalize_marker_line(value: str) -> str:
    """Normalize harmless Markdown/punctuation wrappers around a marker."""
    normalized = value.strip()
    normalized = _MARKDOWN_WRAPPER_RE.sub("", normalized)
    normalized = normalized.strip().rstrip(".,;!?")
    normalized = _MARKDOWN_WRAPPER_RE.sub("", normalized)
    return normalized.strip()


def marker_satisfied(response_text: object, markers: Iterable[object]) -> bool:
    if not isinstance(response_text, str) or not response_text.strip():
        return False

    configured = [
        marker.strip()
        for marker in markers
        if isinstance(marker, str) and marker.strip()
    ]
    if not configured:
        return True

    lines = [normalize_marker_line(line) for line in response_text.splitlines()]
    collapsed = collapse_whitespace(response_text)

    for marker in configured:
        normalized_marker = collapse_whitespace(marker)
        normalized_lines = [collapse_whitespace(line) for line in lines]
        if any(
            line == normalized_marker
            or line.startswith(normalized_marker + ":")

            for line in normalized_lines
        ):
            return True
        if collapsed == normalized_marker:
            return True
        if collapsed.endswith(" " + normalized_marker):
            return True
        if collapsed.endswith(" " + normalized_marker + ":"):
            return True
    return False