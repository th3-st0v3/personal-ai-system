import sqlite3
import tempfile
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

    def test_session_survives_process_restart(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            first = sqlite3.connect(tmp.name)
            auth_service.initialize(first)
            auth_service.signup(first, "file@example.com", "long-password", "File")
            file_token, _ = auth_service.login(first, "file@example.com", "long-password")
            first.close()

            second = sqlite3.connect(tmp.name)
            auth_service.initialize(second)
            user = auth_service.current_user(second, file_token)
            if user is None:
                self.fail("session should survive process restart")
            self.assertEqual(user["email"], "file@example.com")
            second.close()

    def test_multiple_logins_keep_multiple_sessions(self):
        auth_service.signup(self.connection, "multi@example.com", "long-password", None)
        first_token, _ = auth_service.login(self.connection, "multi@example.com", "long-password")
        second_token, _ = auth_service.login(self.connection, "multi@example.com", "long-password")
        self.assertIsNotNone(auth_service.current_user(self.connection, first_token))
        self.assertIsNotNone(auth_service.current_user(self.connection, second_token))

    def test_explicit_rotation_revokes_previous_token(self):
        auth_service.signup(self.connection, "rotate2@example.com", "long-password", None)
        token, _ = auth_service.login(self.connection, "rotate2@example.com", "long-password")
        rotated = auth_service.rotate_session(self.connection, token)
        if rotated is None:
            self.fail("rotation should return a new token")
        self.assertIsNone(auth_service.current_user(self.connection, token))
        rotated_user = auth_service.current_user(self.connection, rotated)
        if rotated_user is None:
            self.fail("rotated token should remain valid")
        self.assertEqual(rotated_user["email"], "rotate2@example.com")

    def test_logout_revokes_session(self):
        auth_service.signup(self.connection, "logout@example.com", "long-password", None)
        token, _ = auth_service.login(self.connection, "logout@example.com", "long-password")
        auth_service.logout(self.connection, token)
        self.assertIsNone(auth_service.current_user(self.connection, token))


if __name__ == "__main__":
    unittest.main()
