"""Exercise the HTTP routes used by the production web client."""
from __future__ import annotations

import base64
import io
import json
import urllib.error
import urllib.request

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

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


def sample_pdf() -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 72 720 Td (Pressure 100 psi) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


manifest = request("GET", "/api/manifest")
assert isinstance(manifest, dict) and manifest.get("api_version") == 3
project = request("POST", "/api/projects", {"name": "CI E2E Project", "description": "route smoke"})
assert isinstance(project, dict) and isinstance(project.get("id"), int)
project_id = project["id"]
note = request("POST", f"/api/projects/{project_id}/notes", {"title": "CI note", "content": "pressure evidence"})
assert isinstance(note, dict) and isinstance(note.get("id"), int)
search = request("GET", f"/api/projects/{project_id}/search?q=pressure")
assert isinstance(search, list) and any(item.get("kind") == "note" for item in search if isinstance(item, dict))
aggregate = request("GET", "/api/search?q=pressure")
assert isinstance(aggregate, dict) and any(item.get("id") == note["id"] and item.get("project_id") == project_id for item in aggregate.get("notes", []) if isinstance(item, dict))

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

connections = request("POST", "/api/connections", {"name": "CI provider", "provider": "test", "capabilities": ["chat"]})
assert isinstance(connections, dict) and isinstance(connections.get("id"), int)
plugins = request("POST", "/api/plugins", {"name": "CI plugin", "version": "0.1.0", "description": "smoke plugin", "entrypoint": "ci.plugin:main", "capabilities": ["test"]})
assert isinstance(plugins, dict) and isinstance(plugins.get("id"), int)
enabled_plugin = request("POST", f"/api/plugins/{plugins['id']}/enabled", {"enabled": True})
assert isinstance(enabled_plugin, dict) and enabled_plugin.get("enabled") is True
digest = request("POST", "/api/digest", {"text": "Pressure is 10 MPa. The value may vary with temperature. Verify the source."})
assert isinstance(digest, dict) and digest.get("claims")

chat = request("POST", "/api/chats", {"project_id": project_id})
assert isinstance(chat, dict) and isinstance(chat.get("id"), int)
chat_id = chat["id"]
chat_result = request("POST", f"/api/chats/{chat_id}/messages", {"content": "Create a transparent engineering model.", "model": "profile:free", "mode": "auto"})
assert isinstance(chat_result, dict) and isinstance(chat_result.get("messages"), list)
assistant_messages = [item for item in chat_result["messages"] if isinstance(item, dict) and item.get("role") == "assistant"]
assert assistant_messages and isinstance(assistant_messages[-1].get("id"), int)
feedback = request("POST", f"/api/chats/{chat_id}/feedback", {"message_id": assistant_messages[-1]["id"], "rating": "up"})
assert feedback == {"message_id": assistant_messages[-1]["id"], "rating": "up"}
branch = request("POST", f"/api/chats/{chat_id}/branch", {"title": "CI Branch"})
assert isinstance(branch, dict) and isinstance(branch.get("id"), int) and branch["id"] != chat_id
branch_id = branch["id"]
branched = request("GET", f"/api/chats/{branch_id}")
assert isinstance(branched, dict) and len(branched.get("messages", [])) >= len(chat_result.get("messages", []))

requirements = request("POST", f"/api/engineering/projects/{project_id}/requirements", {"description": "Pressure remains within bounds"})
assert isinstance(requirements, dict) and isinstance(requirements.get("id"), int)
req_id = requirements["id"]
source = request("POST", f"/api/engineering/projects/{project_id}/sources/ingest", {"title": "CI source", "content": "Pressure is 100 psi.", "source_type": "text"})
assert isinstance(source, dict) and isinstance(source.get("id"), int)
source_id = source["id"]
source_results = request("GET", f"/api/engineering/projects/{project_id}/sources/search?q=pressure&limit=5")
assert isinstance(source_results, list) and source_results
chunk_id = source_results[0]["chunk_id"]
chunk = request("GET", f"/api/engineering/projects/{project_id}/sources/chunks/{chunk_id}")
assert isinstance(chunk, dict) and chunk.get("source_id") == source_id and "content" in chunk

pdf_payload = base64.b64encode(sample_pdf()).decode("ascii")
pdf_source = request("POST", f"/api/engineering/projects/{project_id}/sources/pdf", {"title": "CI PDF source", "version": "1", "data_base64": pdf_payload})
assert isinstance(pdf_source, dict) and pdf_source.get("source_type") == "pdf" and pdf_source.get("page_count") == 1
pdf_search = request("GET", f"/api/engineering/projects/{project_id}/sources/search?q=Pressure%20100%20psi&limit=5")
assert isinstance(pdf_search, list) and any(item.get("source") == "CI PDF source" for item in pdf_search if isinstance(item, dict))

plan = request("GET", f"/api/engineering/projects/{project_id}/requirements/test-plan")
assert isinstance(plan, (list, dict))
evidence = request("POST", f"/api/engineering/projects/{project_id}/requirements/{req_id}/evidence", {"result": "100 psi", "supports_status": "Verified", "source": "CI source", "source_id": source_id, "description": "CI evidence"})
assert isinstance(evidence, dict) and isinstance(evidence.get("id"), int)
evidence_list = request("GET", f"/api/engineering/projects/{project_id}/requirements/{req_id}/evidence")
assert isinstance(evidence_list, list) and evidence_list
report = request("GET", f"/api/engineering/projects/{project_id}/report")
assert isinstance(report, dict)
request("POST", f"/api/engineering/projects/{project_id}/evidence/invalidate", {"id": evidence["id"], "reason": "CI invalidation test"})
request("PATCH", f"/api/chats/{chat_id}", {"title": "CI renamed", "pinned": True})
request("DELETE", f"/api/chats/{chat_id}")
request("DELETE", f"/api/chats/{branch_id}")
print("HTTP E2E API smoke: PASS")
