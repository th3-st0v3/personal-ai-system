import json
import os
import sqlite3
import tempfile
import unittest

import auth_service
import db
from engineering_schema import initialize


class TestEngineeringSchema(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_path = db.DATABASE_PATH
        db.DATABASE_PATH = os.path.join(self.temp_dir.name, "test.db")
        connection = sqlite3.connect(db.DATABASE_PATH)
        connection.execute("PRAGMA foreign_keys = ON")
        db.initialize_database(connection)
        auth_service.initialize(connection)
        initialize(connection)
        connection.close()

    def tearDown(self):
        db.DATABASE_PATH = self.original_path
        self.temp_dir.cleanup()

    def test_core_entities_and_relationship_tables_exist(self):
        connection = db.get_connection()
        try:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        finally:
            connection.close()
        self.assertTrue({"workspaces", "users", "workspace_members", "sources", "evidence_locations", "source_chunks", "decisions", "reviews", "audit_events"}.issubset(tables))

    def test_project_and_requirement_extensions_are_additive(self):
        connection = db.get_connection()
        try:
            project_columns = {row[1] for row in connection.execute("PRAGMA table_info(projects)")}
            requirement_columns = {row[1] for row in connection.execute("PRAGMA table_info(requirements)")}
            evidence_columns = {row[1] for row in connection.execute("PRAGMA table_info(evidence)")}
        finally:
            connection.close()
        self.assertTrue({"workspace_id", "owner_id", "status", "updated_at"}.issubset(project_columns))
        self.assertTrue({"identifier", "title", "acceptance_criteria", "priority", "updated_at"}.issubset(requirement_columns))
        self.assertIn("evidence_type", evidence_columns)

    def test_schema_can_be_initialized_repeatedly(self):
        connection = db.get_connection()
        try:
            initialize(connection)
            initialize(connection)
            version = connection.execute("SELECT version FROM engineering_schema_version").fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(version, 3)

    def test_requirement_changes_are_audited_and_audit_events_are_immutable(self):
        project_id = db.create_project("Audit Project")
        requirement_id = db.create_requirement(project_id, "Initial requirement")
        connection = db.get_connection()
        try:
            created = connection.execute(
                "SELECT action, metadata FROM audit_events WHERE entity_type = 'requirement' AND entity_id = ? ORDER BY id",
                (requirement_id,),
            ).fetchall()
            self.assertEqual(created[0][0], "requirement_created")

            connection.execute(
                "UPDATE requirements SET title = ?, priority = ?, status = ? WHERE id = ?",
                ("Updated", "High", "Verified", requirement_id),
            )
            connection.commit()

            rows = connection.execute(
                "SELECT action, metadata FROM audit_events WHERE entity_type = 'requirement' AND entity_id = ? ORDER BY id",
                (requirement_id,),
            ).fetchall()
            self.assertEqual(len(rows), 4)
            field_names = {
                json.loads(row[1])["field"]
                for row in rows[1:]
            }
            self.assertEqual(field_names, {"title", "priority", "status"})

            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE audit_events SET action = 'tampered' WHERE entity_type = 'requirement' AND entity_id = ?",
                    (requirement_id,),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "DELETE FROM audit_events WHERE entity_type = 'requirement' AND entity_id = ?",
                    (requirement_id,),
                )

            status_event = json.loads(
                rows[3][1]
            )
            self.assertEqual(status_event["old"], "Unverified")
            self.assertEqual(status_event["new"], "Verified")
        finally:
            connection.close()



if __name__ == "__main__":
    unittest.main()
