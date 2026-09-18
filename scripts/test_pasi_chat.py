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
    task_fingerprint,
    pending_operation_for_task,
    checkpoint_active_operation,
    clear_active_operation,
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
        self.assertIn("Previous PASI ChatGPT session: https://chatgpt.com/c/example", prompt)
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
        self.assertFalse(needs_github_context("explain Newton's second law", override="public"))
        self.assertFalse(needs_github_context("explain Newton's second law", override="auto"))
        self.assertTrue(needs_github_context("explain Newton's second law", override="fallback"))
        self.assertTrue(needs_github_context("explain Newton's second law", override="always"))
        self.assertFalse(needs_github_context("fix the repository", override="never"))

    def test_public_github_unavailable_detection_is_conservative(self) -> None:
        self.assertTrue(public_github_context_unavailable("PASI_PUBLIC_GITHUB_UNAVAILABLE: true"))
        self.assertTrue(public_github_context_unavailable("I cannot access the GitHub repository from this environment."))
        self.assertTrue(public_github_context_unavailable("The public GitHub link is not accessible here."))
        self.assertFalse(public_github_context_unavailable("I inspected the public repository and found the bridge implementation."))
        self.assertFalse(public_github_context_unavailable("GitHub is useful for source control."))

    def test_exact_pending_operation_is_reused_before_chat_routing(self) -> None:
        task = "repair the timeout path"
        adapter = FakeChatAdapter({"kind": "chatgpt_state", "chat_url": "https://chatgpt.com/c/existing", "chat_exhausted": False})
        handoff = {
            "chat_url": "https://chatgpt.com/c/existing",
            "active_operation_id": "op-pending",
            "active_task_fingerprint": task_fingerprint(task),
        }
        updated, chat_url = route_chat(adapter, handoff, task, "th3-st0v3/personal-ai-system", "auto")
        self.assertEqual(chat_url, "https://chatgpt.com/c/existing")
        self.assertEqual(updated["active_operation_id"], "op-pending")
        self.assertNotIn(("new_session", ""), adapter.calls)
        self.assertNotIn(("select_reasoning", "thinking"), adapter.calls)

    def test_pending_operation_is_task_scoped(self) -> None:
        task = "repair the timeout path"
        handoff = {"active_operation_id": "op-pending", "active_task_fingerprint": task_fingerprint(task)}
        self.assertEqual(pending_operation_for_task(handoff, task), "op-pending")
        self.assertIsNone(pending_operation_for_task(handoff, "different task"))

    def test_checkpoint_and_clear_preserve_exact_operation_identity(self) -> None:
        task = "checkpoint timeout operation"
        handoff = {"chat_url": "https://chatgpt.com/c/current"}
        checkpoint_active_operation(handoff, "op-timeout", task)
        self.assertEqual(handoff["active_operation_id"], "op-timeout")
        self.assertEqual(handoff["active_task_fingerprint"], task_fingerprint(task))
        self.assertEqual(handoff["active_operation_chat_url"], "https://chatgpt.com/c/current")
        clear_active_operation(handoff)
        self.assertNotIn("active_operation_id", handoff)
        self.assertNotIn("active_task_fingerprint", handoff)
        self.assertNotIn("active_operation_chat_url", handoff)

    def test_reuses_existing_chat_and_enables_thinking(self) -> None:
        adapter = FakeChatAdapter({"kind": "chatgpt_state", "chat_url": "https://chatgpt.com/c/existing", "chat_exhausted": False, "github_attached": False})
        handoff, chat_url = route_chat(adapter, {"chat_url": "https://chatgpt.com/c/existing", "chat_exhausted": False}, "explain thermodynamics", "th3-st0v3/personal-ai-system", "auto")
        self.assertEqual(chat_url, "https://chatgpt.com/c/existing")
        self.assertNotIn(("new_session", ""), adapter.calls)
        self.assertIn(("select_reasoning", "thinking"), adapter.calls)
        self.assertNotIn(("attach_github", "th3-st0v3/personal-ai-system"), adapter.calls)
        self.assertFalse(handoff["github_attached"])
        self.assertEqual(handoff["context_source"], "public_github")

    def test_creates_new_chat_only_when_existing_chat_is_exhausted(self) -> None:
        adapter = FakeChatAdapter({"kind": "chatgpt_state", "chat_url": "https://chatgpt.com/c/existing", "chat_exhausted": True, "github_attached": False})
        handoff, _ = route_chat(adapter, {"chat_url": "https://chatgpt.com/c/existing", "chat_exhausted": False}, "explain thermodynamics", "th3-st0v3/personal-ai-system", "auto")
        self.assertIn(("new_session", ""), adapter.calls)
        self.assertIn(("select_reasoning", "thinking"), adapter.calls)
        self.assertFalse(handoff["chat_exhausted"])

    def test_public_repo_task_does_not_attach_github_app(self) -> None:
        adapter = FakeChatAdapter({"kind": "chatgpt_state", "chat_url": "https://chatgpt.com/c/existing", "chat_exhausted": False, "github_attached": False})
        handoff, _ = route_chat(adapter, {"chat_url": "https://chatgpt.com/c/existing", "chat_exhausted": False}, "inspect the repository bridge", "th3-st0v3/personal-ai-system", "auto")
        self.assertNotIn(("attach_github", "th3-st0v3/personal-ai-system"), adapter.calls)
        self.assertIn(("select_reasoning", "thinking"), adapter.calls)
        self.assertFalse(handoff["github_attached"])
        self.assertEqual(handoff["context_source"], "public_github")

    def test_explicit_fallback_attaches_github_but_keeps_thinking_enabled(self) -> None:
        adapter = FakeChatAdapter({"kind": "chatgpt_state", "chat_url": "https://chatgpt.com/c/existing", "chat_exhausted": False, "github_attached": False})
        handoff, _ = route_chat(adapter, {"chat_url": "https://chatgpt.com/c/existing", "chat_exhausted": False}, "inspect the repository bridge", "th3-st0v3/personal-ai-system", "fallback")
        self.assertIn(("attach_github", "th3-st0v3/personal-ai-system"), adapter.calls)
        self.assertIn(("select_reasoning", "thinking"), adapter.calls)
        self.assertTrue(handoff["github_attached"])
        self.assertEqual(handoff["context_source"], "github_app_fallback")

    def test_already_attached_github_context_is_not_duplicated_and_thinking_is_still_enabled(self) -> None:
        adapter = FakeChatAdapter({"kind": "chatgpt_state", "chat_url": "https://chatgpt.com/c/existing", "chat_exhausted": False, "github_attached": True})
        handoff, _ = route_chat(adapter, {"chat_url": "https://chatgpt.com/c/existing", "github_attached": True}, "inspect the repository bridge", "th3-st0v3/personal-ai-system", "fallback")
        self.assertNotIn(("attach_github", "th3-st0v3/personal-ai-system"), adapter.calls)
        self.assertIn(("select_reasoning", "thinking"), adapter.calls)
        self.assertTrue(handoff["github_attached"])

    def test_normal_response_does_not_stage_controller_update(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = root / "automation" / "tampermonkey" / "chatgpt-controller.user.js"
            controller.parent.mkdir(parents=True)
            controller.write_text("// @version      2.4.0\n", encoding="utf-8")
            result = process_controller_update_signal("ordinary answer", root)
            self.assertFalse(result["requested"])
            self.assertFalse((root / ".runtime" / "chatgpt" / "controller-update-request.json").exists())

    def test_explicit_matching_new_version_stages_controller_update(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = root / "automation" / "tampermonkey" / "chatgpt-controller.user.js"
            controller.parent.mkdir(parents=True)
            controller.write_text("// @version      2.4.0\n", encoding="utf-8")
            write_sync_state(root / ".runtime" / "chatgpt" / "controller-sync-state.json", version="2.3.0")
            response = "PASI_CONTROLLER_UPDATE: true\nPASI_CONTROLLER_UPDATE_VERSION: 2.4.0\nPASI_CONTROLLER_UPDATE_REASON: improve response extraction"
            result = process_controller_update_signal(response, root)
            self.assertTrue(result["eligible"])
            request_path = root / ".runtime" / "chatgpt" / "controller-update-request.json"
            self.assertTrue(request_path.exists())
            self.assertEqual(read_last_synced_version(root / ".runtime" / "chatgpt" / "controller-sync-state.json"), "2.3.0")


if __name__ == "__main__":
    unittest.main()
