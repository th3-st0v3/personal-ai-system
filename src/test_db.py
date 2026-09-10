import os
import sqlite3
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
    def test_get_calculation_record_returns_none_for_missing_id(self):
        retrieved = db.get_calculation_record(999999)

        self.assertIsNone(retrieved)
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

    def test_find_matching_evidence_ignores_invalidated_evidence(self):
        project_id = db.create_project("Test Project")
        requirement_id = db.create_requirement(
            project_id,
            "Motor shall not exceed 5A",
        )

        evidence_id = db.add_evidence(
            requirement_id,
            source="bench_test_log.csv",
            result="Measured 4.2A peak",
            supports_status="Verified",
            location="row 12",
        )

        db.invalidate_evidence(evidence_id)

        matches = db.find_matching_evidence(
            requirement_id,
            source="bench_test_log.csv",
            result="Measured 4.2A peak",
            supports_status="Verified",
            location="row 12",
        )

        self.assertEqual(len(matches), 0)

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


    def test_schema_version_is_current(self):
        connection = db.get_connection()

        version = connection.execute(
            "SELECT version FROM schema_version"
        ).fetchone()[0]

        connection.close()

        self.assertEqual(version, db.SCHEMA_VERSION)

    def test_old_database_migrates_without_losing_evidence(self):
        legacy_path = os.path.join(
            self.temp_dir.name,
            "legacy_v1_notes.db",
        )

        connection = sqlite3.connect(legacy_path)
        connection.execute("PRAGMA foreign_keys = ON")

        connection.execute("""
            CREATE TABLE notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'user',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                project_id INTEGER
            )
        """)

        connection.execute("""
            CREATE TABLE projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

        connection.execute("""
            CREATE TABLE requirements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Unverified'
                    CHECK (
                        status IN (
                            'Verified',
                            'Failed',
                            'Unverified',
                            'At risk'
                        )
                    ),
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (project_id) REFERENCES projects(id)
            )
        """)

        connection.execute("""
            CREATE TABLE evidence (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                requirement_id INTEGER NOT NULL,
                source TEXT NOT NULL,
                location TEXT,
                result TEXT NOT NULL,
                supports_status TEXT NOT NULL
                    CHECK (
                        supports_status IN (
                            'Verified',
                            'Failed',
                            'Unverified',
                            'At risk'
                        )
                    ),
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (requirement_id)
                    REFERENCES requirements(id)
            )
        """)

        connection.execute("""
            CREATE TABLE schema_version (
                version INTEGER NOT NULL
            )
        """)

        connection.execute(
            "INSERT INTO schema_version (version) VALUES (1)"
        )

        project_cursor = connection.execute(
            """
            INSERT INTO projects (name, description)
            VALUES (?, ?)
            """,
            ("Migration Test Project", None),
        )
        project_id = project_cursor.lastrowid

        requirement_cursor = connection.execute(
            """
            INSERT INTO requirements (project_id, description)
            VALUES (?, ?)
            """,
            (project_id, "Motor shall not exceed 5A"),
        )
        requirement_id = requirement_cursor.lastrowid

        connection.execute(
            """
            INSERT INTO evidence (
                requirement_id,
                source,
                location,
                result,
                supports_status
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                requirement_id,
                "old_test.csv",
                "row 7",
                "Measured 4.2A peak",
                "Verified",
            ),
        )

        connection.commit()
        connection.close()

        original_database_path = db.DATABASE_PATH
        db.DATABASE_PATH = legacy_path

        try:
            connection = db.get_connection()

            evidence = connection.execute(
                """
                SELECT
                    id,
                    requirement_id,
                    source,
                    location,
                    result,
                    supports_status,
                    lifecycle_status
                FROM evidence
                """
            ).fetchall()

            version_rows = connection.execute(
                "SELECT version FROM schema_version"
            ).fetchall()

            connection.close()
        finally:
            db.DATABASE_PATH = original_database_path

        self.assertEqual(len(evidence), 1)
        self.assertEqual(
            evidence[0][1:6],
            (
                requirement_id,
                "old_test.csv",
                "row 7",
                "Measured 4.2A peak",
                "Verified",
            ),
        )
        self.assertEqual(evidence[0][6], "Active")
        self.assertEqual(version_rows, [(db.SCHEMA_VERSION,)])
    def test_get_calculation_records_returns_all_records(self):
        from calculation_records import CalculationRecord

        first = CalculationRecord(
            calculation_type="hydrostatic_pressure",
            inputs={
                "density": 1000.0,
                "gravity": 9.81,
                "depth": 10.0,
            },
            units={
                "density": "kg/m^3",
                "gravity": "m/s^2",
                "depth": "m",
            },
            assumptions=(
                "constant density",
                "constant gravitational acceleration",
            ),
            method="P = rho * g * h",
            result=98100.0,
            result_unit="Pa",
            source="deterministic calculation",
        )

        second = CalculationRecord(
            calculation_type="hydrostatic_pressure",
            inputs={
                "density": 1000.0,
                "gravity": 9.81,
                "depth": 20.0,
            },
            units={
                "density": "kg/m^3",
                "gravity": "m/s^2",
                "depth": "m",
            },
            assumptions=(
                "constant density",
                "constant gravitational acceleration",
            ),
            method="P = rho * g * h",
            result=196200.0,
            result_unit="Pa",
            source="deterministic calculation",
        )

        db.save_calculation_record(first)
        db.save_calculation_record(second)

        records = db.get_calculation_records()

        self.assertEqual(len(records), 2)
        self.assertIsInstance(records[0], CalculationRecord)
        self.assertIsInstance(records[1], CalculationRecord)
        self.assertEqual(records[0].result, 98100.0)
        self.assertEqual(records[1].result, 196200.0)
    def test_get_calculation_records_by_type_returns_matching_records(self):
        from calculation_records import CalculationRecord

        hydrostatic = CalculationRecord(
            calculation_type="hydrostatic_pressure",
            inputs={
                "density": 1000.0,
                "gravity": 9.81,
                "depth": 10.0,
            },
            units={
                "density": "kg/m^3",
                "gravity": "m/s^2",
                "depth": "m",
            },
            assumptions=(
                "constant density",
                "constant gravitational acceleration",
            ),
            method="P = rho * g * h",
            result=98100.0,
            result_unit="Pa",
            source="deterministic calculation",
        )

        other = CalculationRecord(
            calculation_type="other_calculation",
            inputs={"value": 5.0},
            units={"value": "unit"},
            assumptions=("test assumption",),
            method="test method",
            result=25.0,
            result_unit="unit",
            source="deterministic calculation",
        )

        db.save_calculation_record(hydrostatic)
        db.save_calculation_record(other)

        records = db.get_calculation_records_by_type(
            "hydrostatic_pressure"
        )

        self.assertEqual(len(records), 1)
        self.assertIsInstance(records[0], CalculationRecord)
        self.assertEqual(
            records[0].calculation_type,
            "hydrostatic_pressure",
        )
        self.assertEqual(records[0].result, 98100.0)
    def test_get_calculation_records_by_type_returns_empty_for_no_matches(self):
        records = db.get_calculation_records_by_type(
            "nonexistent_calculation"
        )

        self.assertEqual(records, [])
    def test_get_calculation_records_by_type_preserves_order(self):
        from calculation_records import CalculationRecord

        first = CalculationRecord(
            calculation_type="hydrostatic_pressure",
            inputs={
                "density": 1000.0,
                "gravity": 9.81,
                "depth": 5.0,
            },
            units={
                "density": "kg/m^3",
                "gravity": "m/s^2",
                "depth": "m",
            },
            assumptions=(
                "constant density",
                "constant gravitational acceleration",
            ),
            method="P = rho * g * h",
            result=49050.0,
            result_unit="Pa",
            source="deterministic calculation",
        )

        second = CalculationRecord(
            calculation_type="hydrostatic_pressure",
            inputs={
                "density": 1000.0,
                "gravity": 9.81,
                "depth": 15.0,
            },
            units={
                "density": "kg/m^3",
                "gravity": "m/s^2",
                "depth": "m",
            },
            assumptions=(
                "constant density",
                "constant gravitational acceleration",
            ),
            method="P = rho * g * h",
            result=147150.0,
            result_unit="Pa",
            source="deterministic calculation",
        )

        db.save_calculation_record(first)
        db.save_calculation_record(second)

        records = db.get_calculation_records_by_type(
            "hydrostatic_pressure"
        )

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].result, 49050.0)
        self.assertEqual(records[1].result, 147150.0)
    def test_get_calculation_records_by_type_returns_empty_for_empty_type(self):
        records = db.get_calculation_records_by_type("")

        self.assertEqual(records, [])
    def test_get_recent_calculation_records_returns_newest_first(self):
        from calculation_records import CalculationRecord

        first = CalculationRecord(
            calculation_type="hydrostatic_pressure",
            inputs={
                "density": 1000.0,
                "gravity": 9.81,
                "depth": 5.0,
            },
            units={
                "density": "kg/m^3",
                "gravity": "m/s^2",
                "depth": "m",
            },
            assumptions=(
                "constant density",
                "constant gravitational acceleration",
            ),
            method="P = rho * g * h",
            result=49050.0,
            result_unit="Pa",
            source="deterministic calculation",
        )

        second = CalculationRecord(
            calculation_type="hydrostatic_pressure",
            inputs={
                "density": 1000.0,
                "gravity": 9.81,
                "depth": 10.0,
            },
            units={
                "density": "kg/m^3",
                "gravity": "m/s^2",
                "depth": "m",
            },
            assumptions=(
                "constant density",
                "constant gravitational acceleration",
            ),
            method="P = rho * g * h",
            result=98100.0,
            result_unit="Pa",
            source="deterministic calculation",
        )

        third = CalculationRecord(
            calculation_type="hydrostatic_pressure",
            inputs={
                "density": 1000.0,
                "gravity": 9.81,
                "depth": 15.0,
            },
            units={
                "density": "kg/m^3",
                "gravity": "m/s^2",
                "depth": "m",
            },
            assumptions=(
                "constant density",
                "constant gravitational acceleration",
            ),
            method="P = rho * g * h",
            result=147150.0,
            result_unit="Pa",
            source="deterministic calculation",
        )

        db.save_calculation_record(first)
        db.save_calculation_record(second)
        db.save_calculation_record(third)

        records = db.get_recent_calculation_records(2)

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].result, 147150.0)
        self.assertEqual(records[1].result, 98100.0)        
    def test_current_database_does_not_duplicate_schema_version(self):
        connection = db.get_connection()

        rows = connection.execute(
            "SELECT version FROM schema_version"
        ).fetchall()

        connection.close()

        self.assertEqual(rows, [(db.SCHEMA_VERSION,)])
    def test_save_and_get_calculation_record(self):
        from calculation_records import CalculationRecord

        record = CalculationRecord(
            calculation_type="hydrostatic_pressure",
            inputs={
                "density": 1000.0,
                "gravity": 9.81,
                "depth": 10.0,
            },
            units={
                "density": "kg/m^3",
                "gravity": "m/s^2",
                "depth": "m",
            },
            assumptions=(
                "constant density",
                "constant gravitational acceleration",
            ),
            method="P = rho * g * h",
            result=98100.0,
            result_unit="Pa",
            source="deterministic calculation",
        )

        calculation_id = db.save_calculation_record(record)
        retrieved = db.get_calculation_record(calculation_id)

        self.assertIsInstance(retrieved, CalculationRecord)
        self.assertEqual(retrieved.calculation_type, "hydrostatic_pressure")
        self.assertEqual(retrieved.inputs["density"], 1000.0)
        self.assertEqual(retrieved.inputs["gravity"], 9.81)
        self.assertEqual(retrieved.inputs["depth"], 10.0)
        self.assertEqual(retrieved.result, 98100.0)
        self.assertEqual(retrieved.result_unit, "Pa")
        def test_get_calculation_record_returns_calculation_record(self):
            from calculation_records import CalculationRecord

        record = CalculationRecord(
            calculation_type="hydrostatic_pressure",
            inputs={
                "density": 1000.0,
                "gravity": 9.81,
                "depth": 10.0,
            },
            units={
                "density": "kg/m^3",
                "gravity": "m/s^2",
                "depth": "m",
            },
            assumptions=(
                "constant density",
                "constant gravitational acceleration",
            ),
            method="P = rho * g * h",
            result=98100.0,
            result_unit="Pa",
            source="deterministic calculation",
        )

        calculation_id = db.save_calculation_record(record)
        retrieved = db.get_calculation_record(calculation_id)

        self.assertIsInstance(retrieved, CalculationRecord)
        self.assertEqual(retrieved.calculation_type, "hydrostatic_pressure")
        self.assertEqual(retrieved.inputs["density"], 1000.0)
        self.assertEqual(retrieved.inputs["gravity"], 9.81)
        self.assertEqual(retrieved.inputs["depth"], 10.0)
        self.assertEqual(retrieved.units["density"], "kg/m^3")
        self.assertEqual(retrieved.units["gravity"], "m/s^2")
        self.assertEqual(retrieved.units["depth"], "m")
        self.assertEqual(
            retrieved.assumptions,
            (
                "constant density",
                "constant gravitational acceleration",
            ),
        )
        self.assertEqual(retrieved.method, "P = rho * g * h")
        self.assertEqual(retrieved.result, 98100.0)
        self.assertEqual(retrieved.result_unit, "Pa")
        self.assertEqual(retrieved.source, "deterministic calculation")
    def test_get_recent_calculation_records_rejects_non_positive_limit(self):
        with self.assertRaises(ValueError):
            db.get_recent_calculation_records(0)

        with self.assertRaises(ValueError):
            db.get_recent_calculation_records(-1)
if __name__ == "__main__":
    unittest.main()
