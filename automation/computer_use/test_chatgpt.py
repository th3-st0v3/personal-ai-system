from __future__ import annotations

import unittest
from typing import Any, Mapping

from automation.computer_use.chatgpt import ChatGPTAdapter, ChatGPTAdapterError
from automation.computer_use.completion import ChatGPTCompletionDetector, completion_from_operation
from automation.computer_use.contracts import Observation


class FakeTransport:
    def __init__(self, responses: list[Mapping[str, Any]]) -> None:
        self.responses = list(responses)
        self.requests: list[tuple[str, str, Mapping[str, Any] | None]] = []

    def request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        self.requests.append((method, path, payload))
        if not self.responses:
            raise AssertionError("unexpected transport request")
        return self.responses.pop(0)


class RepeatingTransport(FakeTransport):
    def __init__(self, response: Mapping[str, Any]) -> None:
        super().__init__([response])
        self.response = response

    def request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
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
        cases = {
            "queued": "generating",
            "claimed": "generating",
            "generating": "generating",
            "failed": "error",
            "cancelled": "interrupted",
        }
        for status, expected in cases.items():
            state, _, _ = completion_from_operation({"status": status})
            self.assertEqual(state, expected)

    def test_completed_without_response_is_complete_but_not_response_available(self) -> None:
        state, text, available = completion_from_operation({"status": "completed"})
        self.assertEqual(state, "complete")
        self.assertEqual(text, "")
        self.assertFalse(available)

    def test_completed_with_verified_response_is_complete_and_available(self) -> None:
        state, text, available = completion_from_operation(
            {"status": "completed", "response_text": "answer", "response_text_available": True}
        )
        self.assertEqual(state, "complete")
        self.assertEqual(text, "answer")
        self.assertTrue(available)

    def test_unknown_status_is_unknown(self) -> None:
        state, _, _ = completion_from_operation({"status": "something-new"})
        self.assertEqual(state, "unknown")

    def test_detector_prefers_operation_error_over_browser_quiet(self) -> None:
        detector = ChatGPTCompletionDetector()
        self.assertEqual(
            detector.detect([observation({"operation": {"status": "failed"}, "browser": {"quiet": True}})]),
            "error",
        )

    def test_detector_maps_browser_evidence_when_operation_is_unavailable(self) -> None:
        detector = ChatGPTCompletionDetector()
        self.assertEqual(detector.detect([observation({"browser": {"generation_active": True}})]), "generating")
        self.assertEqual(detector.detect([observation({"browser": {"quiet": True}})]), "quiet")
        self.assertEqual(detector.detect([observation({"browser": {"interrupted": True}})]), "interrupted")

    def test_detector_never_treats_ambiguous_evidence_as_success(self) -> None:
        detector = ChatGPTCompletionDetector()
        for item in ({}, {"operation": {}}, {"browser": {}}):
            self.assertEqual(detector.detect([observation(item)]), "unknown")


class ChatGPTAdapterTests(unittest.TestCase):
    def test_submit_prompt_queues_prompt_operation(self) -> None:
        transport = FakeTransport([{"operation": {"operation_id": "op-1"}}])
        adapter = ChatGPTAdapter(transport, session_id="session-1")
        self.assertEqual(adapter.submit_prompt("inspect this"), "op-1")
        self.assertEqual(transport.requests[0], ("POST", "/queue", {"operation_type": "prompt", "prompt": "inspect this"}))

    def test_new_session_queues_new_chat_and_requires_verified_completion(self) -> None:
        transport = FakeTransport(
            [
                {"operation": {"operation_id": "op-new"}},
                {"operation": {"operation_id": "op-new", "status": "completed"}},
            ]
        )
        adapter = ChatGPTAdapter(transport, session_id="session-1", poll_interval_seconds=0.001)
        self.assertEqual(adapter.new_session(), "op-new")
        self.assertEqual(transport.requests[0][2], {"operation_type": "new_chat", "prompt": ""})

    def test_reasoning_mode_does_not_fake_capability(self) -> None:
        adapter = ChatGPTAdapter(FakeTransport([]), session_id="session-1")
        with self.assertRaises(ChatGPTAdapterError):
            adapter.select_reasoning_mode("thinking")

    def test_read_response_requires_active_operation(self) -> None:
        adapter = ChatGPTAdapter(FakeTransport([]), session_id="session-1")
        with self.assertRaises(ChatGPTAdapterError):
            adapter.read_response()

    def test_read_operation_scopes_query_parameter(self) -> None:
        transport = FakeTransport([{"operation": {"operation_id": "op/a", "status": "generating"}}])
        adapter = ChatGPTAdapter(transport, session_id="session-1")
        response = adapter.read_operation("op/a")
        self.assertEqual(response.completion, "generating")
        self.assertIn("operation_id=op%2Fa", transport.requests[0][1])

    def test_completed_response_can_be_text_available(self) -> None:
        transport = FakeTransport(
            [
                {"operation": {"operation_id": "op-1", "status": "completed", "response_text": "answer", "response_text_available": True}},
            ]
        )
        adapter = ChatGPTAdapter(transport, session_id="session-1")
        response = adapter.read_operation("op-1")
        self.assertEqual(response.completion, "complete")
        self.assertTrue(response.response_available)
        self.assertEqual(response.text, "answer")

    def test_wait_timeout_is_explicit_timeout(self) -> None:
        transport = RepeatingTransport({"operation": {"operation_id": "op-1", "status": "generating"}})
        adapter = ChatGPTAdapter(transport, session_id="session-1", poll_interval_seconds=0.001, max_wait_seconds=0.001)
        response = adapter.wait_for_completion("op-1")
        self.assertEqual(response.completion, "timeout")
        self.assertGreaterEqual(len(transport.requests), 1)


if __name__ == "__main__":
    unittest.main()
