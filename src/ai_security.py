"""Small policy boundary for untrusted AI context and tool execution."""
from __future__ import annotations

import json

MAX_CONTEXT_CHARS = 120_000
MAX_TOOL_RESULT_CHARS = 32_000
ALLOWED_TOOLS = frozenset({"run_calculation", "run_simulation", "get_project_items", "search_project_sources"})


def validate_tool(name: str, arguments: object) -> dict[str, object]:
    if name not in ALLOWED_TOOLS:
        raise ValueError(f"Tool '{name}' is not authorized.")
    if not isinstance(arguments, dict):
        raise ValueError("Tool arguments must be an object.")
    if name == "search_project_sources":
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("search_project_sources requires a non-empty query.")
        limit = arguments.get("limit", 8)
        if not isinstance(limit, int) or not 1 <= limit <= 20:
            raise ValueError("search_project_sources limit must be between 1 and 20.")
    return {"tool": name, "authorization": "allowed", "arguments": arguments}


def untrusted_context(value: object, *, label: str = "external data", limit: int = MAX_TOOL_RESULT_CHARS) -> str:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":")) if not isinstance(value, str) else value
    text = text[:limit]
    return f"<untrusted-data source={json.dumps(label)}>{text}</untrusted-data>"


def bound_context(messages: list[dict[str, object]]) -> list[dict[str, object]]:
    """Keep model context bounded and mark non-user tool data as untrusted."""
    bounded: list[dict[str, object]] = []
    total = 0
    for message in messages:
        role = str(message.get("role", ""))
        content = str(message.get("content", ""))
        if role == "tool":
            content = untrusted_context(content, label="tool output")
        remaining = MAX_CONTEXT_CHARS - total
        if remaining <= 0:
            break
        content = content[:remaining]
        bounded.append({**message, "content": content})
        total += len(content)
    return bounded


__all__ = ["ALLOWED_TOOLS", "MAX_CONTEXT_CHARS", "MAX_TOOL_RESULT_CHARS", "validate_tool", "untrusted_context", "bound_context"]
