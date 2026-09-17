from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from automation.orchestrator.github_automation_bridge import GitHubAutomationBridge
from automation.orchestrator.github_command_queue import AutomationCommand, GitHubCommandQueue
from automation.orchestrator.state import StateManager
from automation.orchestrator.task_service import TaskService


class FakeQueue:
    def __init__(self, commands: list[AutomationCommand]) -> None:
        self.commands = commands
        self.seen: set[int] | None = None

    def poll_once(self, *, consumed_issue_numbers: set[int]) -> list[AutomationCommand]:
        self.seen = set(consumed_issue_numbers)
        return [command for command in self.commands if command.issue_number not in self.seen]


@dataclass(frozen=True)
class FakeSubmission:
    runner_id: str


class FakeTaskService:
    def __init__(self) -> None:
        self.prompts: list[tuple[str, str]] = []

    def submit(self, prompt: str, *, runner_id: str | None = None) -> FakeSubmission:
        if runner_id is None:
            raise AssertionError("bridge must provide a runner id")
        self.prompts.append((prompt, runner_id))
        return FakeSubmission(runner_id=runner_id)


class FakeStateManager:
    def __init__(self, ai_dir: Path) -> None:
        self.ai_dir = ai_dir

    def read_json(self, path: Path, default: Any) -> Any:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default

    def write_json(self, path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")


def test_bridge_persists_consumed_issue_numbers(tmp_path: Path) -> None:
    state_manager = FakeStateManager(tmp_path / ".ai")
    queue = FakeQueue([AutomationCommand(12, "th3-st0v3", "inspect code", "[PASI AUTOMATION] inspect")])
    service = FakeTaskService()
    bridge = GitHubAutomationBridge(
        cast(GitHubCommandQueue, queue),
        cast(TaskService, service),
        cast(StateManager, state_manager),
    )

    assert bridge.poll_once() == ["github-issue-12"]
    assert service.prompts == [("inspect code", "github-issue-12")]
    assert bridge.poll_once() == []
    assert queue.seen == {12}
