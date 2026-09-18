from __future__ import annotations

import unittest
from typing import Any, Mapping

from automation.computer_use.chatgpt import ChatGPTAdapter, ChatGPTAdapterError, UrllibBridgeTransport
from automation.computer_use.completion import ChatGPTCompletionDetector, completion_from_operation
from automation.computer_use.contracts import Observation


class FakeTransport:
    def __init__(self, responses: list[Mapping[str, Any]]) -> None:
        self.responses = list(responses)
        self.requests: list[tuple[str, str, Mapping[str, Any] | None]] = []

    def request(self, method: str, path: str, payload: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        self.requests.append((method, path, payload))
        if not self.responses:
            raise AssertionError("unexpected transport request")
        return self.responses.pop(0)


class RepeatingTransport(FakeTransport):
    def __init__(self, response: Mapping[str, Any]) -> None:
        super().__init__([response])
        self.response = response

    def request(self, method: str, path: str, payload: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        self.requests.append((method, path, payload))
        return self.response


def observation(data: Mapping[str, Any]) -> Observation:
    return Observation(
        observation_id="test-observation",
        session_id="session-1",
        source="test",
        kind="completion",
        data=data,
    )


class CompletionTests(unittest.TestCase):
    def test_all_known_operation_states_are_explicit(self) -> None:
        cases = {"queued": "generating", "claimed": "generating", "generating": "generating", "failed": "error", "cancelled": "interrupted"}
        for status, expected in cases.items():
            state, _, _ = completion_from_operation({"status": status})
            self.assertEqual(state, expected)

    def test_completed_without_response_is_complete_but_not_response_available(self) -> None:
        state, text, available = completion_from_operation({"status": "completed"})
        self.assertEqual(state, "complete")
        self.assertEqual(text, "")
        self.assertFalse(available)

    def test_completed_with_verified_response_is_complete_and_available(self) -> None:
        state, text, available = completion_from_operation({"status": "completed", "response_text": "answer", "response_text_available": True})
        self.assertEqual(state, "complete")
        self.assertEqual(text, "answer")
        self.assertTrue(available)

    def test_unknown_status_is_unknown(self) -> None:
        state, _, _ = completion_from_operation({"status": "something-new"})
        self.assertEqual(state, "unknown")

    def test_detector_prefers_operation_error_over_browser_quiet(self) -> None:
        detector = ChatGPTCompletionDetector()
        self.assertEqual(detector.detect([observation({"operation": {"status": "failed"}, "browser": {"quiet": True}})]), "error")

    def test_detector_maps_browser_evidence_when_operation_is_unavailable(self) -> None:
        detector = ChatGPTCompletionDetector()
        self.assertEqual(detector.detect([observation({"browser": {"generation_active": True}})]), "generating")
        self.assertEqual(detector.detect([observation({"browser": {"quiet": True}})]), "quiet")
        self.assertEqual(detector.detect([observation({"browser": {"interrupted": True}})]), "interrupted")

    def test_detector_never_treats_ambiguous_evidence_as_success(self) -> None:
        detector = ChatGPTCompletionDetector()
        for item in ({}, {"operation": {}}, {"browser": {}}):
            self.assertEqual(detector.detect([observation(item)]), "unknown")


class BridgeTransportTests(unittest.TestCase):
    def test_accepts_expected_localhost_url(self) -> None:
        self.assertEqual(UrllibBridgeTransport("http://127.0.0.1:8765").base_url, "http://127.0.0.1:8765")

    def test_rejects_non_localhost_host_even_when_prefix_matches(self) -> None:
        with self.assertRaises(ValueError):
            UrllibBridgeTransport("http://127.0.0.1:8765@example.com:80")

    def test_rejects_credentials(self) -> None:
        with self.assertRaises(ValueError):
            UrllibBridgeTransport("http://user:pass@127.0.0.1:8765")

    def test_rejects_non_http_scheme(self) -> None:
        with self.assertRaises(ValueError):
            UrllibBridgeTransport("https://127.0.0.1:8765")


class ChatGPTAdapterTests(unittest.TestCase):
    def test_submit_prompt_queues_prompt_operation(self) -> None:
        transport = FakeTransport([{"operation": {"operation_id": "op-1"}}])
        adapter = ChatGPTAdapter(transport, session_id="session-1")
        self.assertEqual(adapter.submit_prompt("inspect this"), "op-1")
        self.assertEqual(transport.requests[0], ("POST", "/queue", {"operation_type": "prompt", "prompt": "inspect this"}))

    def test_new_session_queues_new_chat_and_requires_verified_completion(self) -> None:
        transport = FakeTransport([{"operation": {"operation_id": "op-new"}}, {"operation": {"operation_id": "op-new", "status": "completed"}}])
        adapter = ChatGPTAdapter(transport, session_id="session-1", poll_interval_seconds=0.001)
        self.assertEqual(adapter.new_session(), "op-new")
        self.assertEqual(transport.requests[0][2], {"operation_type": "new_chat", "prompt": ""})

    def test_attach_github_repository_queues_semantic_attachment_operation(self) -> None:
        transport = FakeTransport([{"operation": {"operation_id": "op-github"}}, {"operation": {"operation_id": "op-github", "status": "completed"}}])
        adapter = ChatGPTAdapter(transport, session_id="session-1", poll_interval_seconds=0.001)
        self.assertEqual(adapter.attach_github_repository("th3-st0v3/personal-ai-system"), "op-github")
        self.assertEqual(transport.requests[0][2], {"operation_type": "attach_github", "prompt": "th3-st0v3/personal-ai-system"})

    def test_attach_github_repository_rejects_invalid_repository(self) -> None:
        with self.assertRaises(ValueError):
            ChatGPTAdapter(FakeTransport([]), session_id="session-1").attach_github_repository("personal-ai-system")

    def test_select_reasoning_mode_queues_semantic_selection(self) -> None:
        transport = FakeTransport([{"operation": {"operation_id": "op-thinking"}}, {"operation": {"operation_id": "op-thinking", "status": "completed"}}])
        ChatGPTAdapter(transport, session_id="session-1", poll_interval_seconds=0.001).select_reasoning_mode("thinking")
        self.assertEqual(transport.requests[0][2], {"operation_type": "select_reasoning", "prompt": "thinking"})

    def test_read_response_requires_active_operation(self) -> None:
        with self.assertRaises(ChatGPTAdapterError):
            ChatGPTAdapter(FakeTransport([]), session_id="session-1").read_response()

    def test_read_operation_scopes_query_parameter(self) -> None:
        transport = FakeTransport([{"operation": {"operation_id": "op/a", "status": "generating"}}])
        response = ChatGPTAdapter(transport, session_id="session-1").read_operation("op/a")
        self.assertEqual(response.completion, "generating")
        self.assertIn("operation_id=op%2Fa", transport.requests[0][1])

    def test_completed_response_can_be_text_available(self) -> None:
        transport = FakeTransport([{"operation": {"operation_id": "op-1", "status": "completed", "response_text": "answer", "response_text_available": True}}])
        response = ChatGPTAdapter(transport, session_id="session-1").read_operation("op-1")
        self.assertEqual(response.completion, "complete")
        self.assertTrue(response.response_available)
        self.assertEqual(response.text, "answer")

    def test_completed_prompt_consumes_live_browser_response(self) -> None:
        transport = FakeTransport([
            {"operation": {"operation_id": "op-1", "operation_type": "prompt", "status": "completed", "chat_url": "https://chatgpt.com/c/abc"}},
            {"observation": {"data": {"kind": "chatgpt_response", "chat_url": "https://chatgpt.com/c/abc", "response_text": "live answer", "response_text_available": True}}},
            {"observation": {"data": {"kind": "chatgpt_state", "chat_url": "https://chatgpt.com/c/abc", "chat_exhausted": False}}},
        ])
        response = ChatGPTAdapter(transport, session_id="session-1").read_operation("op-1")
        self.assertTrue(response.response_available)
        self.assertEqual(response.text, "live answer")
        self.assertEqual(response.chat_url, "https://chatgpt.com/c/abc")
        self.assertFalse(response.chat_exhausted)

    def test_failed_prompt_exposes_chat_exhaustion(self) -> None:
        transport = FakeTransport([{"operation": {"operation_id": "op-1", "operation_type": "prompt", "status": "failed", "error": "CHAT_EXHAUSTED: usage limit"}}])
        response = ChatGPTAdapter(transport, session_id="session-1").read_operation("op-1")
        self.assertEqual(response.completion, "error")
        self.assertTrue(response.chat_exhausted)
        self.assertEqual(response.error, "CHAT_EXHAUSTED: usage limit")

    def test_timeout_recovers_operation_bound_browser_response(self) -> None:
        transport = FakeTransport([
            {"operation": {"operation_id": "op-late", "status": "generating"}},
            {"observation": {"data": {
                "kind": "chatgpt_response",
                "active_operation_id": "op-late",
                "chat_url": "https://chatgpt.com/c/late",
                "response_text": "late response",
                "response_text_available": True,
                "chat_exhausted": False,
            }}},
        ])
        adapter = ChatGPTAdapter(transport, session_id="session-1", poll_interval_seconds=0.001, max_wait_seconds=0.001)
        response = adapter.wait_for_completion("op-late")
        self.assertEqual(response.completion, "complete")
        self.assertTrue(response.response_available)
        self.assertEqual(response.text, "late response")
        self.assertEqual(response.chat_url, "https://chatgpt.com/c/late")

    def test_timeout_rejects_unbound_browser_response(self) -> None:
        transport = FakeTransport([
            {"operation": {"operation_id": "op-late", "status": "generating"}},
            {"observation": {"data": {
                "kind": "chatgpt_response",
                "active_operation_id": "different-operation",
                "response_text": "stale response",
                "response_text_available": True,
            }}},
        ])
        adapter = ChatGPTAdapter(transport, session_id="session-1", poll_interval_seconds=0.001, max_wait_seconds=0.001)
        response = adapter.wait_for_completion("op-late")
        self.assertEqual(response.completion, "timeout")
        self.assertFalse(response.response_available)

    def test_wait_timeout_is_explicit_timeout(self) -> None:
        transport = RepeatingTransport({"operation": {"operation_id": "op-1", "status": "generating"}})
        response = ChatGPTAdapter(transport, session_id="session-1", poll_interval_seconds=0.001, max_wait_seconds=0.001).wait_for_completion("op-1")
        self.assertEqual(response.completion, "timeout")
        self.assertGreaterEqual(len(transport.requests), 1)


if __name__ == "__main__":
    unittest.main()
