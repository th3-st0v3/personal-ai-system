import sqlite3
import tempfile
import unittest
from unittest.mock import patch

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

    def test_failed_logins_are_bounded_per_email_and_ip(self):
        auth_service.signup(self.connection, "throttle@example.com", "long-password", None)

        for _ in range(auth_service.LOGIN_MAX_FAILURES):
            with self.assertRaisesRegex(ValueError, "Email or password is incorrect."):
                auth_service.login(
                    self.connection,
                    "throttle@example.com",
                    "wrong-password",
                    client_ip="127.0.0.1",
                )

        with self.assertRaisesRegex(ValueError, "Email or password is incorrect."):
            auth_service.login(
                self.connection,
                "throttle@example.com",
                "long-password",
                client_ip="127.0.0.1",
            )

        row = self.connection.execute(
            "SELECT failure_count,locked_until FROM login_attempts WHERE throttle_key=?",
            ("ip:127.0.0.1",),
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], auth_service.LOGIN_MAX_FAILURES)
        self.assertGreater(row[1], auth_service._now())

    def test_successful_login_clears_throttle_state(self):
        auth_service.signup(self.connection, "reset@example.com", "long-password", None)
        with self.assertRaisesRegex(ValueError, "Email or password is incorrect."):
            auth_service.login(
                self.connection,
                "reset@example.com",
                "wrong-password",
                client_ip="127.0.0.2",
            )

        token, user = auth_service.login(
            self.connection,
            "reset@example.com",
            "long-password",
            client_ip="127.0.0.2",
        )
        self.assertTrue(token)
        self.assertEqual(user["email"], "reset@example.com")
        rows = self.connection.execute("SELECT COUNT(*) FROM login_attempts").fetchone()
        self.assertEqual(rows[0], 0)

    def test_expired_throttle_window_allows_login(self):
        auth_service.signup(self.connection, "expired@example.com", "long-password", None)
        with self.assertRaisesRegex(ValueError, "Email or password is incorrect."):
            auth_service.login(
                self.connection,
                "expired@example.com",
                "wrong-password",
                client_ip="127.0.0.3",
            )

        future = auth_service._now() + auth_service.LOGIN_FAILURE_WINDOW_SECONDS + 1
        with patch.object(auth_service, "_now", return_value=future):
            token, user = auth_service.login(
                self.connection,
                "expired@example.com",
                "long-password",
                client_ip="127.0.0.3",
            )
        self.assertTrue(token)
        self.assertEqual(user["email"], "expired@example.com")

    def test_logout_revokes_session(self):
        auth_service.signup(self.connection, "logout@example.com", "long-password", None)
        token, _ = auth_service.login(self.connection, "logout@example.com", "long-password")
        auth_service.logout(self.connection, token)
        self.assertIsNone(auth_service.current_user(self.connection, token))


if __name__ == "__main__":
    unittest.main()
