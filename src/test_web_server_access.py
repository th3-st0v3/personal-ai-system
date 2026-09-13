import io
import json
import os
import tempfile
import unittest

import db
from web_api import WebApplication
from web_server import SiteApplication
from workspace_application import WorkspaceApplication


class TestSiteApplicationResourceAuthorization(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_db = db.DATABASE_PATH
        db.DATABASE_PATH = os.path.join(self.temp.name, "site.db")
        self.workspace = WorkspaceApplication(os.path.join(self.temp.name, "storage"))
        self.api = WebApplication(self.workspace)
        self.site = SiteApplication(self.api, web_root=os.path.join(os.path.dirname(__file__), "..", "web"))
        self.legacy_project_id = self.workspace.create_project("Legacy local project")

    def tearDown(self):
        db.DATABASE_PATH = self.original_db
        self.temp.cleanup()

    def request(self, method, path, payload=None, cookie=None):
        body = json.dumps(payload).encode() if payload is not None else b""
        captured = {}
        environ = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path.split("?", 1)[0],
            "QUERY_STRING": path.split("?", 1)[1] if "?" in path else "",
            "CONTENT_LENGTH": str(len(body)),
            "wsgi.input": io.BytesIO(body),
            "HTTP_HOST": "127.0.0.1:8000",
        }
        if cookie:
            environ["HTTP_COOKIE"] = cookie

        def start_response(status, headers, exc_info=None):
            captured["status"] = status
            captured["headers"] = dict(headers)

        raw = b"".join(self.site(environ, start_response))
        return int(str(captured["status"]).split(" ", 1)[0]), captured["headers"], json.loads(raw)

    @staticmethod
    def cookie(headers):
        return headers["Set-Cookie"].split(";", 1)[0]

    def signup(self, email):
        status, headers, payload = self.request(
            "POST",
            "/api/auth/signup",
            {"email": email, "password": "safe-pass-123", "display_name": email.split("@", 1)[0]},
        )
        self.assertEqual(status, 201)
        return self.cookie(headers), payload["user"]

    def test_users_are_isolated_from_projects_chats_and_engineering_routes(self):
        alice_cookie, alice = self.signup("alice@example.com")
        status, _, created = self.request("POST", "/api/projects", {"name": "Alice project"}, alice_cookie)
        self.assertEqual(status, 201)
        alice_project_id = created["id"]
        status, _, created = self.request("POST", "/api/chats", {"project_id": alice_project_id}, alice_cookie)
        self.assertEqual(status, 201)
        alice_chat_id = created["id"]

        bob_cookie, bob = self.signup("bob@example.com")
        self.assertNotEqual(alice["id"], bob["id"])

        status, _, projects = self.request("GET", "/api/projects", bob_cookie)
        self.assertEqual(status, 200)
        self.assertEqual(projects, [])

        status, _, projects = self.request("GET", "/api/projects", alice_cookie)
        self.assertEqual(status, 200)
        self.assertEqual({item["id"] for item in projects}, {self.legacy_project_id, alice_project_id})

        status, _, _ = self.request("GET", f"/api/projects/{alice_project_id}", bob_cookie)
        self.assertEqual(status, 403)
        status, _, _ = self.request("PATCH", f"/api/projects/{alice_project_id}", {"description": "attacked"}, bob_cookie)
        self.assertEqual(status, 403)

        status, _, chats = self.request("GET", "/api/chats", bob_cookie)
        self.assertEqual(status, 200)
        self.assertEqual(chats, [])
        status, _, _ = self.request("GET", f"/api/chats/{alice_chat_id}", bob_cookie)
        self.assertEqual(status, 403)
        status, _, _ = self.request(
            "POST", f"/api/chats/{alice_chat_id}/messages", {"content": "unauthorized", "mode": "local"}, bob_cookie
        )
        self.assertEqual(status, 403)

        status, _, _ = self.request("GET", f"/api/engineering/projects/{alice_project_id}/requirements", bob_cookie)
        self.assertEqual(status, 403)
        status, _, requirements = self.request("GET", f"/api/engineering/projects/{alice_project_id}/requirements", alice_cookie)
        self.assertEqual(status, 200)
        self.assertEqual(requirements, [])

        status, _, _ = self.request("GET", f"/api/projects/{alice_project_id}")
        self.assertEqual(status, 401)


if __name__ == "__main__":
    unittest.main()
