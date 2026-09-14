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

    # The frontend was intentionally consolidated to these four canonical files.
    expected_files = {
        "app.js",
        "index.html",
        "styles.css",
        "ui-completion.js",
    }

    actual_files = {
        path.name for path in WEB.iterdir() if path.is_file()
    }

    assert actual_files == expected_files, (
        f"Unexpected frontend files: "
        f"{sorted(actual_files ^ expected_files)}"
    )

    # All four canonical files must exist and be non-empty.
    for filename in expected_files:
        path = WEB / filename
        assert path.is_file(), f"Missing canonical frontend file: {filename}"
        assert path.stat().st_size > 0, f"Empty frontend file: {filename}"

    # index.html must load only the canonical JavaScript entrypoints.
    script_sources = set(
        re.findall(r'<script[^>]+src="([^"]+)"', index)
    )

    expected_scripts = {
        "/app.js",
        "/ui-completion.js",
    }

    assert script_sources == expected_scripts, (
        f"Unexpected script entrypoints: {sorted(script_sources)}"
    )

    assert (
        'href="/styles.css"' in index
    ), "Canonical stylesheet is not loaded."

    # Deleted frontend layers must not be referenced by index.html.
    legacy_names = {
        "backend-frontend-bridge.js",
        "backend-final.js",
        "production-ui.js",
        "final-interactions.js",
        "engineering-final.js",
        "ux-final.js",
        "auth-ui.js",
        "pdf-ui.js",
        "final-controls.js",
        "app.css",
        "design-system.css",
        "accessibility.css",
        "accessibility-runtime.js",
    }

    for legacy in legacy_names:
        assert legacy not in index, (
            f"Legacy frontend reference remains: {legacy}"
        )

    # Core browser DOM contract.
    required_dom_ids = {
        "chat-form",
        "chat-input",
        "send-chat",
        "ai-mode",
        "global-search",
        "chat-list",
        "project-files",
        "project-calculations",
        "project-simulations",
        "project-engineering",
        "calculations-toggle",
        "calculation-categories",
        "login-button",
        "signup-button",
        "account-button",
    }

    for element_id in required_dom_ids:
        assert f'id="{element_id}"' in index, (
            f"Missing DOM contract: {element_id}"
        )

    # Canonical interaction ownership.
    assert "renderMessages" in app, (
        "Canonical message renderer is missing."
    )
    assert "sendMessage" in app, (
        "Canonical chat send path is missing."
    )
    assert "ui-completion.js" not in app, (
        "app.js should not load the completion layer itself."
    )

    # Feature/navigation ownership remains in the completion layer.
    for capability in (
        "renderSettingsPage",
        "renderProjectsPage",
        "openSimulationsView",
        "openConnectionsView",
        "data-customize",
    ):
        assert capability in ui, (
            f"Frontend completion capability missing: {capability}"
        )

    combined = app + ui

    # Important backend contracts used by the current frontend.
    required_api_prefixes = (
        "/api/auth/logout",
        "/api/auth/me",
        "/api/chats",
        "/api/projects",
        "/api/manifest",
        "/api/search",
        "/api/calculations/catalog",
        "/api/calculations/run",
        "/api/calculations/run/save",
        "/api/connections",
        "/api/plugins",
        "/api/digest",
        "/api/simulations",
        "/api/simulations/run",
        "/api/engineering/projects/",
    )

    for endpoint in required_api_prefixes:
        assert endpoint in combined, (
            f"Frontend does not reference backend endpoint: {endpoint}"
        )

    # Basic chat capabilities.
    for capability in (
        "rename",
        "pin",
        "move",
        "share",
        "delete",
        "retry",
        "branch",
        "rate-up",
        "rate-down",
    ):
        assert capability in combined, (
            f"Chat capability missing: {capability}"
        )

    # Engineering/workspace capabilities.
    for capability in (
        "Import GitHub file",
        "Search sources",
        "Add evidence",
        "Invalidate",
        "Run simulation",
        "Add connection",
        "Register plugin",
    ):
        assert capability in combined, (
            f"Feature capability missing: {capability}"
        )

    # Accessibility/reduced-motion styling remains in the consolidated stylesheet.
    assert "prefers-reduced-motion" in css, (
        "Reduced-motion support is missing."
    )
    assert ":focus-visible" in css, (
        "Keyboard focus styling is missing."
    )
