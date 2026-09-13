"""Static frontend/backend contract checks for the browser application."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
HTML = (WEB / "index.html").read_text(encoding="utf-8")
BRIDGE = (WEB / "backend-frontend-bridge.js").read_text(encoding="utf-8")
BACKEND_FINAL = (WEB / "backend-final.js").read_text(encoding="utf-8")
PRODUCTION = (WEB / "production-ui.js").read_text(encoding="utf-8")
FINAL = (WEB / "final-interactions.js").read_text(encoding="utf-8")
ENGINEERING = (WEB / "engineering-final.js").read_text(encoding="utf-8")
UX_FINAL = (WEB / "ux-final.js").read_text(encoding="utf-8")
AUTH = (WEB / "auth-ui.js").read_text(encoding="utf-8")
PDF = (WEB / "pdf-ui.js").read_text(encoding="utf-8")
UI_COMPLETION = (WEB / "ui-completion.js").read_text(encoding="utf-8")
APP_CSS = (WEB / "app.css").read_text(encoding="utf-8")
DESIGN_SYSTEM = (WEB / "design-system.css").read_text(encoding="utf-8")
ACCESSIBILITY = (WEB / "accessibility.css").read_text(encoding="utf-8")
ACCESSIBILITY_RUNTIME = (WEB / "accessibility-runtime.js").read_text(encoding="utf-8")

required_scripts = {"production-ui.js", "auth-ui.js", "pdf-ui.js", "engineering-final.js", "ux-final.js", "final-controls.js", "final-interactions.js", "backend-frontend-bridge.js", "backend-final.js", "accessibility-runtime.js", "ui-completion.js"}
for script in required_scripts:
    assert f'src="/{script}"' in HTML, f"Missing {script} from index.html"
    assert (WEB / script).is_file(), f"Missing script file: {script}"
assert 'href="/app.css"' in HTML and APP_CSS, "Canonical stylesheet entrypoint is not loaded."
assert "/design-system.css" in APP_CSS and DESIGN_SYSTEM, "Canonical design system is not reachable from app.css."
assert "/accessibility.css" in APP_CSS and ACCESSIBILITY, "Accessibility layer is not reachable from app.css."
assert "PASAccessibility" in ACCESSIBILITY_RUNTIME, "Shared accessibility runtime is not exposed."

required_dom_ids = {"chat-form", "chat-input", "send-chat", "ai-mode", "global-search", "chat-list", "project-files", "project-calculations", "project-simulations", "project-engineering", "calculations-toggle", "calculation-categories", "login-button", "signup-button", "account-button"}
for element_id in required_dom_ids:
    assert f'id="{element_id}"' in HTML, f"Missing DOM contract: {element_id}"

combined = PRODUCTION + FINAL + ENGINEERING + UX_FINAL + AUTH + PDF + BRIDGE + BACKEND_FINAL
for endpoint in {
    "/api/chats", "/api/chats/", "/api/projects", "/api/calculations/majors", "/api/calculations/catalog", "/api/calculations/",
    "/api/calculations/run/save", "/api/simulations", "/api/simulations/run", "/api/engineering/projects/",
    "/sources/chunks/", "/api/connections", "/api/plugins", "/api/auth/signup", "/api/auth/login", "/api/search",
}:
    assert endpoint in combined, f"Frontend does not reference backend endpoint: {endpoint}"
assert "/api/chats/" in FINAL and "/branch" in FINAL and "/feedback" in FINAL, "Dynamic chat action routes are not wired."
for capability in ("rename", "pin", "move", "share", "delete", "retry", "branch", "rate-up", "rate-down"):
    assert capability in PRODUCTION + FINAL, f"Chat capability missing: {capability}"
for capability in ("Import GitHub file", "Search sources", "Add evidence", "Invalidate"):
    assert capability in ENGINEERING, f"Engineering UI capability missing: {capability}"
for capability in ("Run simulation", "data-run-simulation", "Add connection", "Register plugin", "data-toggle-plugin", "fetch source"):
    assert capability in BRIDGE, f"Bridge capability missing: {capability}"
for capability in ("Saved as calculation record", "project-paste", "/paste"):
    assert capability in BACKEND_FINAL, f"Final capability missing: {capability}"
search_source = (ROOT / "scripts" / "search_web_api.py") if (ROOT / "scripts" / "search_web_api.py").exists() else (ROOT / "src" / "search_web_api.py")
assert "project_id" in search_source.read_text(encoding="utf-8")
assert "get_chunk" in (ROOT / "src" / "ingestion_service.py").read_text(encoding="utf-8")
assert "Import PDF" in PDF and "/sources/pdf" in PDF and "pypdf" in (ROOT / "src" / "pdf_ingestion.py").read_text(encoding="utf-8")
for capability in ("Skills", "Connectors", "Plugins", "You", "Discover"):
    assert capability in UX_FINAL, f"Customize capability missing: {capability}"

# The completion layer owns the navigation UX and must preserve the full
# catalog hierarchy without duplicating calculation implementations.
for capability in (
    "data-calculation-category", "data-calculation-subgroup",
    "data-open-calculation-group", "data-open-calculation-subgroup",
    "calculation-group-card-grid", "calculation-card-grid", "prefers-reduced-motion",
):
    assert capability in UI_COMPLETION + DESIGN_SYSTEM, f"Frontend completion capability missing: {capability}"
assert "Ctrl+O" in HTML and "subcategories" in UI_COMPLETION, "Calculation shortcut/group contract is incomplete."
print("frontend/backend contract: PASS")
