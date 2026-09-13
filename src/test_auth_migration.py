import sqlite3
import unittest

import auth_service


class TestAuthMigration(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        auth_service.initialize(self.connection)

    def tearDown(self):
        self.connection.close()

    def test_initialize_migrates_legacy_users_table(self):
        connection = sqlite3.connect(":memory:")
        connection.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE, password_salt TEXT NOT NULL DEFAULT '', password_hash TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT '')"
        )
        auth_service.initialize(connection)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
        self.assertTrue({"display_name", "password_salt", "password_hash", "created_at"}.issubset(columns))
        user = auth_service.signup(connection, "legacy@example.com", "long-password", None)
        self.assertEqual(user["display_name"], "legacy")
        token, logged_in = auth_service.login(connection, "legacy@example.com", "long-password")
        self.assertTrue(token)
        self.assertEqual(logged_in["email"], "legacy@example.com")
        connection.close()

    def test_session_survives_new_database_connection(self):
        connection = sqlite3.connect(":memory:")
        auth_service.initialize(connection)
        auth_service.signup(connection, "persist@example.com", "long-password", "Persist")
        token, _ = auth_service.login(connection, "persist@example.com", "long-password")
        self.assertEqual(auth_service.current_user(connection, token)["email"], "persist@example.com")
        # The in-memory database cannot simulate a process restart, so verify the
        # persistence contract directly by creating a second connection to a file DB.
        connection.close()

        with __import__("tempfile").NamedTemporaryFile(suffix=".db") as tmp:
            first = sqlite3.connect(tmp.name)
            auth_service.initialize(first)
            auth_service.signup(first, "file@example.com", "long-password", "File")
            file_token, _ = auth_service.login(first, "file@example.com", "long-password")
            first.close()

            second = sqlite3.connect(tmp.name)
            auth_service.initialize(second)
            user = auth_service.current_user(second, file_token)
            self.assertIsNotNone(user)
            self.assertEqual(user["email"], "file@example.com")
            second.close()

    def test_new_login_revokes_old_session(self):
        auth_service.signup(self.connection, "rotate@example.com", "long-password", None)
        first_token, _ = auth_service.login(self.connection, "rotate@example.com", "long-password")
        second_token, _ = auth_service.login(self.connection, "rotate@example.com", "long-password")
        self.assertIsNone(auth_service.current_user(self.connection, first_token))
        self.assertIsNotNone(auth_service.current_user(self.connection, second_token))

    def test_explicit_rotation_revokes_previous_token(self):
        auth_service.signup(self.connection, "rotate2@example.com", "long-password", None)
        token, _ = auth_service.login(self.connection, "rotate2@example.com", "long-password")
        rotated = auth_service.rotate_session(self.connection, token)
        self.assertIsNotNone(rotated)
        self.assertIsNone(auth_service.current_user(self.connection, token))
        self.assertEqual(auth_service.current_user(self.connection, rotated)["email"], "rotate2@example.com")

    def test_logout_revokes_session(self):
        auth_service.signup(self.connection, "logout@example.com", "long-password", None)
        token, _ = auth_service.login(self.connection, "logout@example.com", "long-password")
        auth_service.logout(self.connection, token)
        self.assertIsNone(auth_service.current_user(self.connection, token))


if __name__ == "__main__":
    unittest.main()
