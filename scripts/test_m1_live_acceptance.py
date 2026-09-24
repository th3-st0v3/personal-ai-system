from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.run_m1_live_acceptance import (
    parse_conversation_signature,
    signature_counts,
    validate_signature_progression,
    wait_for_conversation_signature,
    wait_for_signature_progression,
)


class TestM1LiveAcceptance(unittest.TestCase):
    def test_documented_direct_script_invocation_bootstraps_repository_imports(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/run_m1_live_acceptance.py", "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "Run the M1 20-prompt live duplicate-send/false-verdict gate in the current ChatGPT conversation.",
            result.stdout,
        )

    def test_m1_harness_does_not_create_a_new_chat(self) -> None:
        source = Path("scripts/run_m1_live_acceptance.py").read_text(encoding="utf-8")
        self.assertNotIn("adapter.new_session()", source)

    def test_fresh_empty_conversation_signature_is_valid(self) -> None:
        self.assertEqual(parse_conversation_signature("0:0:"), (0, 0, ""))

    def test_nonempty_conversation_requires_assistant_fingerprint(self) -> None:
        self.assertIsNone(parse_conversation_signature("3:4:"))

    def test_wait_for_conversation_signature_retries_until_state_is_published(self) -> None:
        class FakeAdapter:
            def __init__(self) -> None:
                self.states = [
                    {
                        "kind": "chatgpt_health",
                        "chat_url": "https://chatgpt.com/c/fresh",
                        "conversation_signature": None,
                    },
                    {
                        "kind": "chatgpt_state",
                        "chat_url": "https://chatgpt.com/c/fresh",
                        "conversation_signature": "0:0:",
                    },
                ]

            def read_browser_state(self) -> dict[str, object]:
                state = self.states.pop(0)
                return {"data": state}

        state, signature = wait_for_conversation_signature(
            FakeAdapter(), "https://chatgpt.com/c/fresh", timeout_seconds=0.1, poll_seconds=0
        )
        self.assertEqual(state["kind"], "chatgpt_state")
        self.assertEqual(signature, "0:0:")

    def test_wait_for_signature_progression_retries_stale_state(self) -> None:
        class FakeAdapter:
            def __init__(self) -> None:
                self.states = [
                    {
                        "kind": "chatgpt_state",
                        "chat_url": "https://chatgpt.com/c/live",
                        "conversation_signature": "4:5:previous",
                    },
                    {
                        "kind": "chatgpt_state",
                        "chat_url": "https://chatgpt.com/c/live",
                        "conversation_signature": "5:6:current",
                    },
                ]

            def read_browser_state(self) -> dict[str, object]:
                return {"data": self.states.pop(0)}

        state, signature = wait_for_signature_progression(
            FakeAdapter(),
            "https://chatgpt.com/c/live",
            "4:5:previous",
            1,
            timeout_seconds=0.1,
            poll_seconds=0,
        )
        self.assertEqual(state["chat_url"], "https://chatgpt.com/c/live")
        self.assertEqual(signature, "5:6:current")

    def test_parse_conversation_signature_requires_counts_and_fingerprint(self) -> None:
        self.assertEqual(
            parse_conversation_signature("3:4:assistant response"),
            (3, 4, "assistant response"),
        )
        self.assertEqual(signature_counts("3:4:assistant response"), (3, 4))
        self.assertIsNone(parse_conversation_signature("3:4:"))
        self.assertIsNone(parse_conversation_signature("3:assistant:response"))
        self.assertIsNone(parse_conversation_signature("invalid"))

    def test_validate_signature_progression_accepts_exact_next_message_pair(self) -> None:
        self.assertEqual(
            validate_signature_progression(
                "3:4:first assistant response",
                "4:5:second assistant response",
                1,
            ),
            (4, 5),
        )

    def test_validate_signature_progression_rejects_duplicate_or_skipped_messages(self) -> None:
        with self.assertRaisesRegex(
            RuntimeError, "expected exact conversation-signature count progression"
        ):
            validate_signature_progression(
                "3:4:first assistant response",
                "5:6:duplicate submission evidence",
                2,
            )

    def test_validate_signature_progression_rejects_unchanged_assistant_fingerprint(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "fingerprint did not change"):
            validate_signature_progression(
                "3:4:same response",
                "4:5:same response",
                3,
            )

    def test_validate_signature_progression_rejects_malformed_signatures(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "invalid previous conversation_signature"):
            validate_signature_progression("", "1:1:response", 1)
        with self.assertRaisesRegex(RuntimeError, "invalid conversation_signature"):
            validate_signature_progression("0:0:baseline", "1:1:", 1)


if __name__ == "__main__":
    unittest.main()
