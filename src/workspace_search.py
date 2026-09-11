"""Search across the unified project workspace browser."""
from __future__ import annotations

from dataclasses import replace

import workspace_browser


def search_project(
    project_id: int,
    query: str,
    *,
    recursive: bool = True,
) -> list[workspace_browser.BrowserItem]:
    """Return workspace items whose searchable text contains query.

    Search covers names for every item and note content for notes. Matching is
    case-insensitive and whitespace-normalized. Empty queries are rejected so
    callers cannot accidentally request the entire workspace through search.
    """
    normalized = " ".join(query.split()).casefold()
    if not normalized:
        raise ValueError("Search query is required.")

    items = workspace_browser.list_project_items(
        project_id, recursive=recursive, sort="a_z"
    )
    matches: list[workspace_browser.BrowserItem] = []
    for item in items:
        searchable = [item.name]
        if item.kind == "note" and item.content:
            searchable.append(item.content)
        if any(normalized in text.casefold() for text in searchable):
            matches.append(item)
    return matches


def search_project_names(project_id: int, query: str) -> list[workspace_browser.BrowserItem]:
    """Search only item names, including nested workspace items."""
    normalized = " ".join(query.split()).casefold()
    if not normalized:
        raise ValueError("Search query is required.")
    return [
        item
        for item in workspace_browser.list_project_items(project_id, recursive=True)
        if normalized in item.name.casefold()
    ]


__all__ = ["search_project", "search_project_names"]
