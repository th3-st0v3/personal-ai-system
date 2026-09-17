from __future__ import annotations

from pathlib import Path

from .github_command_queue import GitHubCommandQueue
from .state import StateCorruptionError, StateManager
from .task_service import TaskService


class GitHubAutomationBridge:
    """Connect the GitHub command queue to the application TaskService.

    Consumption is recorded only after TaskService accepts the command, and the
    consumed ledger is persisted so a process restart cannot replay old issues.
    """

    def __init__(self, queue: GitHubCommandQueue, task_service: TaskService, state_manager: StateManager) -> None:
        self.queue = queue
        self.task_service = task_service
        self.state_manager = state_manager
        self.state_path = state_manager.ai_dir / "github-automation-command-state.json"

    def poll_once(self) -> list[str]:
        consumed = self._load_consumed()
        submissions: list[str] = []
        for command in self.queue.poll_once(consumed_issue_numbers=consumed):
            submission = self.task_service.submit(command.prompt, runner_id=f"github-issue-{command.issue_number}")
            consumed.add(command.issue_number)
            self._save_consumed(consumed)
            submissions.append(submission.runner_id)
        return submissions

    def _load_consumed(self) -> set[int]:
        value = self.state_manager.read_json(self.state_path, {"version": 1, "consumed_issue_numbers": []})
        if not isinstance(value, dict) or value.get("version") != 1:
            raise StateCorruptionError("Invalid GitHub automation command state")
        numbers = value.get("consumed_issue_numbers")
        if not isinstance(numbers, list) or any(not isinstance(item, int) or isinstance(item, bool) or item < 1 for item in numbers):
            raise StateCorruptionError("Invalid GitHub automation command ledger")
        return set(numbers)

    def _save_consumed(self, consumed: set[int]) -> None:
        bounded = sorted(consumed)[-1_000:]
        self.state_manager.write_json(
            self.state_path,
            {"version": 1, "consumed_issue_numbers": bounded},
        )


__all__ = ["GitHubAutomationBridge"]
