from __future__ import annotations

import json
import unittest
from typing import Any, Mapping

from automation.computer_use.review import ReviewError, ReviewRequest, ReviewResult, TransportBackedReviewer


class FakeReviewTransport:
    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str, int]] = []

    def complete(self, provider: str, prompt: str, *, max_output_chars: int) -> Mapping[str, Any]:
        self.calls.append((provider, prompt, max_output_chars))
        return self.payload


class ReviewTests(unittest.TestCase):
    def test_reviewer_must_be_independent(self) -> None:
        transport = FakeReviewTransport({"verdict": "reviewed", "findings": []})
        reviewer = TransportBackedReviewer("chatgpt", transport)
        request = ReviewRequest("Inspect", "chatgpt", "candidate")
        with self.assertRaises(ReviewError):
            reviewer.review(request)

    def test_reviewer_returns_advisory_result_with_provenance(self) -> None:
        transport = FakeReviewTransport(
            {"verdict": "needs-work", "findings": ["Add an independent test."]}
        )
        reviewer = TransportBackedReviewer("claude", transport)
        request = ReviewRequest(
            "Inspect", "chatgpt", "candidate", evidence_fingerprints=("a" * 64,)
        )
        result = reviewer.review(request)
        self.assertEqual(result.reviewer_provider, "claude")
        self.assertEqual(result.evidence_fingerprints, ("a" * 64,))
        self.assertEqual(result.findings, ("Add an independent test.",))
        self.assertEqual(transport.calls[0][0], "claude")

    def test_malformed_reviewer_output_fails_closed(self) -> None:
        reviewer = TransportBackedReviewer("claude", FakeReviewTransport({"findings": []}))
        with self.assertRaises(ReviewError):
            reviewer.review(ReviewRequest("Inspect", "chatgpt", "candidate"))

    def test_candidate_output_is_bounded(self) -> None:
        with self.assertRaises(ReviewError):
            ReviewRequest("Inspect", "chatgpt", "x" * 11, max_output_chars=10)

    def test_prompt_is_bounded(self) -> None:
        transport = FakeReviewTransport({"verdict": "reviewed", "findings": []})
        reviewer = TransportBackedReviewer("claude", transport, max_prompt_chars=100)
        reviewer.review(ReviewRequest("Inspect", "chatgpt", "candidate"))
        self.assertLessEqual(len(transport.calls[0][1]), 100 + len("\n[prompt truncated]"))

    def test_result_fingerprint_is_json_stable(self) -> None:
        result = ReviewResult("claude", "reviewed", ("finding",), ("a" * 64,))
        self.assertEqual(len(result.fingerprint), 64)
        self.assertIsInstance(json.dumps(result.to_dict()), str)


if __name__ == "__main__":
    unittest.main()
