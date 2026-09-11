import os
import sqlite3
import tempfile
import unittest

import db
from calculation_definitions import CALCULATION_DEFINITIONS
from calculations import hydrostatic_pressure_record


class TestCalculationFoundationPersistence(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_path = db.DATABASE_PATH
        db.DATABASE_PATH = os.path.join(self.temp_dir.name, "test.db")

    def tearDown(self):
        db.DATABASE_PATH = self.original_path
        self.temp_dir.cleanup()

    def test_schema_creates_calculation_foundation(self):
        connection = db.get_connection()
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        self.assertTrue({"calculation_models", "method_versions", "calculation_parameters"}.issubset(tables))
        self.assertEqual(connection.execute("SELECT version FROM schema_version").fetchone()[0], db.SCHEMA_VERSION)
        self.assertEqual(db.SCHEMA_VERSION, 6)
        connection.close()

    def test_built_in_models_and_parameters_are_seeded(self):
        connection = db.get_connection()
        models = connection.execute("SELECT key FROM calculation_models ORDER BY key").fetchall()
        parameter_count = connection.execute("SELECT COUNT(*) FROM calculation_parameters").fetchone()[0]
        connection.close()
        expected_models = sorted((model.key,) for model, _, _ in CALCULATION_DEFINITIONS)
        expected_parameter_count = sum(len(parameters) for _, _, parameters in CALCULATION_DEFINITIONS)
        self.assertEqual(models, expected_models)
        self.assertEqual(parameter_count, expected_parameter_count)

    def test_new_record_links_to_model_and_method_version(self):
        calculation_id = db.save_calculation_record(hydrostatic_pressure_record(1000.0, 9.81, 10.0))
        connection = db.get_connection()
        row = connection.execute(
            "SELECT calculation_model_id, method_version_id, method_version FROM calculation_records WHERE id = ?",
            (calculation_id,),
        ).fetchone()
        connection.close()
        self.assertEqual(row[2], "1.0")
        self.assertIsNotNone(row[0])
        self.assertIsNotNone(row[1])

    def test_v4_database_migrates_and_preserves_calculation_and_evidence_links(self):
        path = os.path.join(self.temp_dir.name, "legacy.db")
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript("""
            CREATE TABLE schema_version (version INTEGER NOT NULL);
            INSERT INTO schema_version VALUES (4);
            CREATE TABLE projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE requirements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Unverified',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (project_id) REFERENCES projects(id)
            );
            CREATE TABLE calculation_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                calculation_type TEXT NOT NULL,
                inputs TEXT NOT NULL,
                units TEXT NOT NULL,
                assumptions TEXT NOT NULL,
                method TEXT NOT NULL,
                result REAL NOT NULL,
                result_unit TEXT NOT NULL,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE evidence (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                requirement_id INTEGER NOT NULL,
                source TEXT NOT NULL,
                location TEXT,
                result TEXT NOT NULL,
                supports_status TEXT NOT NULL,
                lifecycle_status TEXT NOT NULL DEFAULT 'Active',
                calculation_record_id INTEGER,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (requirement_id) REFERENCES requirements(id),
                FOREIGN KEY (calculation_record_id) REFERENCES calculation_records(id)
            );
            INSERT INTO projects(name) VALUES ('Legacy');
            INSERT INTO requirements(project_id, description) VALUES (1, 'Pressure');
            INSERT INTO calculation_records(
                calculation_type, inputs, units, assumptions, method,
                result, result_unit, source
            ) VALUES (
                'hydrostatic_pressure',
                '{"density":1000,"gravity":9.81,"depth":10}',
                '{"density":"kg/m^3"}',
                '["constant density"]',
                'P = rho * g * h',
                98100,
                'Pa',
                'deterministic calculation'
            );
            INSERT INTO evidence(
                requirement_id, source, result, supports_status, calculation_record_id
            ) VALUES (1, 'legacy', '98100', 'Verified', 1);
        """)
        connection.commit()
        connection.close()

        db.DATABASE_PATH = path
        connection = db.get_connection()
        self.assertEqual(connection.execute("SELECT version FROM schema_version").fetchone()[0], db.SCHEMA_VERSION)
        self.assertEqual(connection.execute("SELECT version FROM schema_version").fetchone()[0], 6)
        self.assertEqual(connection.execute("SELECT calculation_record_id FROM evidence").fetchone()[0], 1)
        self.assertIsNotNone(connection.execute("SELECT calculation_model_id FROM calculation_records").fetchone()[0])
        connection.close()


if __name__ == "__main__":
    unittest.main()
