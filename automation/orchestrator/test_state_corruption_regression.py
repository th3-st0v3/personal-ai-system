from __future__ import annotations

import pytest

from automation.orchestrator.state import StateManager


def test_corrupt_json_fails_closed_instead_of_returning_default(tmp_path) -> None:
    manager = StateManager(tmp_path / ".ai")
    manager.queue_path.parent.mkdir(parents=True, exist_ok=True)
    manager.queue_path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Corrupt state file"):
        manager.load_queue()


def test_wrong_state_shape_fails_closed_for_queue(tmp_path) -> None:
    manager = StateManager(tmp_path / ".ai")
    manager.queue_path.parent.mkdir(parents=True, exist_ok=True)
    manager.queue_path.write_text("{}", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Invalid state shape"):
        manager.load_queue()
