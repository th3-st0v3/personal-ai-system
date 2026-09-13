import os
import sqlite3
import tempfile
import unittest
from typing import cast

import db
import ingestion_service
import policy


def as_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise AssertionError(f"expected list, got {value!r}")
    return cast(list[dict[str, object]], value)


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

    def test_text_ingestion_is_versioned_searchable_and_untrusted(self):
        connection = db.get_connection()
        try:
            source = ingestion_service.ingest_text(
                connection,
                self.project_id,
                "test.md",
                "Pressure requirement: 5 MPa.\nUse steel.",
                version="1",
                chunk_chars=100,
            )
            hits = ingestion_service.search_chunks(connection, self.project_id, "5 MPa")
        finally:
            connection.close()
        self.assertEqual(source["source_type"], "text")
        self.assertEqual(source["trust_level"], "untrusted")
        chunks = as_list(source["chunks"])
        self.assertEqual(len(chunks), 1)
        hit = hits[0]
        self.assertEqual(hit["source"], "test.md")
        self.assertEqual(hit["trust_level"], "untrusted")

    def test_rejects_invalid_source_metadata(self):
        connection = db.get_connection()
        try:
            with self.assertRaises(ValueError):
                ingestion_service.ingest_text(connection, self.project_id, "", "alpha")
            with self.assertRaises(ValueError):
                ingestion_service.ingest_text(connection, self.project_id, "same", "alpha", url="javascript:alert(1)")
            with self.assertRaises(ValueError):
                ingestion_service.ingest_text(connection, self.project_id, "same", "alpha", source_type="shell")
        finally:
            connection.close()

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

    def test_rate_limit_is_enforced(self):
        connection = db.get_connection()
        old = policy.RATE_LIMITS["run_calculation"]
        policy.RATE_LIMITS["run_calculation"] = (1, 60)
        try:
            policy.require(connection, "local", "run_calculation")
            with self.assertRaises(PermissionError):
                policy.require(connection, "local", "run_calculation")
        finally:
            policy.RATE_LIMITS["run_calculation"] = old
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
