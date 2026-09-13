import json
import os
import tempfile
import unittest

import db
from web_api import create_app
from workspace_application import WorkspaceApplication


class TestAuthWebDiagnostic(unittest.TestCase):
    def test_http_signup_returns_precise_service_error(self):
        temp = tempfile.TemporaryDirectory()
        old = db.DATABASE_PATH
        db.DATABASE_PATH = os.path.join(temp.name, "auth.db")
        try:
            workspace = WorkspaceApplication(os.path.join(temp.name, "storage"))
            app = create_app(workspace)
            status, _, raw = app.request("POST", "/api/auth/signup", json.dumps({"email":"diagnostic@example.com","password":"safe-pass-123","display_name":"Diagnostic"}).encode())
            if status != 201:
                self.fail(f"HTTP signup failed: status={status}, payload={raw.decode()}")
        finally:
            db.DATABASE_PATH = old
            temp.cleanup()


if __name__ == "__main__":
    unittest.main()
