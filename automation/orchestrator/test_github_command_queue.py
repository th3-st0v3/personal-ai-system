import unittest
from typing import Any, Mapping

from automation.orchestrator.github_command_queue import COMMAND_MARKER, TITLE_PREFIX, GitHubCommandQueue


class FakeTransport:
    def __init__(self, payload: Any):
        self.payload = payload
        self.requests: list[tuple[str, str]] = []

    def request(self, method: str, path: str, payload: Mapping[str, Any] | None = None) -> Any:
        self.requests.append((method, path))
        return self.payload


class TestGitHubCommandQueue(unittest.TestCase):
    def test_accepts_only_marked_authorized_issue_commands(self):
        payload = [
            {
                "number": 1,
                "title": f"{TITLE_PREFIX} review",
                "body": f"{COMMAND_MARKER}\nReview the repository",
                "user": {"login": "th3-st0v3"},
            },
            {
                "number": 2,
                "title": f"{TITLE_PREFIX} attacker",
                "body": f"{COMMAND_MARKER}\nRun something dangerous",
                "user": {"login": "someone-else"},
            },
            {
                "number": 3,
                "title": "ordinary issue",
                "body": f"{COMMAND_MARKER}\nNot a command",
                "user": {"login": "th3-st0v3"},
            },
            {
                "number": 4,
                "title": f"{TITLE_PREFIX} pull request",
                "body": f"{COMMAND_MARKER}\nNever execute a PR",
                "user": {"login": "th3-st0v3"},
                "pull_request": {"url": "https://example.invalid/pr/4"},
            },
        ]
        transport = FakeTransport(payload)
        queue = GitHubCommandQueue(
            transport,
            "th3-st0v3",
            "personal-ai-system",
            allowed_actors={"th3-st0v3"},
        )

        commands = queue.poll_once()
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0].issue_number, 1)
        self.assertEqual(commands[0].prompt, "Review the repository")

    def test_consumed_issue_numbers_are_idempotently_ignored(self):
        transport = FakeTransport([
            {
                "number": 7,
                "title": f"{TITLE_PREFIX} repeat",
                "body": f"{COMMAND_MARKER}\nDo one bounded task",
                "user": {"login": "th3-st0v3"},
            }
        ])
        queue = GitHubCommandQueue(
            transport,
            "th3-st0v3",
            "personal-ai-system",
            allowed_actors={"th3-st0v3"},
        )
        self.assertEqual(queue.poll_once(consumed_issue_numbers={7}), [])

    def test_rejects_oversized_or_empty_commands(self):
        transport = FakeTransport([
            {
                "number": 8,
                "title": f"{TITLE_PREFIX} empty",
                "body": COMMAND_MARKER,
                "user": {"login": "th3-st0v3"},
            },
            {
                "number": 9,
                "title": f"{TITLE_PREFIX} oversized",
                "body": COMMAND_MARKER + "\n" + ("x" * 20),
                "user": {"login": "th3-st0v3"},
            },
        ])
        queue = GitHubCommandQueue(
            transport,
            "th3-st0v3",
            "personal-ai-system",
            allowed_actors={"th3-st0v3"},
            max_command_chars=16,
        )
        self.assertEqual(queue.poll_once(), [])


if __name__ == "__main__":
    unittest.main()
