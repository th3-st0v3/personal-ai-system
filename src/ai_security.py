"""Explicit trust boundary for untrusted AI context, source content, and tool execution."""
from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence

MAX_CONTEXT_CHARS = 120_000
MAX_TOOL_RESULT_CHARS = 32_000
MAX_SOURCE_CHARS = 2_000_000
MAX_QUERY_CHARS = 2_000
MAX_TOOL_ARGUMENTS_CHARS = 8_000
ALLOWED_TOOLS = frozenset({"run_calculation", "run_simulation", "get_project_items", "search_project_sources"})

# These markers do not prove that content is malicious. They flag content that
# deserves explicit treatment as untrusted context and prevent callers from
# accidentally promoting it into a system/developer instruction channel.
INSTRUCTION_MARKERS = re.compile(
    r"(?:ignore\s+(?:all|any|previous|prior)\s+instructions|system\s+message|developer\s+message|"
    r"reveal\s+(?:the|your)\s+(?:prompt|system\s+instructions)|disable\s+(?:security|safety)|"
    r"run\s+(?:this|the)\s+command|curl\s+https?://|wget\s+https?://)",
    re.IGNORECASE,
)


def validate_tool(name: str, arguments: object) -> dict[str, object]:
    if name not in ALLOWED_TOOLS:
        raise ValueError(f"Tool '{name}' is not authorized.")
    if not isinstance(arguments, dict):
        raise ValueError("Tool arguments must be an object.")
    encoded = json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))
    if len(encoded) > MAX_TOOL_ARGUMENTS_CHARS:
        raise ValueError("Tool arguments exceed the safety size limit.")
    if name == "search_project_sources":
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("search_project_sources requires a non-empty query.")
        if len(query) > MAX_QUERY_CHARS:
            raise ValueError(f"search_project_sources query exceeds {MAX_QUERY_CHARS} characters.")
        limit = arguments.get("limit", 8)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
            raise ValueError("search_project_sources limit must be between 1 and 20.")
    elif name == "get_project_items" and arguments:
        raise ValueError("get_project_items does not accept arguments.")
    return {"tool": name, "authorization": "allowed", "arguments": arguments}


def validate_external_text(value: object, *, field: str = "content", max_chars: int = MAX_SOURCE_CHARS) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string.")
    text = value.replace("\x00", "")
    if not text.strip():
        raise ValueError(f"{field} must be non-empty.")
    if len(text) > max_chars:
        raise ValueError(f"{field} exceeds {max_chars} characters.")
    return text


def inspect_untrusted_text(value: object, *, label: str = "external data", max_chars: int = MAX_SOURCE_CHARS) -> dict[str, object]:
    text = validate_external_text(value, field=label, max_chars=max_chars)
    marker_count = len(INSTRUCTION_MARKERS.findall(text))
    return {
        "label": label,
        "chars": len(text),
        "instruction_markers": marker_count,
        "suspected_injection": marker_count > 0,
        "trust": "untrusted",
    }


def untrusted_context(value: object, *, label: str = "external data", limit: int = MAX_TOOL_RESULT_CHARS) -> str:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":")) if not isinstance(value, str) else value
    text = text[:limit]
    metadata = inspect_untrusted_text(text, label=label, max_chars=limit)
    wrapper = json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
    return f"<untrusted-data trust=untrusted metadata={wrapper}>{text}</untrusted-data>"


def bound_context(messages: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """Keep context bounded and mark every non-system external result as untrusted."""
    bounded: list[dict[str, object]] = []
    total = 0
    for message in messages:
        role = str(message.get("role", ""))
        content = str(message.get("content", ""))
        if role == "tool":
            content = untrusted_context(content, label="tool output")
        elif role not in {"system", "developer", "user"}:
            content = untrusted_context(content, label=f"message:{role or 'unknown'}")
        remaining = MAX_CONTEXT_CHARS - total
        if remaining <= 0:
            break
        content = content[:remaining]
        bounded.append({**message, "content": content})
        total += len(content)
    return bounded


__all__ = [
    "ALLOWED_TOOLS",
    "INSTRUCTION_MARKERS",
    "MAX_CONTEXT_CHARS",
    "MAX_QUERY_CHARS",
    "MAX_SOURCE_CHARS",
    "MAX_TOOL_ARGUMENTS_CHARS",
    "MAX_TOOL_RESULT_CHARS",
    "validate_tool",
    "validate_external_text",
    "inspect_untrusted_text",
    "untrusted_context",
    "bound_context",
]
