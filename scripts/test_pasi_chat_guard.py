from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from scripts import pasi_chat_guard as guard
from scripts.pasi_chat_guard import classify_observation, observation_text


class TestPasiChatGuard(unittest.TestCase):
    def test_guard_monitor_has_a_short_health_request_timeout(self) -> None:
        source = Path(guard.__file__).read_text(encoding="utf-8")
        self.assertIn("HEALTH_MONITOR_REQUEST_TIMEOUT_SECONDS = 0.25", source)
        self.assertIn("timeout=HEALTH_MONITOR_REQUEST_TIMEOUT_SECONDS", source)
        self.assertIn("monitor.join(timeout=HEALTH_MONITOR_REQUEST_TIMEOUT_SECONDS + 0.1)", source)

    def test_guard_does_not_classify_completed_child_from_late_health_observation(self) -> None:
        source = Path(guard.__file__).read_text(encoding="utf-8")
        request_pos = source.index('observed = classify_observation(request_json("/browser/observation"))')
        post_request_poll_pos = source.index("if process.poll() is not None:", request_pos)
        observed_limit_pos = source.index('if observed in {"usage_limit", "auth_required"}:', request_pos)
        self.assertLess(request_pos, post_request_poll_pos)
        self.assertLess(post_request_poll_pos, observed_limit_pos)

    def test_guard_waits_for_child_exit_without_polling_for_process_completion(self) -> None:
        source = Path(guard.__file__).read_text(encoding="utf-8")
        self.assertIn("process.wait(timeout=timeout)", source)
        self.assertIn("monitor_browser_state", source)
        self.assertIn("monitor_stop.wait(bridge_poll_seconds)", source)
        self.assertNotIn("time.sleep(bridge_poll_seconds)", source)

    def test_guard_timeout_cancels_active_bridge_operation(self) -> None:
        source = Path(guard.__file__).read_text(encoding="utf-8")
        self.assertIn("def cancel_active_operation(reason: str)", source)
        self.assertIn('request_json("/browser/health")', source)
        self.assertIn("chat/cancel", source)
        self.assertIn('cancel_active_operation("guard timeout before child termination")', source)

    def test_fallback_sandbox_scrubs_sensitive_environment(self) -> None:
        source = Path("scripts/pasi_provider_router.py").read_text(encoding="utf-8")
        for secret_name in (
            "PASI_BRIDGE_TOKEN",
            "GITHUB_TOKEN",
            "GH_TOKEN",
            "OPENROUTER_API_KEY",
            "PERPLEXITY_API_KEY",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "GOOGLE_API_KEY",
            "GEMINI_API_KEY",
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
            "SSH_AUTH_SOCK",
        ):
            self.assertIn(f'"{secret_name}"', source)

    def test_guard_uses_immutable_launcher_control_script_and_explicit_target_repo(self) -> None:
        source = Path(guard.__file__).read_text(encoding="utf-8")
        self.assertIn('str(REPO_ROOT / "scripts" / "pasi_chat.py")', source)
        self.assertIn('"--repo",\n            str(repo_root)', source)
        self.assertIn('parser.add_argument("--repo"', source)
        self.assertIn("repo_root = args.repo.expanduser().resolve()", source)
        self.assertIn("execute_computer_requests(response, repo_root)", source)

    def test_default_timeout_matches_native_generation_ceiling(self) -> None:
        self.assertEqual(guard.DEFAULT_TIMEOUT, 60 * 60)

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

    def test_typed_health_text_classification_detects_provider_limit_without_boolean_flags(self) -> None:
        payload = {
            "observation": {
                "data": {
                    "kind": "chatgpt_health",
                    "signals": ["message limit", "try again later"],
                }
            }
        }
        self.assertEqual(classify_observation(payload), "usage_limit")
        self.assertIn("message limit", observation_text(payload["observation"]["data"]))

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


if __name__ == "__main__":
    unittest.main()
