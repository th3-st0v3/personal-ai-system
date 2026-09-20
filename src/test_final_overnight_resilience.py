from __future__ import annotations

import sys
from pathlib import Path

from automation.computer_use.obstacles import ObstacleLedger
from scripts import pasi_overnight_engine_v2 as supervisor
from scripts import pasi_overnight_hardening as hardening


def test_obstacle_ledger_keeps_recent_pending_actions_after_compaction(tmp_path: Path) -> None:
    ledger = ObstacleLedger(tmp_path, tmp_path.parent / "operator-state")
    ledger.log_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger.log_path.open("w", encoding="utf-8") as handle:
        for index in range(12_000):
            handle.write(
                '{"obstacle_id":"old-%d","created_at":"2026-01-01T00:00:00+00:00",'
                '"kind":"old","status":"resolved","summary":"old",'
                '"next_action":"none","task_id":"","details":{},"fingerprint":"old-%d"}\n' % (index, index)
            )
        handle.write(
            '{"obstacle_id":"pending-1","created_at":"2026-01-01T00:00:00+00:00",'
            '"kind":"auth_challenge","status":"pending","summary":"needs attention",'
            '"next_action":"complete the browser challenge","task_id":"1",'
            '"details":{},"fingerprint":"pending-1"}\n'
        )

    obstacle = ledger.record(
        "new_failure",
        "a new failure",
        "continue with another task",
        task_id="2",
    )

    assert obstacle.status == "pending"
    assert ledger.log_path.stat().st_size < 2_000_000
    pending = ledger.pending()
    assert any(item.get("obstacle_id") == "pending-1" for item in pending)
    action_list = ledger.list_path.read_text(encoding="utf-8")
    assert "pending-1" in action_list
    assert "This list is informational and non-blocking." in action_list


def test_nonblocking_service_start_does_not_wait_for_health(monkeypatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    class FakeProcess:
        pass

    def fake_popen(command: list[str], cwd: Path) -> FakeProcess:
        assert cwd == supervisor.REPO_ROOT
        calls.append(command)
        return FakeProcess()

    monkeypatch.setattr(hardening.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(supervisor, "healthy", lambda _url: False)
    monkeypatch.setattr(supervisor, "log_event", lambda *_args, **_kwargs: None)

    ledger = ObstacleLedger(tmp_path, tmp_path.parent / "operator-state")
    children = hardening.nonblocking_ensure_services(ledger=ledger)

    assert len(children) == 1
    assert calls == [
        [sys.executable, "-m", "automation.orchestrator.bridge"],
    ]
    assert ledger.pending() == []
