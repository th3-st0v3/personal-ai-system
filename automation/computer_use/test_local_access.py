from __future__ import annotations

import os
from pathlib import Path

import pytest

from automation.computer_use.local_access import LocalAccessBroker, LocalAccessError


def test_defaults_to_project_root_and_reports_security_levels(tmp_path: Path) -> None:
    broker = LocalAccessBroker(tmp_path)
    names = {item["name"]: item["risk"] for item in broker.capabilities()}
    assert names["computer.system.read"] == "safe"
    assert names["computer.files.read"] == "safe"
    assert names["computer.files.write"] == "approval_required"
    assert names["computer.command.execute"] == "approval_required"
    assert names["computer.credentials.read"] == "denied"


def test_reads_utf8_file_and_preserves_bounds(tmp_path: Path) -> None:
    target = tmp_path / "src"
    target.mkdir()
    (target / "main.py").write_text("print('ok')\n" * 100, encoding="utf-8")
    broker = LocalAccessBroker(tmp_path, max_read_bytes=1000)
    result = broker.read_text("src/main.py", max_chars=39)
    assert result["content"] == "print('ok')\n" * 3 + "pri"
    assert result["truncated"] is True
    assert result["path"].endswith("src/main.py")


def test_blocks_path_traversal_and_sensitive_files(tmp_path: Path) -> None:
    secret = tmp_path / ".env"
    secret.write_text("TOKEN=hidden", encoding="utf-8")
    (tmp_path / "safe.txt").write_text("safe", encoding="utf-8")
    broker = LocalAccessBroker(tmp_path)
    with pytest.raises(LocalAccessError):
        broker.read_text("../outside.txt")
    with pytest.raises(LocalAccessError):
        broker.read_text(".env")


def test_lists_directory_without_exposing_sensitive_entries(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "safe.txt").write_text("ok", encoding="utf-8")
    (tmp_path / ".env").write_text("hidden", encoding="utf-8")
    (tmp_path / "credentials.json").write_text("hidden", encoding="utf-8")
    broker = LocalAccessBroker(tmp_path)
    names = {item["name"] for item in broker.list_directory()}
    assert names == {"src", "safe.txt"}


def test_environment_can_add_explicit_workspace_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    extra = tmp_path / "extra"
    extra.mkdir()
    (extra / "note.txt").write_text("hello", encoding="utf-8")
    monkeypatch.setenv("PASI_ALLOWED_ROOTS", os.fspath(extra))
    broker = LocalAccessBroker(tmp_path)
    assert broker.read_text("note.txt")["content"] == "hello"
    assert str(extra.resolve()) in broker.system_info()["allowed_roots"]
