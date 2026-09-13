import os
import sqlite3
import tempfile
import unittest

import auth_service


class TestAuthMigration(unittest.TestCase):
    def test_initialize_migrates_legacy_users_table(self):
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE, password_salt TEXT NOT NULL DEFAULT '', password_hash TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT '')")
        auth_service.initialize(connection)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
        self.assertTrue({"display_name", "password_salt", "password_hash", "created_at"}.issubset(columns))
        user = auth_service.signup(connection, "legacy@example.com", "long-password", None)
        self.assertEqual(user["display_name"], "legacy")
        token, logged_in = auth_service.login(connection, "legacy@example.com", "long-password")
        self.assertTrue(token)
        self.assertEqual(logged_in["email"], "legacy@example.com")
        connection.close()


if __name__ == "__main__":
    unittest.main()
