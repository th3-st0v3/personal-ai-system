from __future__ import annotations

import unittest

from scripts.pasi_chat_guard import classify_observation, observation_text


class TestPasiChatGuard(unittest.TestCase):
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

    def test_text_classification_detects_provider_limit_without_boolean_flags(self) -> None:
        payload = {
            "observation": {
                "data": {
                    "kind": "chatgpt_response",
                    "response_text": "You have reached your message limit. Try again later.",
                }
            }
        }
        self.assertEqual(classify_observation(payload), "usage_limit")
        self.assertIn("message limit", observation_text(payload["observation"]["data"]))

    def test_unknown_observations_are_not_false_positive_limits(self) -> None:
        self.assertIsNone(classify_observation({"observation": {"data": {"kind": "chatgpt_state", "thinking": True}}}))
        self.assertIsNone(classify_observation(None))


if __name__ == "__main__":
    unittest.main()
