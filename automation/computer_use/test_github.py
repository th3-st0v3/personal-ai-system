from __future__ import annotations

import unittest
from typing import Any, Mapping

from automation.computer_use.contracts import ActionProposal, Observation
from automation.computer_use.github import (
    GitHubAdapterError,
    GitHubControlAdapter,
    UrllibGitHubTransport,
)


class FakeGitHubTransport:
    def __init__(self, response: Any = None) -> None:
        self.response = {"id": 1, "full_name": "owner/repo"} if response is None else response
        self.requests: list[tuple[str, str, Mapping[str, Any] | None]] = []

    def request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
    ) -> Any:
        self.requests.append((method, path, payload))
        return self.response


class FakeComputerAdapter:
    def __init__(self) -> None:
        self.actions: list[ActionProposal] = []

    def observe(self) -> Observation:
        raise AssertionError("unexpected observe")

    def execute(self, action: ActionProposal) -> Observation:
        self.actions.append(action)
        return Observation(
            observation_id="ui-observation",
            session_id=action.session_id,
            source="github-ui",
            kind="github.ui",
            data={"action_id": action.action_id},
        )


class GitHubTransportTests(unittest.TestCase):
    def test_accepts_github_api_host(self) -> None:
        transport = UrllibGitHubTransport()
        self.assertEqual(transport.api_base_url, "https://api.github.com")

    def test_rejects_non_github_api_host(self) -> None:
        with self.assertRaises(ValueError):
            UrllibGitHubTransport("https://api.github.com.example.com")

    def test_rejects_credentials_in_api_url(self) -> None:
        with self.assertRaises(ValueError):
            UrllibGitHubTransport("https://user:pass@api.github.com")

    def test_rejects_path_traversal(self) -> None:
        transport = FakeGitHubTransport()
        adapter = GitHubControlAdapter("owner", "repo", transport)
        action = ActionProposal("a1", "s1", "github", "github_read", {"operation": "file", "parameters": {"path": "../secret"}})
        with self.assertRaises(ValueError):
            adapter.execute(action)


class GitHubControlAdapterTests(unittest.TestCase):
    def test_observe_reads_repository(self) -> None:
        transport = FakeGitHubTransport({"id": 1, "full_name": "owner/repo"})
        adapter = GitHubControlAdapter("owner", "repo", transport, session_id="s1")
        observation = adapter.observe()
        self.assertEqual(observation.source, "github-api")
        self.assertEqual(observation.kind, "github.repository")
        self.assertEqual(transport.requests[0], ("GET", "/repos/owner/repo", None))

    def test_read_file_uses_bounded_repository_path(self) -> None:
        transport = FakeGitHubTransport({"path": "src/main.py"})
        adapter = GitHubControlAdapter("owner", "repo", transport, session_id="s1")
        action = ActionProposal("a1", "s1", "github", "github_read", {"operation": "file", "parameters": {"path": "src/main.py"}})
        result = adapter.execute(action)
        self.assertEqual(result.kind, "github.file")
        self.assertEqual(transport.requests[0][1], "/repos/owner/repo/contents/src/main.py")

    def test_list_response_is_normalized_to_items(self) -> None:
        transport = FakeGitHubTransport([{"number": 1}, {"number": 2}])
        adapter = GitHubControlAdapter("owner", "repo", transport, session_id="s1")
        action = ActionProposal("a1", "s1", "github", "github_read", {"operation": "pulls"})
        result = adapter.execute(action)
        self.assertEqual(result.data["items"], [{"number": 1}, {"number": 2}])

    def test_pull_request_state_is_allowlisted(self) -> None:
        transport = FakeGitHubTransport()
        adapter = GitHubControlAdapter("owner", "repo", transport)
        action = ActionProposal("a1", "s1", "github", "github_read", {"operation": "pulls", "parameters": {"state": "pending"}})
        with self.assertRaises(ValueError):
            adapter.execute(action)

    def test_ui_fallback_is_explicit(self) -> None:
        ui = FakeComputerAdapter()
        adapter = GitHubControlAdapter("owner", "repo", FakeGitHubTransport(), ui_adapter=ui)
        action = ActionProposal("a1", "s1", "github.com", "github_ui", {"operation": "review"})
        result = adapter.execute(action)
        self.assertEqual(result.source, "github-ui")
        self.assertEqual(ui.actions, [action])

    def test_ui_fallback_requires_configuration(self) -> None:
        adapter = GitHubControlAdapter("owner", "repo", FakeGitHubTransport())
        action = ActionProposal("a1", "s1", "github.com", "github_ui")
        with self.assertRaises(GitHubAdapterError):
            adapter.execute(action)

    def test_ui_fallback_rejects_non_github_target(self) -> None:
        ui = FakeComputerAdapter()
        adapter = GitHubControlAdapter("owner", "repo", FakeGitHubTransport(), ui_adapter=ui)
        action = ActionProposal("a1", "s1", "example.com", "github_ui")
        with self.assertRaises(GitHubAdapterError):
            adapter.execute(action)

    def test_unknown_action_is_rejected(self) -> None:
        adapter = GitHubControlAdapter("owner", "repo", FakeGitHubTransport())
        action = ActionProposal("a1", "s1", "github", "observe")
        with self.assertRaises(GitHubAdapterError):
            adapter.execute(action)


if __name__ == "__main__":
    unittest.main()
