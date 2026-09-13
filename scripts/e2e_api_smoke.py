"""Exercise the HTTP routes used by the production web client."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"


def request(method: str, path: str, payload: object | None = None) -> object:
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AssertionError(f"{method} {path} returned HTTP {exc.code}: {detail}") from exc


manifest = request("GET", "/api/manifest")
assert isinstance(manifest, dict) and manifest.get("api_version") == 3
project = request("POST", "/api/projects", {"name": "CI E2E Project", "description": "route smoke"})
assert isinstance(project, dict) and isinstance(project.get("id"), int)
project_id = project["id"]
note = request("POST", f"/api/projects/{project_id}/notes", {"title": "CI note", "content": "pressure evidence"})
assert isinstance(note, dict) and isinstance(note.get("id"), int)
search = request("GET", f"/api/projects/{project_id}/search?q=pressure")
assert isinstance(search, list) and any(item.get("kind") == "note" for item in search if isinstance(item, dict))
majors = request("GET", "/api/calculations/majors")
assert isinstance(majors, list) and len(majors) == 6
catalog = request("GET", "/api/calculations/catalog")
assert isinstance(catalog, list) and catalog
model_key = catalog[0]["key"]
model_detail = request("GET", f"/api/calculations/{model_key}")
assert isinstance(model_detail, dict) and "model" in model_detail
simulations = request("GET", "/api/simulations")
assert isinstance(simulations, list) and simulations
sim_key = simulations[0]["key"]
inputs = {str(parameter): 1.0 for parameter in simulations[0].get("parameters", [])}
sim_result = request("POST", "/api/simulations/run", {"simulation_key": sim_key, "inputs": inputs})
assert isinstance(sim_result, dict) and "outputs" in sim_result
chat = request("POST", "/api/chats", {"project_id": project_id})
assert isinstance(chat, dict) and isinstance(chat.get("id"), int)
chat_id = chat["id"]
chat_result = request("POST", f"/api/chats/{chat_id}/messages", {"content": "Create a transparent engineering model.", "model": "profile:free", "mode": "auto"})
assert isinstance(chat_result, dict) and isinstance(chat_result.get("messages"), list)
requirements = request("POST", f"/api/engineering/projects/{project_id}/requirements", {"description": "Pressure remains within bounds"})
assert isinstance(requirements, dict) and isinstance(requirements.get("id"), int)
req_id = requirements["id"]
source = request("POST", f"/api/engineering/projects/{project_id}/sources/ingest", {"title": "CI source", "content": "Pressure is 100 psi.", "source_type": "text"})
assert isinstance(source, dict) and isinstance(source.get("id"), int)
source_id = source["id"]
source_results = request("GET", f"/api/engineering/projects/{project_id}/sources/search?q=pressure&limit=5")
assert isinstance(source_results, list) and source_results
plan = request("GET", f"/api/engineering/projects/{project_id}/requirements/test-plan")
assert isinstance(plan, list) or isinstance(plan, dict)
evidence = request("POST", f"/api/engineering/projects/{project_id}/requirements/{req_id}/evidence", {"result": "100 psi", "supports_status": "Verified", "source_id": source_id, "description": "CI evidence"})
assert isinstance(evidence, dict) and isinstance(evidence.get("id"), int)
evidence_list = request("GET", f"/api/engineering/projects/{project_id}/requirements/{req_id}/evidence")
assert isinstance(evidence_list, list) and evidence_list
report = request("GET", f"/api/engineering/projects/{project_id}/report")
assert isinstance(report, dict)
request("PATCH", f"/api/chats/{chat_id}", {"title": "CI renamed", "pinned": True})
request("DELETE", f"/api/chats/{chat_id}")
request("DELETE", f"/api/projects/{project_id}")
print("HTTP E2E API smoke: PASS")
