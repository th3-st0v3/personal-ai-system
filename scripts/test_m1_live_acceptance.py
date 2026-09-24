from __future__ import annotations

import unittest

from scripts.run_m1_live_acceptance import (
    parse_conversation_signature,
    signature_counts,
    validate_signature_progression,
)


class TestM1LiveAcceptance(unittest.TestCase):
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
        with self.assertRaisesRegex(RuntimeError, "expected exact conversation-signature count progression"):
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
