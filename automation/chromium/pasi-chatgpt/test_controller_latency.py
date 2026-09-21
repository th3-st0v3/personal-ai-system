from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[3]
TAMPERMONKEY = ROOT / "automation" / "legacy" / "tampermonkey" / "chatgpt-controller.user.js"
NATIVE = ROOT / "automation" / "chromium" / "pasi-chatgpt" / "content.js"
BACKGROUND = ROOT / "automation" / "chromium" / "pasi-chatgpt" / "background.js"


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
    policy = __import__("json").loads(
        (ROOT / "automation" / "chromium" / "pasi-chatgpt" / "timeout-policy.json").read_text(
            encoding="utf-8"
        )
    )

    assert policy["controller_poll_ms"] <= 500
    assert policy["dom_poll_ms"] <= 20
    assert policy["click_settle_ms"] <= 20
    assert policy["response_settle_ms"] <= 20
    assert policy["submission_ack_ms"] <= 1000
    assert "const POLL_MS = TIMEOUT_POLICY.pollMs || 500;" in source
    assert "const DOM_POLL_MS = TIMEOUT_POLICY.domPollMs || 20;" in source
    assert "const CLICK_SETTLE_MS = TIMEOUT_POLICY.clickSettleMs || 20;" in source
    assert "const RESPONSE_SETTLE_MS = TIMEOUT_POLICY.responseSettleMs || 20;" in source
    assert "const SUBMISSION_ACK_MS = TIMEOUT_POLICY.submissionAckMs || 1000;" in source
    assert "const ACTIVE_KEY = 'pasi:active-operation';" in source
    assert "localStorage.setItem(ACTIVE_KEY" in source
    assert "localStorage.removeItem(ACTIVE_KEY);" in source


def test_latency_changes_preserve_browser_safety_boundaries() -> None:
    tampermonkey = _read(TAMPERMONKEY)
    native = _read(NATIVE)
    background = _read(BACKGROUND)

    assert "GM_xmlhttpRequest" in tampermonkey
    assert "context limit" in tampermonkey or "conversation has reached its limit" in tampermonkey
    assert "reportFailure" in tampermonkey

    assert "chrome.runtime.sendMessage" in native
    assert "type: 'pasi-bridge-request'" in native
    assert "credentials: 'omit'" in background
    assert "targetAddressSpace" not in background
    assert "http://127.0.0.1:8765" in background
    assert "allowedBridgeRequest(method, path)" in background
    assert "captcha" in native
    assert "session has expired" in native
    assert "CHAT_EXHAUSTED" in native
    assert "reportHealth" in native
    assert "aria-labelledby" in native
    assert "hasAttribute?.('disabled')" in native
    assert "github connection failed" in native
    assert "GitHub repository must be in owner/name form" in native
    assert 'button[data-testid*="model" i]' in native
    assert 'button[aria-label*="model" i]' in native
    assert "extended" in native
    assert "medium|high|extra high" in native
    assert "thinking|think|medium|high|extra high" in native
    assert "findDirectThinkingControl" in native
    assert 'button[data-testid*="intelligence" i]' in native
    assert "fall back to a nearby menu button" in native
    assert "payload?.operation?.status === 'completed'" in native
    assert "payload?.operation?.response_text_available === true" in native
    assert "Boolean(payload.operation.response_text.trim())" in native
    assert "ack_only: true" in native


def test_native_controller_recovers_composer_rerenders_and_stops_invalidated_context_polling() -> None:
    native = _read(NATIVE)

    assert "snapshotUserMessages()" in native
    assert "classifyNewUserMessages" in native
    assert "composer lost the requested prompt before submission after bounded recovery" in native
    assert "composer lost the requested prompt before submission after bounded recovery" in native
    assert "refusing to overwrite" in native
    assert "extensionContextInvalidated" in native
    assert "extension context invalidated; reload the ChatGPT page" in native
    assert "clearInterval(pollTimerId)" in native
    assert "clearInterval(healthTimerId)" in native
    assert "if (extensionContextInvalidated) return;" in native
    assert "return markThinkingUnavailable('current ChatGPT account/model does not expose a usable Thinking model option')" in native or "return markThinkingUnavailable('current ChatGPT account/model does not expose a usable Thinking model option');" in native


def test_native_controller_has_immediate_terminal_poll_and_event_driven_waits() -> None:
    source = _read(NATIVE)

    assert "const POLL_MS = TIMEOUT_POLICY.pollMs || 500;" in source
    assert "const DOM_POLL_MS = TIMEOUT_POLICY.domPollMs || 20;" in source
    assert "function waitUntil(predicate, timeoutMs, pollMs = DOM_POLL_MS)" in source
    assert "new MutationObserver" in source
    assert "queueMicrotask(() =>" in source
    assert "scheduleImmediatePoll()" in source
    assert "clearMonitoringStateFor(operation.operation_id)" in source
    assert "chat_response_received" in source
    assert "prompt_injected" in source
    assert "ui=" in source


def test_native_controller_uses_event_driven_response_capture() -> None:
    source = _read(NATIVE)

    assert "async function waitForResponse(baseline)" in source
    assert "const response = await waitUntil(() =>" in source
    assert "let sawGeneration = false" in source
    assert "PASI_NATIVE: ChatGPT generation timed out" in source
    assert "const MAX_RESPONSE_TEXT_CHARS = 120_000;" in source