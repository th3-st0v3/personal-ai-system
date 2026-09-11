import os
import sqlite3
import tempfile
import unittest

import db


class TestEngineeringOrganizationPersistence(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_path = db.DATABASE_PATH
        db.DATABASE_PATH = os.path.join(self.temp_dir.name, "test.db")

    def tearDown(self):
        db.DATABASE_PATH = self.original_path
        self.temp_dir.cleanup()

    def test_schema_creates_wells_and_design_cases(self):
        connection = db.get_connection()
        tables = {
            row[0]
            for row in connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table'
                  AND name IN ('wells', 'design_cases')
                """
            ).fetchall()
        }
        version = connection.execute(
            "SELECT version FROM schema_version"
        ).fetchone()[0]
        connection.close()

        self.assertEqual(tables, {"wells", "design_cases"})
        self.assertEqual(version, db.SCHEMA_VERSION)
        self.assertEqual(version, 6)

    def test_create_and_get_well(self):
        project_id = db.create_project("Well Study")

        well_id = db.create_well(
            project_id,
            "Well A-1",
            identifier="A-1",
            description="Primary study well",
        )

        well = db.get_well(well_id)

        self.assertEqual(well[0], well_id)
        self.assertEqual(well[1], project_id)
        self.assertEqual(well[2], "Well A-1")
        self.assertEqual(well[3], "A-1")
        self.assertEqual(well[4], "Primary study well")
        self.assertEqual(well[5], "Active")

    def test_wells_are_scoped_to_project(self):
        first_project = db.create_project("Project A")
        second_project = db.create_project("Project B")

        first_well = db.create_well(first_project, "Well A")
        second_well = db.create_well(second_project, "Well B")

        self.assertEqual(
            [row[0] for row in db.get_wells(first_project)],
            [first_well],
        )
        self.assertEqual(
            [row[0] for row in db.get_wells(second_project)],
            [second_well],
        )

    def test_well_identifier_is_unique_within_project(self):
        project_id = db.create_project("Well Study")
        db.create_well(project_id, "Well A", identifier="API-1")

        with self.assertRaises(sqlite3.IntegrityError):
            db.create_well(project_id, "Well B", identifier="API-1")

    def test_well_lifecycle_status_can_be_updated(self):
        project_id = db.create_project("Well Study")
        well_id = db.create_well(project_id, "Well A")

        db.update_well_lifecycle_status(well_id, "Archived")

        self.assertEqual(db.get_well(well_id)[5], "Archived")

    def test_invalid_well_lifecycle_status_is_rejected(self):
        project_id = db.create_project("Well Study")
        well_id = db.create_well(project_id, "Well A")

        with self.assertRaises(ValueError):
            db.update_well_lifecycle_status(well_id, "Deleted")

    def test_create_and_get_design_case_for_well(self):
        project_id = db.create_project("Well Study")
        well_id = db.create_well(project_id, "Well A")

        case_id = db.create_design_case(
            project_id,
            "Base Case",
            well_id=well_id,
            description="Initial engineering case",
        )

        case = db.get_design_case(case_id)

        self.assertEqual(case[0], case_id)
        self.assertEqual(case[1], project_id)
        self.assertEqual(case[2], well_id)
        self.assertEqual(case[3], "Base Case")
        self.assertEqual(case[4], "Initial engineering case")
        self.assertEqual(case[5], "Active")

    def test_design_case_can_exist_without_a_well(self):
        project_id = db.create_project("General Study")

        case_id = db.create_design_case(
            project_id,
            "Project-Level Case",
        )

        case = db.get_design_case(case_id)

        self.assertEqual(case[1], project_id)
        self.assertIsNone(case[2])

    def test_design_case_cannot_link_well_from_another_project(self):
        first_project = db.create_project("Project A")
        second_project = db.create_project("Project B")
        well_id = db.create_well(first_project, "Well A")

        with self.assertRaises(sqlite3.IntegrityError):
            db.create_design_case(
                second_project,
                "Invalid Case",
                well_id=well_id,
            )

    def test_design_cases_can_be_filtered_by_project_and_well(self):
        project_id = db.create_project("Well Study")
        well_id = db.create_well(project_id, "Well A")
        other_well_id = db.create_well(project_id, "Well B")

        first_case = db.create_design_case(project_id, "Case A", well_id=well_id)
        second_case = db.create_design_case(project_id, "Case B", well_id=other_well_id)
        project_case = db.create_design_case(project_id, "Project Case")

        self.assertEqual(
            [row[0] for row in db.get_design_cases(project_id=project_id)],
            [first_case, second_case, project_case],
        )
        self.assertEqual(
            [row[0] for row in db.get_design_cases(well_id=well_id)],
            [first_case],
        )
        self.assertEqual(
            [row[0] for row in db.get_design_cases(project_id, well_id)],
            [first_case],
        )

    def test_design_case_lifecycle_status_can_be_updated(self):
        project_id = db.create_project("Well Study")
        case_id = db.create_design_case(project_id, "Case A")

        db.update_design_case_lifecycle_status(case_id, "Superseded")

        self.assertEqual(db.get_design_case(case_id)[5], "Superseded")

    def test_v5_database_migrates_without_losing_project_data(self):
        legacy_path = os.path.join(self.temp_dir.name, "legacy_v5.db")
        connection = sqlite3.connect(legacy_path)
        connection.execute("PRAGMA foreign_keys = ON")

        connection.execute("""
            CREATE TABLE schema_version (version INTEGER NOT NULL)
        """)
        connection.execute(
            "INSERT INTO schema_version (version) VALUES (5)"
        )
        connection.execute("""
            CREATE TABLE projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        connection.execute(
            "INSERT INTO projects (name, description) VALUES (?, ?)",
            ("Legacy Project", "Preserve this project"),
        )
        connection.commit()
        connection.close()

        db.DATABASE_PATH = legacy_path
        connection = db.get_connection()
        version = connection.execute(
            "SELECT version FROM schema_version"
        ).fetchone()[0]
        project = connection.execute(
            "SELECT name, description FROM projects"
        ).fetchone()
        tables = {
            row[0]
            for row in connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table'
                  AND name IN ('wells', 'design_cases')
                """
            ).fetchall()
        }
        connection.close()

        self.assertEqual(version, 6)
        self.assertEqual(project, ("Legacy Project", "Preserve this project"))
        self.assertEqual(tables, {"wells", "design_cases"})
