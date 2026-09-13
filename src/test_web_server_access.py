"""HTTP-level authorization regression tests."""
from __future__ import annotations

import json
import tempfile
import unittest
from http.cookies import SimpleCookie
from pathlib import Path
from unittest.mock import patch

import auth_service
import db
from web_server import SiteApplication


class TestSiteApplicationResourceAuthorization(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.patcher = patch.multiple(
            db,
            DB_PATH=root / "app.db",
            STORAGE_ROOT=root / "storage",
        )
        self.patcher.start()
        db.initialize()
        self.app = SiteApplication()

    def tearDown(self):
        self.patcher.stop()
        self.temp.cleanup()

    def request(self, method, path, payload=None, cookie=None):
        body = b"" if payload is None else json.dumps(payload).encode()
        headers = {"Content-Type": "application/json", "Content-Length": str(len(body))}
        if cookie:
            headers["Cookie"] = cookie
        environ = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "QUERY_STRING": "",
            "CONTENT_LENGTH": str(len(body)),
            "CONTENT_TYPE": "application/json",
            "wsgi.input": __import__("io").BytesIO(body),
            "HTTP_COOKIE": headers.get("Cookie", ""),
        }
        captured = {}

        def start_response(status, response_headers):
            captured["status"] = int(status.split()[0])
            captured["headers"] = response_headers

        response = b"".join(self.app(environ, start_response))
        try:
            data = json.loads(response.decode()) if response else None
        except json.JSONDecodeError:
            data = response.decode()
        return captured["status"], captured["headers"], data

    @staticmethod
    def session_cookie(token):
        cookie = SimpleCookie()
        cookie["pas_session"] = token
        return cookie.output(header="", sep=";").strip()

    def signup(self, email):
        status, headers, body = self.request(
            "POST", "/api/auth/signup", {"email": email, "password": "correct horse battery staple"}
        )
        self.assertEqual(status, 201, body)
        set_cookie = next(value for name, value in headers if name.lower() == "set-cookie")
        cookie = SimpleCookie()
        cookie.load(set_cookie)
        return cookie["pas_session"].value

    def test_users_are_isolated_from_projects_chats_search_and_engineering_routes(self):
        alice_cookie = self.session_cookie(self.signup("alice@example.test"))
        bob_cookie = self.session_cookie(self.signup("bob@example.test"))

        status, _, alice_project = self.request(
            "POST", "/api/projects", {"name": "Alice private project"}, alice_cookie
        )
        self.assertEqual(status, 201, alice_project)
        alice_project_id = alice_project["project"]["id"]

        status, _, _ = self.request("POST", "/api/chats", {"project_id": alice_project_id}, alice_cookie)
        self.assertIn(status, (200, 201))
        status, _, chats = self.request("GET", "/api/chats", cookie=alice_cookie)
        self.assertEqual(status, 200)
        self.assertEqual(len(chats), 1)
        alice_chat_id = chats[0]["id"]

        status, _, projects = self.request("GET", "/api/projects", cookie=bob_cookie)
        self.assertEqual(status, 200)
        self.assertEqual(projects, [])
        status, _, _ = self.request("GET", f"/api/projects/{alice_project_id}", cookie=bob_cookie)
        self.assertEqual(status, 403)

        status, _, chats = self.request("GET", "/api/chats", cookie=bob_cookie)
        self.assertEqual(status, 200)
        self.assertEqual(chats, [])
        status, _, _ = self.request("GET", f"/api/chats/{alice_chat_id}", cookie=bob_cookie)
        self.assertEqual(status, 403)
        status, _, _ = self.request(
            "POST", f"/api/chats/{alice_chat_id}/messages", {"content": "unauthorized", "mode": "local"}, bob_cookie
        )
        self.assertEqual(status, 403)

        status, _, search = self.request("GET", "/api/search?q=private-alice", cookie=bob_cookie)
        self.assertEqual(status, 200, search)
        self.assertEqual(search["projects"], [])
        status, _, search = self.request("GET", "/api/search?q=private-alice", cookie=alice_cookie)
        self.assertEqual(status, 200, search)
        self.assertEqual({item["id"] for item in search["projects"]}, {alice_project_id})

        status, _, _ = self.request("GET", f"/api/engineering/projects/{alice_project_id}/requirements", cookie=bob_cookie)
        self.assertEqual(status, 403)
        status, _, requirements = self.request("GET", f"/api/engineering/projects/{alice_project_id}/requirements", cookie=alice_cookie)
        self.assertEqual(status, 200)
        self.assertEqual(requirements, [])

        status, _, _ = self.request("GET", f"/api/projects/{alice_project_id}")
        self.assertEqual(status, 401)


if __name__ == "__main__": unittest.main()
