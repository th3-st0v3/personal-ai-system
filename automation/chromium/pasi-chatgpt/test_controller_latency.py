from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[3]
TAMPERMONKEY = ROOT / "automation" / "tampermonkey" / "chatgpt-controller.user.js"
NATIVE = ROOT / "automation" / "chromium" / "pasi-chatgpt" / "content.js"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _number(source: str, name: str) -> int:
    match = re.search(rf"(?:var|const)\s+{re.escape(name)}\s*=\s*(\d+)", source)
    assert match, f"missing {name}"
    return int(match.group(1))


def test_tampermonkey_controller_uses_bounded_idle_polling_and_recovery_state() -> None:
    source = _read(TAMPERMONKEY)

    assert "@version      2.4.11" in source
    assert 1000 <= _number(source, "POLL_INTERVAL_MS") <= 5000
    assert _number(source, "DOM_POLL_INTERVAL_MS") <= 100
    assert _number(source, "RETRY_DELAY_MS") <= 150
    assert _number(source, "RESPONSE_SETTLE_MS") <= 250
    assert "var ACTIVE_KEY = 'pasi:active-operation';" in source
    assert "window.__PASI_CHATGPT_ACTIVE_OPERATION__" in source
    assert "localStorage.setItem(ACTIVE_KEY" in source
    assert "localStorage.removeItem(ACTIVE_KEY);" in source
    assert "await recoverInterruptedOperation();" in source


def test_native_controller_uses_bounded_idle_polling() -> None:
    source = _read(NATIVE)

    assert 1000 <= _number(source, "POLL_MS") <= 5000
    assert _number(source, "DOM_POLL_MS") <= 250
    assert _number(source, "CLICK_SETTLE_MS") <= 300
    assert _number(source, "RESPONSE_SETTLE_MS") <= 250
    assert "const ACTIVE_KEY = 'pasi:active-operation';" in source
    assert "localStorage.setItem(ACTIVE_KEY" in source
    assert "localStorage.removeItem(ACTIVE_KEY);" in source


def test_latency_changes_preserve_browser_safety_boundaries() -> None:
    tampermonkey = _read(TAMPERMONKEY)
    native = _read(NATIVE)

    assert "GM_xmlhttpRequest" in tampermonkey
    assert "context limit" in tampermonkey or "conversation has reached its limit" in tampermonkey
    assert "reportFailure" in tampermonkey

    assert "credentials: 'omit'" in native
    assert "captcha" in native
    assert "session has expired" in native
    assert "CHAT_EXHAUSTED" in native
    assert "reportHealth" in native
    assert "payload?.operation?.status === 'completed'" in native
    assert "payload?.operation?.response_text_available === true" in native
    assert "Boolean(payload.operation.response_text.trim())" in native