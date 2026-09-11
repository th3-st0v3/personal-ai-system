"""Run a compact end-to-end smoke test for the draft beta application boundary."""
from __future__ import annotations

import base64
import json
import os
import tempfile

import db
from engineering_web_api import create_engineering_app
from web_api import create_app
from workspace_application import WorkspaceApplication


def request(app, method, path, payload=None):
    body = b"" if payload is None else json.dumps(payload).encode()
    status, _, raw = app.request(method, path, body)
    return status, json.loads(raw)


def main() -> None:
    with tempfile.TemporaryDirectory() as temp:
        original = db.DATABASE_PATH
        db.DATABASE_PATH = os.path.join(temp, "smoke.db")
        try:
            workspace = WorkspaceApplication(os.path.join(temp, "storage"))
            app = create_app(workspace)
            engineering = create_engineering_app()
            status, project = request(app, "POST", "/api/projects", {"name": "Smoke Project"})
            assert status == 201 and project["id"] == 1
            project_id = project["id"]
            status, folder = request(app, "POST", f"/api/projects/{project_id}/folders", {"name": "Sources"})
            assert status == 201
            folder_id = folder["id"]
            payload = base64.b64encode(b"beta smoke").decode("ascii")
            status, file = request(app, "POST", f"/api/projects/{project_id}/files", {"name": "smoke.txt", "mime_type": "text/plain", "folder_id": folder_id, "data_base64": payload})
            assert status == 201
            file_id = file["id"]
            status, downloaded = request(app, "GET", f"/api/projects/{project_id}/files?id={file_id}")
            assert status == 200 and base64.b64decode(downloaded["data_base64"]) == b"beta smoke"
            status, note = request(app, "POST", f"/api/projects/{project_id}/notes", {"title": "Smoke Note", "content": "works", "folder_id": folder_id})
            assert status == 201
            note_id = note["id"]
            status, updated = request(app, "PATCH", f"/api/projects/{project_id}/notes", {"id": note_id, "title": "Edited", "content": "still works"})
            assert status == 200 and updated["name"] == "Edited"
            status, trace = request(app, "POST", "/api/calculations/run", {"model_key": "hydrostatic_pressure", "inputs": {"density": 1000, "gravity": 9.80665, "depth": 10}})
            assert status == 200 and trace["result"] == 98066.5
            status, items = request(app, "GET", f"/api/projects/{project_id}/items?folder_id={folder_id}&sort=a_z")
            assert status == 200 and {item["name"] for item in items} == {"Edited", "smoke.txt"}
            status, requirement = request(engineering, "POST", f"/api/engineering/projects/{project_id}/requirements", {"description": "Smoke requirement"})
            assert status == 201
            requirement_id = requirement["id"]
            status, source = request(engineering, "POST", f"/api/engineering/projects/{project_id}/sources", {"title": "Smoke source", "source_type": "test"})
            assert status == 201
            status, evidence = request(engineering, "POST", f"/api/engineering/projects/{project_id}/requirements/{requirement_id}/evidence", {"result": "Confirmed", "supports_status": "Verified", "source_id": source["id"]})
            assert status == 201 and evidence["id"] > 0
        finally:
            db.DATABASE_PATH = original
    print("draft beta smoke test: PASS")


if __name__ == "__main__":
    main()
