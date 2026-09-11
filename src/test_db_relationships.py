import os
import tempfile
import unittest

import db
from calculation_records import CalculationRecord


class TestEvidenceCalculationRelationship(unittest.TestCase):
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

    def _create_requirement(self):
        project_id = db.create_project("Test Project")
        return db.create_requirement(
            project_id,
            "Pressure shall remain below 5,000 psi",
        )

    def _create_calculation(self):
        return CalculationRecord(
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
            assumptions=("constant density",),
            method="P = rho * g * h",
            result=98100.0,
            result_unit="Pa",
            source="deterministic calculation",
        )

    def test_evidence_without_calculation_remains_nullable(self):
        requirement_id = self._create_requirement()

        evidence_id = db.add_evidence(
            requirement_id,
            source="bench_test_log.csv",
            result="Measured 4.2A peak",
            supports_status="Verified",
        )

        evidence = db.get_evidence_for_requirement(requirement_id)

        self.assertEqual(evidence[0][0], evidence_id)
        self.assertIsNone(evidence[0][-1])

    def test_evidence_can_be_created_with_calculation_record(self):
        requirement_id = self._create_requirement()
        calculation_id = db.save_calculation_record(self._create_calculation())

        evidence_id = db.add_evidence(
            requirement_id,
            source="hydrostatic calculation",
            result="Calculated 98,100 Pa",
            supports_status="Verified",
            calculation_record_id=calculation_id,
        )

        evidence = db.get_evidence_for_requirement(requirement_id)

        self.assertEqual(evidence[0][0], evidence_id)
        self.assertEqual(evidence[0][-1], calculation_id)
        self.assertEqual(
            db.get_calculation_record_id_for_evidence(evidence_id),
            calculation_id,
        )

    def test_existing_evidence_can_be_linked_to_calculation(self):
        requirement_id = self._create_requirement()
        calculation_id = db.save_calculation_record(self._create_calculation())
        evidence_id = db.add_evidence(
            requirement_id,
            source="manual calculation",
            result="Calculated 98,100 Pa",
            supports_status="Verified",
        )

        db.link_evidence_to_calculation(evidence_id, calculation_id)

        self.assertEqual(
            db.get_calculation_record_id_for_evidence(evidence_id),
            calculation_id,
        )

    def test_linking_requires_existing_calculation(self):
        requirement_id = self._create_requirement()
        evidence_id = db.add_evidence(
            requirement_id,
            source="manual calculation",
            result="Calculated 98,100 Pa",
            supports_status="Verified",
        )

        with self.assertRaises(ValueError):
            db.link_evidence_to_calculation(evidence_id, 999999)

    def test_linking_requires_existing_evidence(self):
        calculation_id = db.save_calculation_record(self._create_calculation())

        with self.assertRaises(ValueError):
            db.link_evidence_to_calculation(999999, calculation_id)

    def test_evidence_history_preserves_calculation_link(self):
        requirement_id = self._create_requirement()
        calculation_id = db.save_calculation_record(self._create_calculation())
        evidence_id = db.add_evidence(
            requirement_id,
            source="hydrostatic calculation",
            result="Calculated 98,100 Pa",
            supports_status="Verified",
            calculation_record_id=calculation_id,
        )

        history = db.get_evidence_history_for_requirement(requirement_id)

        self.assertEqual(history[0][0], evidence_id)
        self.assertEqual(history[0][-1], calculation_id)

    def test_schema_migration_adds_nullable_calculation_link(self):
        database_path = os.path.join(
            self.temp_dir.name,
            "legacy_v3_notes.db",
        )

        connection = db.sqlite3.connect(database_path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("""
            CREATE TABLE schema_version (
                version INTEGER NOT NULL
            )
        """)
        connection.execute(
            "INSERT INTO schema_version (version) VALUES (3)"
        )
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
                status TEXT NOT NULL DEFAULT 'Unverified',
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
                supports_status TEXT NOT NULL,
                lifecycle_status TEXT NOT NULL DEFAULT 'Active',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (requirement_id) REFERENCES requirements(id)
            )
        """)
        connection.execute("""
            CREATE TABLE notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'user',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                project_id INTEGER
            )
        """)
        connection.commit()
        connection.close()

        original_path = db.DATABASE_PATH
        db.DATABASE_PATH = database_path
        try:
            connection = db.get_connection()
            columns = {
                row[1]: row
                for row in connection.execute("PRAGMA table_info(evidence)")
            }
            version = connection.execute(
                "SELECT version FROM schema_version"
            ).fetchone()[0]
            connection.close()
        finally:
            db.DATABASE_PATH = original_path

        self.assertIn("calculation_record_id", columns)
        self.assertEqual(columns["calculation_record_id"][3], 0)
        self.assertEqual(version, db.SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
