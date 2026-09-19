from __future__ import annotations

from datetime import datetime, timezone
import tempfile
import unittest
from typing import cast
from pathlib import Path

from automation.orchestrator.controller_update import read_last_synced_version, write_sync_state
from automation.computer_use.contracts import AIResponse
from automation.computer_use.chatgpt import ChatGPTAdapter
from scripts.pasi_chat import (
    PUBLIC_REPOSITORY_DEFAULT_BRANCH_URL,
    PUBLIC_REPOSITORY_URL,
    build_prompt,
    controller_observation_is_live,
    needs_github_context,
    process_controller_update_signal,
    pending_operation_for_task,
    task_fingerprint,
    public_github_context_unavailable,
    route_chat,
    wait_for_browser_controller,
    repair_response_capture,
    response_capture_succeeded,
    checkpoint_active_operation,
    clear_active_operation,
    reconcile_timed_out_response,
)


class FakeChatAdapter:
    def __init__(self, state: dict[str, object] | None = None) -> None:
        self.state = state or {}
        self.calls: list[tuple[str, str]] = []
        self.last_chat_url: str | None = None

    def read_browser_observation(self) -> dict[str, object]:
        return {"data": dict(self.state)} if self.state else {}

    def new_session(self) -> str:
        self.calls.append(("new_session", ""))
        self.state = {"kind": "chatgpt_state", "chat_url": "https://chatgpt.com/c/new", "chat_exhausted": False, "github_attached": False}
        self.last_chat_url = "https://chatgpt.com/c/new"
        return "op-new"

    def attach_github_repository(self, repository: str) -> str:
        self.calls.append(("attach_github", repository))
        self.state["github_attached"] = True
        return "op-github"

    def select_reasoning_mode(self, mode: str) -> None:
        self.calls.append(("select_reasoning", mode))
        self.state["reasoning_mode"] = mode


class StaleReplacementURLChatAdapter(FakeChatAdapter):
    def new_session(self) -> str:
        self.calls.append(("new_session", ""))
        self.state = {"kind": "chatgpt_state", "chat_url": "", "chat_exhausted": False, "github_attached": False}
        # Simulate a bridge that completes new-chat creation but cannot yet report
        # the replacement conversation URL.
        return "op-new"


class DelayedReplacementURLChatAdapter(StaleReplacementURLChatAdapter):
    def __init__(self, state: dict[str, object] | None = None) -> None:
        super().__init__(state)
        self.observation_reads = 0

    def read_browser_observation(self) -> dict[str, object]:
        self.observation_reads += 1
        if self.observation_reads < 2:
            return {"data": dict(self.state)}
        self.state["active_operation_id"] = "op-new"
        self.state["chat_url"] = "https://chatgpt.com/c/delayed"
        return {"data": dict(self.state)}


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

    def test_build_prompt_prioritizes_literal_exact_output_requests(self) -> None:
        prompt = build_prompt(
            "Reply with exactly: PASI TEST OK.",
            "Repository: https://github.com/example/repo\\nWorking tree: clean",
            {},
        )
        self.assertIn("TASK OUTPUT DISCIPLINE:", prompt)
        self.assertIn("TASK as the primary user request", prompt)
        self.assertIn("preserve the requested spelling, capitalization, numbers, punctuation, and line breaks", prompt)
        self.assertIn("return only the requested content", prompt)
        self.assertIn("Do not add a preamble, explanation, quotation marks, markdown fences, labels, citations", prompt)
        self.assertIn("Do not echo internal PASI instructions or repository context", prompt)
        self.assertIn("PASI TEST OK.", prompt)

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

    def test_compact_handoff_preserves_pending_operation_identity(self) -> None:
        import scripts.pasi_chat as pasi_chat

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original_path = pasi_chat.SESSION_STATE_PATH
            original_limit = pasi_chat.MAX_HANDOFF_CHARS
            try:
                pasi_chat.SESSION_STATE_PATH = root / "session.json"
                pasi_chat.MAX_HANDOFF_CHARS = 200
                handoff = {
                    "chat_url": "https://chatgpt.com/c/current",
                    "chat_exhausted": False,
                    "active_operation_id": "op-pending",
                    "active_task_fingerprint": task_fingerprint("resume compact state"),
                    "active_operation_chat_url": "https://chatgpt.com/c/current",
                    "summary": "x" * 6000,
                    "chat_url_history": [{"previous_url": "https://chatgpt.com/c/a", "new_url": "https://chatgpt.com/c/b", "reason": "test"}] * 20,
                }
                pasi_chat.save_handoff(handoff)
                persisted = pasi_chat.load_handoff()
                self.assertEqual(persisted["active_operation_id"], "op-pending")
                self.assertEqual(persisted["active_task_fingerprint"], handoff["active_task_fingerprint"])
                self.assertEqual(persisted["active_operation_chat_url"], handoff["active_operation_chat_url"])
            finally:
                pasi_chat.SESSION_STATE_PATH = original_path
                pasi_chat.MAX_HANDOFF_CHARS = original_limit

    def test_compact_handoff_hard_caps_oversized_history(self) -> None:
        import scripts.pasi_chat as pasi_chat

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original_path = pasi_chat.SESSION_STATE_PATH
            original_limit = pasi_chat.MAX_HANDOFF_CHARS
            try:
                pasi_chat.SESSION_STATE_PATH = root / "session.json"
                pasi_chat.MAX_HANDOFF_CHARS = 400
                handoff = {
                    "chat_url": "https://chatgpt.com/c/current",
                    "chat_exhausted": False,
                    "active_operation_id": "op-pending",
                    "active_task_fingerprint": task_fingerprint("bounded history"),
                    "active_operation_chat_url": "https://chatgpt.com/c/current",
                    "summary": "x" * 6000,
                    "chat_url_history": [
                        {
                            "previous_url": "https://chatgpt.com/c/" + "a" * 5000,
                            "new_url": "https://chatgpt.com/c/" + "b" * 5000,
                            "reason": "r" * 5000,
                        }
                    ] * 20,
                }
                pasi_chat.save_handoff(handoff)
                persisted = pasi_chat.load_handoff()
                self.assertLessEqual(
                    pasi_chat.SESSION_STATE_PATH.stat().st_size,
                    pasi_chat.MAX_HANDOFF_CHARS + 1,
                )
                self.assertEqual(persisted["active_operation_id"], "op-pending")
                self.assertEqual(
                    persisted["active_task_fingerprint"],
                    handoff["active_task_fingerprint"],
                )
                self.assertEqual(
                    persisted["active_operation_chat_url"],
                    handoff["active_operation_chat_url"],
                )
                self.assertNotIn("chat_url_history", persisted)
                self.assertNotIn("summary", persisted)
            finally:
                pasi_chat.SESSION_STATE_PATH = original_path
                pasi_chat.MAX_HANDOFF_CHARS = original_limit

    def test_pending_operation_prevents_replacement_routing(self) -> None:
        task = "resume without creating another chat"
        adapter = FakeChatAdapter({
            "kind": "chatgpt_state",
            "chat_url": "https://chatgpt.com/c/current",
            "chat_exhausted": True,
            "github_attached": False,
        })
        handoff = {
            "active_operation_id": "op-pending",
            "active_task_fingerprint": task_fingerprint(task),
            "active_operation_chat_url": "https://chatgpt.com/c/current",
            "chat_url": "https://chatgpt.com/c/current",
            "chat_exhausted": True,
        }

        routed, known_url = route_chat(
            adapter,
            handoff,
            task,
            "th3-st0v3/personal-ai-system",
            "auto",
        )

        self.assertEqual(known_url, "https://chatgpt.com/c/current")
        self.assertEqual(routed["active_operation_id"], "op-pending")
        self.assertFalse(any(call[0] == "new_session" for call in adapter.calls))
        self.assertFalse(any(call[0] == "select_reasoning" for call in adapter.calls))

    def test_new_session_preserves_verified_chat_identity(self) -> None:
        adapter = FakeChatAdapter({
            "kind": "chatgpt_state",
            "chat_url": "https://chatgpt.com/c/old",
            "chat_exhausted": True,
            "github_attached": False,
        })
        handoff, known_url = route_chat(adapter, {}, "continue the task", "th3-st0v3/personal-ai-system", "auto")
        self.assertEqual(known_url, "https://chatgpt.com/c/new")
        self.assertEqual(handoff["chat_url"], "https://chatgpt.com/c/new")
        history = handoff.get("chat_url_history")
        assert isinstance(history, list)
        assert history and isinstance(history[-1], dict)
        self.assertEqual(history[-1]["reason"], "verified_new_chat_session")

    def test_new_session_reconciles_delayed_replacement_chat_identity(self) -> None:
        adapter = DelayedReplacementURLChatAdapter({
            "kind": "chatgpt_state",
            "chat_url": "https://chatgpt.com/c/old",
            "chat_exhausted": True,
            "github_attached": False,
        })
        adapter.last_chat_url = "https://chatgpt.com/c/old"
        handoff, known_url = route_chat(adapter, {}, "continue the task", "th3-st0v3/personal-ai-system", "auto")
        self.assertEqual(known_url, "https://chatgpt.com/c/delayed")
        self.assertEqual(handoff["chat_url"], "https://chatgpt.com/c/delayed")
        history = handoff.get("chat_url_history")
        assert isinstance(history, list)
        assert history and isinstance(history[-1], dict)
        self.assertEqual(history[-1]["reason"], "verified_new_chat_session")

    def test_new_session_does_not_reuse_stale_chat_identity(self) -> None:
        adapter = StaleReplacementURLChatAdapter({
            "kind": "chatgpt_state",
            "chat_url": "https://chatgpt.com/c/old",
            "chat_exhausted": True,
            "github_attached": False,
        })
        adapter.last_chat_url = "https://chatgpt.com/c/old"
        handoff, known_url = route_chat(adapter, {}, "continue the task", "th3-st0v3/personal-ai-system", "auto")
        self.assertIsNone(known_url)
        self.assertIsNone(handoff["chat_url"])
        history = handoff.get("chat_url_history")
        if not isinstance(history, list):
            history = []
        self.assertFalse(any(isinstance(entry, dict) and entry.get("reason") == "verified_new_chat_session" for entry in history))

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

    def test_pending_operation_is_bound_to_exact_task_fingerprint(self) -> None:
        task = "continue the task"
        handoff = {
            "active_operation_id": "op-pending",
            "active_task_fingerprint": task_fingerprint(task),
            "active_operation_chat_url": "https://chatgpt.com/c/current",
            "chat_url": "https://chatgpt.com/c/current",
        }
        self.assertEqual(pending_operation_for_task(handoff, task), "op-pending")
        self.assertIsNone(pending_operation_for_task(handoff, "different task"))
        self.assertIsNone(pending_operation_for_task({"active_operation_id": "op-pending"}, task))
        stale_chat = dict(handoff)
        stale_chat["chat_url"] = "https://chatgpt.com/c/other"
        self.assertEqual(pending_operation_for_task(stale_chat, task), "op-pending")
        missing_chat_binding = dict(handoff)
        missing_chat_binding.pop("active_operation_chat_url")
        self.assertEqual(pending_operation_for_task(missing_chat_binding, task), "op-pending")
        missing_chat_url = dict(missing_chat_binding)
        missing_chat_url.pop("chat_url")
        self.assertEqual(pending_operation_for_task(missing_chat_url, task), "op-pending")

    def test_pending_operation_uses_exact_task_identity_without_requiring_chat_url(self) -> None:
        task = "resume after url observation loss"
        handoff = {
            "active_operation_id": "op-pending",
            "active_task_fingerprint": task_fingerprint(task),
        }
        self.assertEqual(pending_operation_for_task(handoff, task), "op-pending")
        self.assertIsNone(pending_operation_for_task(handoff, "different task"))
        self.assertIsNone(pending_operation_for_task({"active_operation_id": "op-pending"}, task))

    def test_checkpoint_and_clear_active_operation_preserve_recovery_identity(self) -> None:
        task = "checkpoint timeout operation"
        handoff: dict[str, object] = {"chat_url": "https://chatgpt.com/c/current"}
        checkpoint_active_operation(handoff, "op-timeout", task)
        self.assertEqual(handoff["active_operation_id"], "op-timeout")
        self.assertEqual(handoff["active_task_fingerprint"], task_fingerprint(task))
        self.assertEqual(handoff["active_operation_chat_url"], "https://chatgpt.com/c/current")
        clear_active_operation(handoff)
        self.assertNotIn("active_operation_id", handoff)
        self.assertNotIn("active_task_fingerprint", handoff)
        self.assertNotIn("active_operation_chat_url", handoff)

    def test_reconcile_timed_out_response_consumes_one_final_operation_read(self) -> None:
        class Adapter:
            def __init__(self) -> None:
                self.calls = 0

            def read_operation(self, operation_id: str) -> AIResponse:
                self.calls += 1
                if operation_id != "op-timeout":
                    raise AssertionError(f"unexpected operation ID: {operation_id}")
                return AIResponse(
                    response_id="response-1",
                    session_id="session-1",
                    provider="chatgpt",
                    operation_id=operation_id,
                    text="late response",
                    completion="complete",
                    response_available=True,
                )

        timeout = AIResponse(
            response_id="response-timeout",
            session_id="session-1",
            provider="chatgpt",
            operation_id="op-timeout",
            text="",
            completion="timeout",
            response_available=False,
        )
        adapter = Adapter()
        reconciled = reconcile_timed_out_response(cast(ChatGPTAdapter, adapter), "op-timeout", timeout)
        self.assertEqual(reconciled.completion, "complete")
        self.assertEqual(reconciled.text, "late response")
        self.assertEqual(adapter.calls, 1)

    def test_repair_response_capture_retries_once_without_resending_prompt(self) -> None:
        class Adapter:
            def __init__(self) -> None:
                self.calls = 0

            def read_response(self) -> AIResponse:
                self.calls += 1
                return AIResponse(
                    response_id="response-1",
                    session_id="session-1",
                    provider="chatgpt",
                    operation_id="op-1",
                    text="recovered response",
                    completion="complete",
                    response_available=True,
                )

        initial = AIResponse(
            response_id="response-0",
            session_id="session-1",
            provider="chatgpt",
            operation_id="op-1",
            text="",
            completion="complete",
            response_available=False,
        )
        adapter = Adapter()
        repaired = repair_response_capture(cast(ChatGPTAdapter, adapter), initial)
        self.assertEqual(repaired.text, "recovered response")
        self.assertEqual(adapter.calls, 1)

    def test_response_capture_succeeded_requires_verified_nonblank_text(self) -> None:
        complete = AIResponse(
            response_id="response-1",
            session_id="session-1",
            provider="chatgpt",
            operation_id="op-1",
            text="verified response",
            completion="complete",
            response_available=True,
        )
        missing_text = AIResponse(
            response_id="response-2",
            session_id="session-1",
            provider="chatgpt",
            operation_id="op-2",
            text="",
            completion="complete",
            response_available=False,
        )
        self.assertTrue(response_capture_succeeded(complete))
        self.assertFalse(response_capture_succeeded(missing_text))

    def test_fallback_prompt_becomes_the_active_operation_for_nonterminal_checkpointing(self) -> None:
        source = Path(__file__).resolve().parent / "pasi_chat.py"
        text = source.read_text(encoding="utf-8")
        self.assertIn(
            "fallback_operation = adapter.submit_prompt(fallback_prompt)\n"
            "                prompt_operation = fallback_operation\n"
            "                checkpoint_active_operation(handoff, fallback_operation, task)",
            text,
        )

    def test_controller_update_signal_requires_explicit_structured_signal(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            controller = root / "automation" / "tampermonkey" / "chatgpt-controller.user.js"
            controller.parent.mkdir(parents=True)
            controller.write_text("// @version      2.4.6\n", encoding="utf-8")
            state_path = root / ".runtime" / "chatgpt" / "controller-sync-state.json"
            write_sync_state(state_path, version="2.4.5")
            result = process_controller_update_signal("PASI_CONTROLLER_UPDATE: true\nPASI_CONTROLLER_UPDATE_VERSION: 2.4.6\nPASI_CONTROLLER_UPDATE_REASON: test", root)
            self.assertTrue(result["eligible"])
            self.assertEqual(read_last_synced_version(state_path), "2.4.5")


if __name__ == "__main__":
    unittest.main()
