from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import pasi_chat_guard as guard
from scripts.pasi_chat_guard import classify_observation


class TestPasiChatGuard(unittest.TestCase):
    def test_guard_timeout_cancels_active_bridge_operation(self) -> None:
        health = {"observation": {"data": {"kind": "chatgpt_health", "active_operation_id": "op-123"}}}
        captured = {}

        class FakeResponse:
            def __enter__(self): return self
            def __exit__(self, *_args): return None

        def fake_urlopen(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeResponse()

        with mock.patch.object(guard, "request_json", return_value=health):
            with mock.patch.object(guard, "urlopen", side_effect=fake_urlopen):
                with mock.patch.dict("os.environ", {"PASI_BRIDGE_TOKEN": "test-token"}, clear=True):
                    self.assertTrue(guard.cancel_active_operation("guard timeout"))

        request = captured["request"]
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.full_url, "http://127.0.0.1:8765/chat/cancel")
        self.assertIn(b'"operation_id": "op-123"', request.data)
        self.assertIn(b'"reason": "guard timeout"', request.data)

    def test_default_timeout_matches_native_generation_ceiling(self) -> None:
        self.assertEqual(guard.DEFAULT_TIMEOUT, guard.TIMEOUT_POLICY["python_wait_seconds"])

    def test_request_json_sends_bridge_authorization_header(self) -> None:
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self
            def __exit__(self, *_args):
                return None
            def read(self, _limit):
                return b'{"observation": {}}'

        def fake_urlopen(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeResponse()

        with mock.patch.dict("os.environ", {"PASI_BRIDGE_TOKEN": "test-token"}, clear=True):
            with mock.patch.object(guard, "urlopen", side_effect=fake_urlopen):
                self.assertEqual(guard.request_json("/browser/health"), {"observation": {}})

        request = captured["request"]
        self.assertEqual(request.headers["Authorization"], "Bearer test-token")
        self.assertEqual(captured["timeout"], 3.0)

    def test_provider_usage_limit_is_distinguished_from_context_exhaustion(self) -> None:
        usage = {"observation": {"data": {"kind": "chatgpt_health", "provider_usage_limited": True}}}
        context = {
            "observation": {
                "data": {
                    "kind": "chatgpt_response",
                    "response_text": "This conversation has reached its limit; start a new chat to continue.",
                }
            }
        }
        self.assertEqual(classify_observation(usage), "usage_limit")
        self.assertIsNone(classify_observation(context))

    def test_authentication_challenge_is_terminal(self) -> None:
        payload = {
            "observation": {
                "data": {
                    "kind": "chatgpt_health",
                    "auth_required": True,
                }
            }
        }
        self.assertEqual(classify_observation(payload), "auth_required")

    def test_structured_health_classification_detects_provider_limit_without_text_scanning(self) -> None:
        payload = {
            "observation": {
                "data": {
                    "kind": "chatgpt_health",
                    "provider_usage_limited": True,
                }
            }
        }
        self.assertEqual(classify_observation(payload), "usage_limit")

        text_only = {
            "observation": {
                "data": {
                    "kind": "chatgpt_health",
                    "signals": ["message limit", "try again later"],
                }
            }
        }
        self.assertIsNone(classify_observation(text_only))

    def test_response_text_that_mentions_usage_limit_is_not_a_provider_limit_signal(self) -> None:
        payload = {
            "observation": {
                "data": {
                    "kind": "chatgpt_response",
                    "response_text": "Explain the phrase usage limit reached in general terms.",
                }
            }
        }
        self.assertIsNone(classify_observation(payload))

    def test_unknown_observations_are_not_false_positive_limits(self) -> None:
        self.assertIsNone(classify_observation({"observation": {"data": {"kind": "chatgpt_state", "thinking": True}}}))
        self.assertIsNone(classify_observation(None))

    def test_extract_computer_requests_accepts_bounded_json_lines(self) -> None:
        response = """PASI_COMPUTER_REQUEST_BEGIN
{"request_id":"read-1","capability":"computer.files.read","parameters":{"path":"README.md","max_chars":1000}}
PASI_COMPUTER_REQUEST_END"""
        requests = guard.extract_computer_requests(response)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["capability"], "computer.files.read")

    def test_extract_computer_requests_ignores_oversized_sections(self) -> None:
        response = "PASI_COMPUTER_REQUEST_BEGIN\n" + ("x" * guard.MAX_COMPUTER_REQUEST_BYTES) + "\nPASI_COMPUTER_REQUEST_END"
        self.assertEqual(guard.extract_computer_requests(response), [])

    def test_capability_execution_denies_write_without_touching_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            response = """PASI_COMPUTER_REQUEST_BEGIN
{"request_id":"write","capability":"computer.files.write","parameters":{"path":"note.txt","content":"unsafe"}}
PASI_COMPUTER_REQUEST_END"""
            results = guard.execute_computer_requests(response, root)
            self.assertEqual(results[0]["status"], "denied")
            self.assertFalse((root / "note.txt").exists())

    def test_computer_protocol_describes_only_safe_capabilities(self) -> None:
        prompt = guard.computer_protocol_prompt()
        self.assertIn("computer.files.read", prompt)
        self.assertIn("computer.files.search", prompt)
        self.assertNotIn("computer.files.write", prompt)
        self.assertNotIn("computer.command.execute", prompt)
        self.assertNotIn("computer.credentials.read", prompt)
        self.assertNotIn("computer.financial.execute", prompt)



    def test_guard_requests_status_or_computer_round_completion_markers(self) -> None:
        source = Path("scripts/pasi_chat_guard.py").read_text(encoding="utf-8")
        self.assertIn('"--completion-marker"', source)
        self.assertIn('"PASI_RESULT_STATUS"', source)
        self.assertIn('"PASI_COMPUTER_REQUEST_END"', source)


if __name__ == "__main__":
    unittest.main()
