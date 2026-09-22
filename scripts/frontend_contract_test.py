"""Static contract checks for the consolidated four-file frontend."""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def test_frontend_contract() -> None:
    index = (WEB / "index.html").read_text(encoding="utf-8")
    app = (WEB / "app.js").read_text(encoding="utf-8")
    ui = (WEB / "ui-completion.js").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    expected_files = {"app.js", "index.html", "styles.css", "ui-completion.js"}
    actual_files = {path.name for path in WEB.iterdir() if path.is_file()}
    assert actual_files == expected_files, f"Unexpected frontend files: {sorted(actual_files ^ expected_files)}"

    for filename in expected_files:
        path = WEB / filename
        assert path.is_file(), f"Missing canonical frontend file: {filename}"
        assert path.stat().st_size > 0, f"Empty frontend file: {filename}"

    script_sources = set(re.findall(r'<script[^>]+src="([^"]+)"', index))
    assert script_sources == {"/app.js", "/ui-completion.js"}, (
        f"Unexpected script entrypoints: {sorted(script_sources)}"
    )
    assert 'href="/styles.css"' in index, "Canonical stylesheet is not loaded."

    legacy_names = {
        "backend-frontend-bridge.js", "backend-final.js", "production-ui.js",
        "final-interactions.js", "engineering-final.js", "ux-final.js", "auth-ui.js",
        "pdf-ui.js", "final-controls.js", "app.css", "design-system.css",
        "accessibility.css", "accessibility-runtime.js",
    }
    for legacy in legacy_names:
        assert legacy not in index, f"Legacy frontend reference remains: {legacy}"

    required_dom_ids = {
        "chat-form", "chat-input", "send-chat", "ai-mode", "global-search", "chat-list",
        "project-files", "project-calculations", "project-simulations", "project-engineering",
        "calculations-toggle", "calculation-categories", "login-button", "signup-button",
        "account-button",
    }
    for element_id in required_dom_ids:
        assert f'id="{element_id}"' in index, f"Missing DOM contract: {element_id}"

    assert "renderMessages" in app, "Canonical message renderer is missing."
    assert "sendMessage" in app, "Canonical chat send path is missing."
    assert "ui-completion.js" not in app, "app.js should not load the completion layer itself."

    for capability in (
        "renderSettingsPage", "renderProjectsPage", "openSimulationsView",
        "openConnectionsView", "data-customize",
    ):
        assert capability in ui, f"Frontend completion capability missing: {capability}"

    combined = app + ui
    assert 'data-view="planner"' in index, "Planner navigation entry is missing."
    assert "openPlanner" in app, "Planner view controller is missing."
    assert "pasi-planner-order:" in app, "Planner local order state is missing."
    assert "data-planner-move" in app, "Keyboard Planner ordering controls are missing."
    assert "planner-task-list" in app, "Planner task list is missing."

    required_api_prefixes = (
        "/api/planner/roadmap", "/api/auth/logout", "/api/auth/me", "/api/chats", "/api/projects", "/api/manifest",
        "/api/search", "/api/calculations/catalog", "/api/calculations/run",
        "/api/calculations/run/save", "/api/connections", "/api/plugins", "/api/digest",
        "/api/simulations", "/api/simulations/run", "/api/engineering/projects/",
    )
    for endpoint in required_api_prefixes:
        assert endpoint in combined, f"Frontend does not reference backend endpoint: {endpoint}"

    for capability in (
        "rename", "pin", "move", "share", "delete", "retry", "branch", "rate-up", "rate-down",
    ):
        assert capability in combined, f"Chat capability missing: {capability}"

    for capability in (
        "Import GitHub file", "Search sources", "Add evidence", "Invalidate",
        "Run simulation", "Add connection", "Register plugin",
    ):
        assert capability in combined, f"Feature capability missing: {capability}"

    assert "prefers-reduced-motion" in css, "Reduced-motion support is missing."
    assert ":focus-visible" in css, "Keyboard focus styling is missing."


def test_foundation_ux_contracts() -> None:
    """Lock the five foundation invariants before the broader UX pass proceeds."""
    index = (WEB / "index.html").read_text(encoding="utf-8")
    app = (WEB / "app.js").read_text(encoding="utf-8")
    ui = (WEB / "ui-completion.js").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    # One settings renderer and no obsolete CLI/Claude Code settings section.
    assert len(re.findall(r"function\s+renderSettingsPage\s*\(", ui)) == 1
    assert "Claude Code / CLI" not in ui
    assert "Claude Code" not in ui

    # Rounded design tokens are active and the stylesheet does not flatten the UI globally.
    assert "--ui-radius-sm:7px" in css
    assert "--ui-radius-md:10px" in css
    assert "--ui-radius-lg:14px" in css
    assert not re.search(r"\*[^{}]*\{[^{}]*border-radius\s*:\s*0", css)

    # Search and auth controls are present and not hidden by the static shell.
    assert 'id="global-search"' in index
    assert 'id="login-button"' in index
    assert 'id="signup-button"' in index
    assert "global-search" in css
    assert "Ctrl+K" in ui

    # There is exactly one canonical message POST construction.
    message_post = re.findall(r"api\(`?/api/chats/\$\{state\.chatId\}/messages", app)
    assert len(message_post) == 1, f"Expected one chat-message POST path, found {len(message_post)}"
    assert "model:modelOverride||modelProfile(selectedMode)" in app
    assert "auto: 'profile:auto'" in app
    assert "claude: 'profile:claude-opus'" in app
    assert "gpt: 'profile:gpt-5.4'" in app
    assert "gemini: 'profile:gemini-3.1-pro'" in app
    assert "free: 'profile:free'" in app


def test_planner_interactive_workspace_contract() -> None:
    index = (WEB / "index.html").read_text(encoding="utf-8")
    app = (WEB / "app.js").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    for marker in (
        "planner-shell", "planner-sidebar", "planner-topbar", "planner-task-list",
        "planner-right-rail", "planner-graph-canvas", "planner-focus-panel",
        "data-planner-filter", "data-planner-tab", "data-planner-graph-task",
        "data-planner-run-control", "data-planner-integration", "data-planner-nav",
        "planner-sidebar-collapsed", "pasi-planner-draft:", "pasi-planner-order:",
    ):
        assert marker in app, f"Planner interaction contract missing: {marker}"

    for marker in (
        ".planner-shell", ".planner-sidebar", ".planner-task-card",
        ".planner-focus-panel", ".planner-graph-node", ".planner-right-rail",
        ".planner-rail-card", ".planner-detail-modal", ".planner-loading",
        ".planner-sidebar-collapsed",
    ):
        assert marker in css, f"Planner styling contract missing: {marker}"

    assert 'data-view="planner"' in index


def test_engineering_workspace_redesign_contract() -> None:
    index = (WEB / "index.html").read_text(encoding="utf-8")
    ui = (WEB / "ui-completion.js").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    assert "PASI Engineering" in index
    assert "New engineering session" in index
    for marker in (
        "engineering-control-center", "engineering-health-strip",
        "engineering-requirement-list", "engineering-source-grid",
        "engineering-coverage-panel", "engineering-decision-list",
        "engineering-action-row", "engineering-requirement-search",
        "engineering-requirement-filter", "data-engineering-requirement-detail",
        "data-engineering-source-detail",
    ):
        assert marker in ui, f"Engineering workspace interaction contract missing: {marker}"

    for marker in (
        ".engineering-control-center", ".engineering-health-strip",
        ".engineering-requirement", ".engineering-source-card",
        ".engineering-coverage-ring", ".engineering-decision-card",
        ".engineering-action-row", ".engineering-detail-modal",
    ):
        assert marker in css, f"Engineering workspace styling contract missing: {marker}"


def test_engineering_requirement_detail_contract() -> None:
    ui = (WEB / "ui-completion.js").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    for marker in (
        "engineering-requirement-detail",
        "engineering-detail-health",
        "engineering-verification-checks",
        "engineering-detail-evidence-list",
        "engineering-source-trace",
        "engineering-linked-decisions",
        "engineering-trace-list",
        "engineering-timeline",
        "engineering-detail-properties",
        "engineeringRequirementEditForm",
        "requirement_id=Number(requirementId)",
    ):
        assert marker in ui, f"Requirement detail interaction contract missing: {marker}"

    for marker in (
        ".engineering-requirement-detail",
        ".engineering-detail-health",
        ".engineering-evidence-card",
        ".engineering-source-trace-card",
        ".engineering-linked-decision",
        ".engineering-trace-row",
        ".engineering-timeline-item",
        ".engineering-detail-properties",
    ):
        assert marker in css, f"Requirement detail styling contract missing: {marker}"

def test_requirement_history_frontend_backend_contract() -> None:
    ui = (WEB / "ui-completion.js").read_text(encoding="utf-8")
    assert "/api/engineering/projects/${s.projectId}/requirements/${requirement.id}/history" in ui
    assert "historyError" in ui
    assert "data-engineering-history-refresh" in ui
    assert "Backend-authoritative history" in ui
    assert "requirement_field_changed" in ui
    assert "old_value" in ui
    assert "new_value" in ui
    assert "engineering-timeline-change" in ui
