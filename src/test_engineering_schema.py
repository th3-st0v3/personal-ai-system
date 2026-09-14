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
        self.assertEqual(version, 2)


if __name__ == "__main__":
    unittest.main()
