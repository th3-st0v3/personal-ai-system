import unittest

from evaluation import evaluate_evidence


def evidence_with_status(status):
    return (
        1,
        1,
        "test_source",
        None,
        "test result",
        status,
    )


class TestEvidenceEvaluation(unittest.TestCase):

    def test_no_evidence_is_unverified(self):
        evaluation = evaluate_evidence([])

        self.assertEqual(
            evaluation["recommendation"],
            "Unverified",
        )
        self.assertEqual(evaluation["signals"], [])
        self.assertFalse(evaluation["conflict"])

    def test_verified_evidence_recommends_verified(self):
        evaluation = evaluate_evidence([
            evidence_with_status("Verified"),
        ])

        self.assertEqual(
            evaluation["recommendation"],
            "Verified",
        )
        self.assertEqual(
            evaluation["signals"],
            ["Verified"],
        )
        self.assertFalse(evaluation["conflict"])

    def test_failed_evidence_recommends_failed(self):
        evaluation = evaluate_evidence([
            evidence_with_status("Failed"),
        ])

        self.assertEqual(
            evaluation["recommendation"],
            "Failed",
        )
        self.assertFalse(evaluation["conflict"])

    def test_at_risk_evidence_recommends_at_risk(self):
        evaluation = evaluate_evidence([
            evidence_with_status("At risk"),
        ])

        self.assertEqual(
            evaluation["recommendation"],
            "At risk",
        )
        self.assertFalse(evaluation["conflict"])


    def test_duplicate_statuses_produce_unique_signals(self):
        evaluation = evaluate_evidence([
            evidence_with_status("Verified"),
            evidence_with_status("Verified"),
        ])

        self.assertEqual(
            evaluation["recommendation"],
            "Verified",
        )
        self.assertEqual(
            evaluation["signals"],
            ["Verified"],
        )
        self.assertFalse(evaluation["conflict"])


    def test_verified_and_failed_evidence_is_conflicting(self):
        evaluation = evaluate_evidence([
            evidence_with_status("Verified"),
            evidence_with_status("Failed"),
        ])

        self.assertEqual(
            evaluation["recommendation"],
            "At risk",
        )
        self.assertEqual(
            evaluation["signals"],
            ["Failed", "Verified"],
        )
        self.assertTrue(evaluation["conflict"])


if __name__ == "__main__":
    unittest.main()
