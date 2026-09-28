from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NATIVE_BACKGROUND = ROOT / "automation" / "chromium" / "pasi-chatgpt" / "background.js"


def test_native_recovery_preserves_existing_tabs_without_navigation():
    source = NATIVE_BACKGROUND.read_text(encoding="utf-8")
    assert "injectExistingChatTabs" in source
    assert "chrome.tabs.query" in source
    assert "chrome.scripting.executeScript" in source
    assert "chrome.tabs.create" not in source
    assert "chrome.tabs.reload" not in source
    assert "chrome.tabs.update" not in source


def test_native_recovery_reinjects_existing_controller_after_startup():
    source = NATIVE_BACKGROUND.read_text(encoding="utf-8")
    assert "chrome.runtime.onStartup" in source
    assert "void injectExistingChatTabs();" in source
    assert "pasi-health-ping" in source
