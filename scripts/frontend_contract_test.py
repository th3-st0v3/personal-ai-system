"""Static frontend/backend contract checks for the browser application."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
PRODUCTION = (ROOT / "web" / "production-ui.js").read_text(encoding="utf-8")
ENGINEERING = (ROOT / "web" / "engineering-final.js").read_text(encoding="utf-8")
UX_FINAL = (ROOT / "web" / "ux-final.js").read_text(encoding="utf-8")
AUTH = (ROOT / "web" / "auth-ui.js").read_text(encoding="utf-8")

required_scripts = {
    "production-ui.js",
    "auth-ui.js",
    "engineering-final.js",
    "ux-final.js",
}
for script in required_scripts:
    assert f'src="/{script}"' in HTML, f"Missing {script} from index.html"
    assert (ROOT / "web" / script).is_file(), f"Missing script file: {script}"

required_dom_ids = {
    "chat-form", "chat-input", "send-chat", "ai-mode", "global-search", "chat-list",
    "project-files", "project-calculations", "project-simulations", "project-engineering",
    "calculations-toggle", "login-button", "signup-button", "account-button",
}
for element_id in required_dom_ids:
    assert f'id="{element_id}"' in HTML, f"Missing DOM contract: {element_id}"

required_frontend_capabilities = {
    "/api/chats",
    "/api/chats/",
    "/api/projects",
    "/api/calculations/majors",
    "/api/calculations/catalog",
    "/api/simulations",
    "/api/engineering/projects/",
    "/api/connections",
    "/api/plugins",
}
combined = PRODUCTION + ENGINEERING + UX_FINAL + AUTH
for endpoint in required_frontend_capabilities:
    assert endpoint in combined, f"Frontend does not reference backend endpoint: {endpoint}"

for capability in ("rename", "pin", "move", "share", "delete", "retry", "branch", "rate-up", "rate-down"):
    assert capability in PRODUCTION, f"Chat capability missing: {capability}"

for capability in ("Import GitHub file", "Search sources", "Add evidence", "Invalidate"):
    assert capability in ENGINEERING, f"Engineering UI capability missing: {capability}"

for capability in ("Skills", "Connectors", "Plugins", "You", "Discover"):
    assert capability in UX_FINAL, f"Customize capability missing: {capability}"

for capability in ("/api/auth/signup", "/api/auth/login"):
    assert capability in AUTH, f"Auth frontend capability missing: {capability}"

print("frontend/backend contract: PASS")
