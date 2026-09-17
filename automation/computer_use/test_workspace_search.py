from pathlib import Path

import pytest

from automation.computer_use.local_access import LocalAccessBroker, LocalAccessError
from automation.computer_use.workspace_search import WorkspaceSearch


def test_search_returns_matching_lines_inside_allowed_roots(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "main.py").write_text("alpha\nneedle here\nneedle again\n", encoding="utf-8")
    results = WorkspaceSearch(LocalAccessBroker(tmp_path)).search("needle", limit=2)
    assert len(results) == 2
    assert results[0]["path"].endswith("src/main.py")
    assert results[0]["line"] == 2
    assert "needle" in results[0]["snippet"]


def test_search_skips_sensitive_and_symlinked_files(tmp_path: Path) -> None:
    (tmp_path / "safe.txt").write_text("needle", encoding="utf-8")
    (tmp_path / "credentials.json").write_text("needle", encoding="utf-8")
    try:
        (tmp_path / "link.txt").symlink_to(tmp_path / "safe.txt")
    except OSError:
        pass
    results = WorkspaceSearch(LocalAccessBroker(tmp_path)).search("needle", limit=10)
    paths = [item["path"] for item in results]
    assert any(path.endswith("safe.txt") for path in paths)
    assert not any(path.endswith("credentials.json") for path in paths)
    assert not any(path.endswith("link.txt") for path in paths)


def test_search_bounds_query_and_result_limit(tmp_path: Path) -> None:
    (tmp_path / "note.txt").write_text("needle\n" * 10, encoding="utf-8")
    searcher = WorkspaceSearch(LocalAccessBroker(tmp_path), max_results=3)
    with pytest.raises(ValueError):
        searcher.search("x" * 201)
    assert len(searcher.search("needle", limit=3)) == 3
