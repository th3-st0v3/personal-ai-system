from __future__ import annotations

from datetime import datetime, timezone
import tempfile
import unittest
from pathlib import Path

from automation.orchestrator.controller_update import read_last_synced_version, write_sync_state
from scripts.pasi_chat import (
    PUBLIC_REPOSITORY_DEFAULT_BRANCH_URL,
    PUBLIC_REPOSITORY_URL,
    build_prompt,
    controller_observation_is_live,
    needs_github_context,
    process_controller_update_signal,
    public_github_context_unavailable,
    route_chat,
    wait_for_browser_controller,
)


class FakeChatAdapter:
    def __init__(self, state: dict[str, object] | None = None) -> None:
        self.state = state or {}
        self.calls: list[tuple[str, str]] = []

    def read_browser_observation(self) -> dict[str, object]:
        return {"data": dict(self.state)} if self.state else {}

    def new_session(self) -> str:
        self.calls.append(("new_session", ""))
        self.state = {"kind": "chatgpt_state", "chat_url": "https://chatgpt.com/c/new", "chat_exhausted": False, "github_attached": False}
        return "op-new"

    def attach_github_repository(self, repository: str) -> str:
        self.calls.append(("attach_github", repository))
        self.state["github_attached"] = True
        return "op-github"

    def select_reasoning_mode(self, mode: str) -> None:
        self.calls.append(("select_reasoning", mode))
        self.state["reasoning_mode"] = mode


class TestPasiChat(unittest.TestCase):
    def test_build_prompt_uses_public_repo_as_default_and_always_requires_thinking(self) -> None:
        prompt = build_prompt("inspect the bridge", "Repository: https://github.com/example/repo\nWorking tree: clean", {})
        self.assertIn("TASK:\ninspect the bridge", prompt)
        self.assertIn("REPOSITORY STATE:\nRepository: https://github.com/example/repo", prompt)
        self.assertIn("PUBLIC GITHUB CONTEXT:", prompt)
        self.assertIn(PUBLIC_REPOSITORY_URL, prompt)
        self.assertIn(PUBLIC_REPOSITORY_DEFAULT_BRANCH_URL, prompt)
        self.assertIn("public GitHub repository as the default source", prompt)
        self.assertIn("Thinking/reasoning mode is required for every PASI task", prompt)
        self.assertIn("PASI_CONTROLLER_UPDATE: true", prompt)

    def test_build_prompt_includes_bounded_handoff(self) -> None:
        prompt = build_prompt("continue the task", "Working tree: clean", {"chat_url": "https://chatgpt.com/c/example", "summary": "Prior verified handoff"})
        self.assertIn("Active PASI ChatGPT session: https://chatgpt.com/c/example", prompt)
        self.assertIn("Previous PASI handoff:\nPrior verified handoff", prompt)

    def test_build_prompt_does_not_claim_execution(self) -> None:
        self.assertIn("Do not claim files were changed", build_prompt("make a change", "clean working tree", {}))

    def test_live_controller_observation_requires_fresh_state(self) -> None:
        now = datetime(2026, 9, 17, 4, 50, tzinfo=timezone.utc)
        fresh = {"data": {"kind": "chatgpt_state", "captured_at": "2026-09-17T04:49:59Z"}}
        stale = {"data": {"kind": "chatgpt_state", "captured_at": "2026-09-17T04:49:30Z"}}
        malformed = {"data": {"kind": "chatgpt_state", "captured_at": "not-a-timestamp"}}
        self.assertTrue(controller_observation_is_live(fresh, now=now))
        self.assertFalse(controller_observation_is_live(stale, now=now))
        self.assertFalse(controller_observation_is_live(malformed, now=now))

    def test_wait_for_browser_controller_accepts_live_state(self) -> None:
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        adapter = FakeChatAdapter({"kind": "chatgpt_state", "chat_url": "https://chatgpt.com/c/existing", "chat_exhausted": False, "captured_at": now})
        wait_for_browser_controller(adapter, timeout_seconds=0.5)

    def test_wait_for_browser_controller_rejects_missing_controller(self) -> None:
        adapter = FakeChatAdapter()
        with self.assertRaisesRegex(RuntimeError, "browser controller is not reporting a live heartbeat"):
            wait_for_browser_controller(adapter, timeout_seconds=0.2)

    def test_github_app_is_not_selected_by_task_classification(self) -> None:
        self.assertFalse(needs_github_context("inspect the GitHub repository and fix the bridge"))
        self.assertFalse(needs_github_context("update automation/tampermonkey/chatgpt-controller.user.js"))
        self.assertFalse(needs_github_context("review the pull request and latest commit"))
        self.assertFalse(needs_github_context("what is GitHub?"))
        self.assertFalse(needs_github_context("run the unit tests"))
        self.assertFalse(needs_github_context("explain Newton's second law"))

    def test_public_github_failure_signal_detection(self) -> None:
        self.assertTrue(public_github_context_unavailable("PASI_PUBLIC_GITHUB_UNAVAILABLE: true"))
        self.assertTrue(public_github_context_unavailable("I can't access the GitHub repository"))
        self.assertFalse(public_github_context_unavailable("I reviewed the GitHub repository and found the bug."))

    def test_controller_update_signal_requires_explicit_structured_signal(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            controller = root / "automation" / "tampermonkey" / "chatgpt-controller.user.js"
            controller.parent.mkdir(parents=True)
            controller.write_text("// @version      2.4.5\n", encoding="utf-8")
            state_path = root / ".runtime" / "chatgpt" / "controller-sync-state.json"
            write_sync_state(state_path, version="2.4.5")
            result = process_controller_update_signal("PASI_CONTROLLER_UPDATE: true\nPASI_CONTROLLER_UPDATE_VERSION: 2.4.6\nPASI_CONTROLLER_UPDATE_REASON: test", root)
            self.assertTrue(result["eligible"])
            self.assertEqual(read_last_synced_version(state_path), "2.4.5")


if __name__ == "__main__":
    unittest.main()
