import os
import tempfile
import unittest

import db


class TestRequirementsAndEvidence(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_path = db.DATABASE_PATH
        db.DATABASE_PATH = os.path.join(
            self.temp_dir.name,
            "test_notes.db",
        )

    def tearDown(self):
        db.DATABASE_PATH = self.original_path
        self.temp_dir.cleanup()

    def test_create_requirement_defaults_to_unverified(self):
        project_id = db.create_project("Test Project")
        requirement_id = db.create_requirement(
            project_id,
            "Motor shall not exceed 5A",
        )

        requirement = db.get_requirement(requirement_id)

        self.assertEqual(requirement[4], "Unverified")

    def test_add_evidence_and_retrieve(self):
        project_id = db.create_project("Test Project")
        requirement_id = db.create_requirement(
            project_id,
            "Motor shall not exceed 5A",
        )

        db.add_evidence(
            requirement_id,
            source="bench_test_log.csv",
            result="Measured 4.2A peak",
            supports_status="Verified",
            location="row 12",
        )

        evidence = db.get_evidence_for_requirement(requirement_id)

        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0][5], "Verified")

    def test_status_does_not_change_automatically_when_evidence_added(self):
        project_id = db.create_project("Test Project")
        requirement_id = db.create_requirement(
            project_id,
            "Motor shall not exceed 5A",
        )

        db.add_evidence(
            requirement_id,
            source="bench_test_log.csv",
            result="Measured 4.2A peak",
            supports_status="Verified",
        )

        requirement = db.get_requirement(requirement_id)

        self.assertEqual(requirement[4], "Unverified")

    def test_update_requirement_status_explicitly(self):
        project_id = db.create_project("Test Project")
        requirement_id = db.create_requirement(
            project_id,
            "Motor shall not exceed 5A",
        )

        db.update_requirement_status(requirement_id, "Verified")

        requirement = db.get_requirement(requirement_id)

        self.assertEqual(requirement[4], "Verified")

    def test_invalid_status_rejected(self):
        project_id = db.create_project("Test Project")
        requirement_id = db.create_requirement(
            project_id,
            "Motor shall not exceed 5A",
        )

        with self.assertRaises(ValueError):
            db.update_requirement_status(
                requirement_id,
                "Definitely Verified",
            )

    def test_find_matching_evidence(self):
        project_id = db.create_project("Test Project")
        requirement_id = db.create_requirement(
            project_id,
            "Motor shall not exceed 5A",
        )

        db.add_evidence(
            requirement_id,
            source="bench_test_log.csv",
            result="Measured 4.2A peak",
            supports_status="Verified",
            location="row 12",
        )

        matches = db.find_matching_evidence(
            requirement_id,
            source="bench_test_log.csv",
            result="Measured 4.2A peak",
            supports_status="Verified",
            location="row 12",
        )

        self.assertEqual(len(matches), 1)

    def test_find_matching_evidence_returns_empty_for_different_evidence(self):
        project_id = db.create_project("Test Project")
        requirement_id = db.create_requirement(
            project_id,
            "Motor shall not exceed 5A",
        )

        db.add_evidence(
            requirement_id,
            source="bench_test_log.csv",
            result="Measured 4.2A peak",
            supports_status="Verified",
            location="row 12",
        )

        matches = db.find_matching_evidence(
            requirement_id,
            source="different_test.csv",
            result="Measured 4.2A peak",
            supports_status="Verified",
            location="row 12",
        )

        self.assertEqual(len(matches), 0)

    def test_evidence_evaluation_with_no_evidence(self):
        project_id = db.create_project("Test Project")
        requirement_id = db.create_requirement(
            project_id,
            "Motor shall not exceed 5A",
        )

        evaluation = db.evaluate_requirement_evidence(requirement_id)

        self.assertEqual(
            evaluation["recommendation"],
            "Unverified",
        )
        self.assertFalse(evaluation["conflict"])

    def test_evidence_evaluation_with_verified_evidence(self):
        project_id = db.create_project("Test Project")
        requirement_id = db.create_requirement(
            project_id,
            "Motor shall not exceed 5A",
        )

        db.add_evidence(
            requirement_id,
            source="bench_test_log.csv",
            result="Measured 4.2A peak",
            supports_status="Verified",
        )

        evaluation = db.evaluate_requirement_evidence(requirement_id)

        self.assertEqual(
            evaluation["recommendation"],
            "Verified",
        )
        self.assertEqual(
            evaluation["signals"],
            ["Verified"],
        )
        self.assertFalse(evaluation["conflict"])

    def test_evidence_evaluation_with_failed_evidence(self):
        project_id = db.create_project("Test Project")
        requirement_id = db.create_requirement(
            project_id,
            "Motor shall not exceed 5A",
        )

        db.add_evidence(
            requirement_id,
            source="bench_test_log.csv",
            result="Measured 6.1A peak",
            supports_status="Failed",
        )

        evaluation = db.evaluate_requirement_evidence(requirement_id)

        self.assertEqual(
            evaluation["recommendation"],
            "Failed",
        )

    def test_evidence_evaluation_with_at_risk_evidence(self):
        project_id = db.create_project("Test Project")
        requirement_id = db.create_requirement(
            project_id,
            "Motor shall not exceed 5A",
        )

        db.add_evidence(
            requirement_id,
            source="inspection_notes.txt",
            result="Thermal margin is smaller than expected",
            supports_status="At risk",
        )

        evaluation = db.evaluate_requirement_evidence(requirement_id)

        self.assertEqual(
            evaluation["recommendation"],
            "At risk",
        )

    def test_evidence_evaluation_detects_conflicting_evidence(self):
        project_id = db.create_project("Test Project")
        requirement_id = db.create_requirement(
            project_id,
            "Motor shall not exceed 5A",
        )

        db.add_evidence(
            requirement_id,
            source="test_a.csv",
            result="Measured 4.2A peak",
            supports_status="Verified",
        )

        db.add_evidence(
            requirement_id,
            source="test_b.csv",
            result="Measured 6.1A peak",
            supports_status="Failed",
        )

        evaluation = db.evaluate_requirement_evidence(requirement_id)

        self.assertEqual(
            evaluation["recommendation"],
            "At risk",
        )
        self.assertTrue(evaluation["conflict"])
        self.assertEqual(
            evaluation["signals"],
            ["Failed", "Verified"],
        )
    def test_evidence_history_includes_invalidated_evidence(self):
        project_id = db.create_project("Test Project")
        requirement_id = db.create_requirement(
            project_id,
            "Motor shall not exceed 5A",
        )

        evidence_id = db.add_evidence(
            requirement_id,
            source="test.csv",
            result="Measured 4.2A peak",
            supports_status="Verified",
        )

        db.invalidate_evidence(evidence_id)

        history = db.get_evidence_history_for_requirement(requirement_id)

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0][0], evidence_id)
        self.assertEqual(history[0][1], requirement_id)
        self.assertEqual(history[0][2], "test.csv")
        self.assertEqual(history[0][4], "Measured 4.2A peak")
        self.assertEqual(history[0][5], "Verified")
        self.assertEqual(history[0][6], "Invalidated")

    def test_invalidate_evidence_removes_it_from_active_evidence(self):
        project_id = db.create_project("Test Project")
        requirement_id = db.create_requirement(
            project_id,
            "Motor shall not exceed 5A",
        )

        evidence_id = db.add_evidence(
            requirement_id,
            source="test.csv",
            result="Measured 4.2A peak",
            supports_status="Verified",
        )

        active_evidence = db.get_evidence_for_requirement(requirement_id)

        self.assertEqual(len(active_evidence), 1)
        self.assertEqual(active_evidence[0][0], evidence_id)

        db.invalidate_evidence(evidence_id)

        active_evidence = db.get_evidence_for_requirement(requirement_id)

        self.assertEqual(active_evidence, [])

        connection = db.get_connection()

        record = connection.execute(
            """
            SELECT id, lifecycle_status
            FROM evidence
            WHERE id = ?
            """,
            (evidence_id,),
        ).fetchone()

        connection.close()

        self.assertEqual(record[0], evidence_id)
        self.assertEqual(record[1], "Invalidated")


if __name__ == "__main__":
    unittest.main()
