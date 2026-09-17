from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from automation.computer_use.ide_state import STATE_RELATIVE_PATH, VSCodeStateReader
from automation.computer_use.local_access import LocalAccessBroker


def _write_state(root: Path, captured_at: str) -> None:
    state_path = root / STATE_RELATIVE_PATH
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({
        "schema_version": "pasi-vscode-readonly-v1",
        "captured_at": captured_at,
        "source": "pasi-vscode-readonly",
        "workspace": {"name": "pasi", "folders": ["pasi"]},
        "active_editor": {"path": "src/main.py", "language": "python", "dirty": True, "line": 4},
        "visible_editors": [{"path": "src/main.py", "language": "python", "dirty": True, "line": 4}],
        "diagnostics": {"errors": 2, "warnings": 1, "information": 0, "hints": 0},
    }), encoding="utf-8")


def test_reader_returns_bounded_current_state(tmp_path: Path) -> None:
    _write_state(tmp_path, datetime.now(timezone.utc).isoformat())
    result = VSCodeStateReader(LocalAccessBroker(tmp_path)).read()
    assert result["status"] == "ok"
    assert result["active_editor"]["path"] == "src/main.py"
    assert result["diagnostics"]["errors"] == 2


def test_reader_rejects_stale_state(tmp_path: Path) -> None:
    captured = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
    _write_state(tmp_path, captured)
    result = VSCodeStateReader(LocalAccessBroker(tmp_path)).read()
    assert result["status"] == "stale"


def test_reader_reports_unavailable_when_extension_has_not_run(tmp_path: Path) -> None:
    result = VSCodeStateReader(LocalAccessBroker(tmp_path)).read()
    assert result["status"] == "unavailable"
