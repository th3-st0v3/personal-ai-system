import os
import sqlite3
import tempfile
import unittest

import db
import ingestion_service
import policy


class TestIngestionPolicy(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original = db.DATABASE_PATH
        db.DATABASE_PATH = os.path.join(self.temp_dir.name, "test.db")
        connection = sqlite3.connect(db.DATABASE_PATH)
        db.initialize_database(connection)
        connection.close()
        self.project_id = db.create_project("Evidence Test")

    def tearDown(self):
        db.DATABASE_PATH = self.original
        self.temp_dir.cleanup()

    def test_text_ingestion_is_versioned_and_searchable(self):
        connection = db.get_connection()
        try:
            source = ingestion_service.ingest_text(
                connection, self.project_id, "test.md", "Pressure requirement: 5 MPa.\nUse steel.",
                version="1", chunk_chars=100,
            )
            hits = ingestion_service.search_chunks(connection, self.project_id, "5 MPa")
        finally:
            connection.close()
        self.assertEqual(source["source_type"], "text")
        self.assertEqual(len(source["chunks"]), 1)
        self.assertEqual(hits[0]["source"], "test.md")

    def test_duplicate_content_reuses_source(self):
        connection = db.get_connection()
        try:
            first = ingestion_service.ingest_text(connection, self.project_id, "same", "alpha")
            second = ingestion_service.ingest_text(connection, self.project_id, "same", "alpha")
        finally:
            connection.close()
        self.assertEqual(first["id"], second["id"])

    def test_policy_defaults_and_explicit_grants(self):
        connection = db.get_connection()
        try:
            self.assertTrue(policy.allowed(connection, "local", "run_calculation"))
            self.assertFalse(policy.allowed(connection, "local", "execute_code"))
            with self.assertRaises(PermissionError):
                policy.require(connection, "local", "execute_code")
            policy.grant(connection, "local", "run_simulation")
            self.assertTrue(policy.allowed(connection, "local", "run_simulation"))
            policy.revoke(connection, "local", "run_simulation")
            self.assertFalse(policy.allowed(connection, "local", "run_simulation"))
        finally:
            connection.close()

    def test_invalid_actions_are_rejected(self):
        connection = db.get_connection()
        try:
            with self.assertRaises(ValueError):
                policy.validate_action("sudo")
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
