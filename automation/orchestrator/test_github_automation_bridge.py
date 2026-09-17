import json
from pathlib import Path

from automation.orchestrator.github_automation_bridge import GitHubAutomationBridge
from automation.orchestrator.github_command_queue import AutomationCommand


class FakeQueue:
    def __init__(self, commands):
        self.commands = commands
        self.seen: set[int] | None = None

    def poll_once(self, *, consumed_issue_numbers):
        self.seen = set(consumed_issue_numbers)
        return [command for command in self.commands if command.issue_number not in self.seen]


class FakeTaskService:
    def __init__(self):
        self.prompts: list[tuple[str, str]] = []

    def submit(self, prompt, *, runner_id=None):
        self.prompts.append((prompt, runner_id))
        return type("Submission", (), {"runner_id": runner_id})()


def test_bridge_persists_consumed_issue_numbers(tmp_path: Path):
    state_manager = type(
        "State",
        (),
        {
            "ai_dir": tmp_path / ".ai",
            "read_json": lambda self, path, default: json.loads(path.read_text(encoding="utf-8")) if path.exists() else default,
            "write_json": lambda self, path, value: (path.parent.mkdir(parents=True, exist_ok=True), path.write_text(json.dumps(value), encoding="utf-8")),
        },
    )()
    queue = FakeQueue([AutomationCommand(12, "th3-st0v3", "inspect code", "[PASI AUTOMATION] inspect")])
    service = FakeTaskService()
    bridge = GitHubAutomationBridge(queue, service, state_manager)

    assert bridge.poll_once() == ["github-issue-12"]
    assert service.prompts == [("inspect code", "github-issue-12")]
    assert bridge.poll_once() == []
    assert queue.seen == {12}
