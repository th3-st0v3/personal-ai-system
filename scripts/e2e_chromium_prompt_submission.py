#!/usr/bin/env python3
"""Chromium acceptance test for non-duplicating prompt submission and fast operation chaining."""

from __future__ import annotations

import json
import shutil
import ssl
import socket
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_chromium_extension import build_extension
from scripts.e2e_chromium_response_recovery import (
    BrowserCdpClient,
    find_chrome,
    free_port,
    generate_fixture_certificate,
    read_devtools_browser_endpoint,
    runtime_evaluate,
    start_chrome,
    stop_chrome,
    wait_for_extension_marker,
)

BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 8765
CHAT_PATH = "/c/pasi-prompt-submission"
OPERATIONS = [
    {
        "operation_id": "pasi-e2e-prompt-1",
        "operation_type": "prompt",
        "prompt": "PASI-BEGIN-" + ("long repository patch context " * 1200) + "-PASI-END",
        "response_text": "first response completed",
    },
    {
        "operation_id": "pasi-e2e-prompt-2",
        "operation_type": "prompt",
        "prompt": "second queued prompt",
        "response_text": "second response completed",
    },
]


class BridgeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    lock = threading.Lock()
    next_index = 0
    current_status: dict[str, str] = {}
    finished_at: dict[str, float] = {}
    submit_chain: list[float] = []
    prompt_injected_events: list[float] = []
    finished_payloads: list[dict] = []
    failures: list[dict] = []
    observations: list[dict] = []

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    @classmethod
    def reset(cls) -> None:
        with cls.lock:
            cls.next_index = 0
            cls.current_status = {item["operation_id"]: "queued" for item in OPERATIONS}
            cls.finished_at = {}
            cls.submit_chain = []
            cls.prompt_injected_events = []
            cls.finished_payloads = []
            cls.failures = []
            cls.observations = []

    @classmethod
    def operation(cls, operation_id: str) -> dict | None:
        for item in OPERATIONS:
            if item["operation_id"] == operation_id:
                return {
                    "operation_id": item["operation_id"],
                    "operation_type": item["operation_type"],
                    "prompt": item["prompt"],
                    "status": cls.current_status.get(operation_id, "queued"),
                    "response_text": item["response_text"]
                    if cls.current_status.get(operation_id) == "completed"
                    else "",
                    "response_text_available": cls.current_status.get(operation_id) == "completed",
                }
        return None

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        query = parse_qs(urlparse(self.path).query)

        if path == "/next-operation":
            with self.lock:
                if self.next_index < len(OPERATIONS):
                    operation = OPERATIONS[self.next_index]
                    if self.current_status[operation["operation_id"]] == "queued":
                        self.current_status[operation["operation_id"]] = "claimed"
                        self.next_index += 1
                        self._send_json(200, {"operation": self.operation(operation["operation_id"])})
                        return
                self._send_json(200, {"operation": None})
                return

        if path == "/operation":
            operation_id = query.get("operation_id", [""])[0]
            operation = self.operation(operation_id)
            if operation is None:
                self._send_json(404, {"error": "operation not found"})
                return
            self._send_json(200, {"operation": operation})
            return

        if path == "/status":
            self._send_json(200, {"status": "ok"})
            return

        if path == "/browser/observation":
            self._send_json(200, {"observation": {"data": {"active_operation_id": None}}})
            return

        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            payload = self._read_json()
        except (ValueError, json.JSONDecodeError):
            self._send_json(400, {"error": "invalid json"})
            return

        if path == "/browser/observation":
            with self.lock:
                self.observations.append(payload)
                observation = payload.get("observation") if isinstance(payload, dict) else None
                data = observation.get("data") if isinstance(observation, dict) else None
                if isinstance(data, dict) and data.get("kind") == "prompt_injected":
                    self.prompt_injected_events.append(time.monotonic())
            self._send_json(200, {"ok": True})
            return

        if path == "/chat/finished":
            operation_id = payload.get("operation_id")
            if not isinstance(operation_id, str) or not operation_id:
                self._send_json(400, {"error": "operation_id must be a non-empty string"})
                return
            expected = next((item for item in OPERATIONS if item["operation_id"] == operation_id), None)
            if expected is None:
                self._send_json(409, {"error": "unexpected operation"})
                return
            if payload.get("response_text_available") is not True:
                self._send_json(409, {"error": "verified response required"})
                return
            if payload.get("response_text") != expected["response_text"]:
                self._send_json(409, {"error": "unexpected response evidence"})
                return
            with self.lock:
                self.current_status[operation_id] = "completed"
                self.finished_at[operation_id] = time.monotonic()
                self.finished_payloads.append(payload)
                if operation_id == OPERATIONS[0]["operation_id"] and len(self.finished_payloads) == 1:
                    self.current_status[OPERATIONS[1]["operation_id"]] = "queued"
            self._send_json(200, {"operation": self.operation(operation_id)})
            return

        if path == "/chat/failed":
            with self.lock:
                self.failures.append(payload)
            self._send_json(200, {"ok": True})
            return

        self._send_json(404, {"error": "not found"})

    def log_message(self, _format: str, *_args: object) -> None:
        return


class FixtureHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    submit_count = 0
    submit_times: list[float] = []
    submitted_values: list[str] = []

    @classmethod
    def reset(cls) -> None:
        cls.submit_count = 0
        cls.submit_times = []
        cls.submitted_values = []

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if urlparse(self.path).path != CHAT_PATH:
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return

        html = r"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>PASI Prompt Submission Fixture</title>
<style>
#composer-form { display: block; }
#prompt-textarea { width: 700px; height: 90px; }
</style>
</head>
<body>
<form id="composer-form">
  <textarea id="prompt-textarea" aria-label="Message"></textarea>
  <button id="thinking" type="button" aria-pressed="true">Thinking</button>
  <button id="send" data-testid="send-button" type="submit" aria-label="Send prompt">Send</button>
</form>
<div id="messages"></div>
<script>
const EXPECTED_RESPONSES = ["first response completed", "second response completed"];
const form = document.getElementById("composer-form");
const composer = document.getElementById("prompt-textarea");
const messages = document.getElementById("messages");
window.fixtureSubmissionCount = 0;
window.submittedValues = [];

function addUserMessage(prompt) {
  const node = document.createElement("div");
  node.setAttribute("data-message-author-role", "user");
  node.setAttribute("data-message-id", "fixture-user-" + window.fixtureSubmissionCount);

  // Simulate ChatGPT's long-message rendering/virtualization: the visible
  // bubble contains the beginning and end, not the full prompt text.
  const normalized = String(prompt).replace(/\s+/g, " ").trim();
  node.textContent = normalized.slice(0, 80) + " … [clamped] … " + normalized.slice(-80);
  messages.appendChild(node);
}

function addAssistantMessage(text) {
  const node = document.createElement("div");
  node.setAttribute("data-message-author-role", "assistant");
  node.innerHTML = '<div class="markdown"></div>';
  node.querySelector(".markdown").textContent = text;
  messages.appendChild(node);
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  window.fixtureSubmissionCount += 1;
  const current = composer.value;
  window.submittedValues.push(current);
  window.submitValue = current;
  composer.value = "";
  composer.dispatchEvent(new Event("input", { bubbles: true }));
  addUserMessage(current);

  const stop = document.createElement("button");
  stop.setAttribute("data-testid", "stop-button", "");
  stop.textContent = "Stop generating";
  messages.appendChild(stop);

  window.setTimeout(() => {
    stop.remove();
    addAssistantMessage(EXPECTED_RESPONSES[window.fixtureSubmissionCount - 1] || "unexpected response");
  }, 80);
});
</script>
</body>
</html>""".encode("utf-8")
        self._send(200, html, "text/html; charset=utf-8")

    def log_message(self, _format: str, *_args: object) -> None:
        return


def main() -> None:
    BridgeHandler.reset()
    FixtureHandler.reset()

    bridge = ThreadingHTTPServer((BRIDGE_HOST, BRIDGE_PORT), BridgeHandler)
    fixture_port = free_port()
    fixture = ThreadingHTTPServer(("127.0.0.1", fixture_port), FixtureHandler)

    with tempfile.TemporaryDirectory(prefix="pasi-prompt-submission-tls-") as tls_root:
        cert_path = Path(tls_root) / "cert.pem"
        key_path = Path(tls_root) / "key.pem"
        generate_fixture_certificate(cert_path, key_path)
        tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls_context.load_cert_chain(certfile=cert_path, keyfile=key_path)
        fixture.socket = tls_context.wrap_socket(fixture.socket, server_side=True)

        bridge_thread = threading.Thread(target=bridge.serve_forever, daemon=True)
        fixture_thread = threading.Thread(target=fixture.serve_forever, daemon=True)
        bridge_thread.start()
        fixture_thread.start()

        chrome_process = None
        cdp = None
        browser_session = None
        target_id = None
        try:
            chrome_binary = find_chrome()
            with (
                tempfile.TemporaryDirectory(prefix="pasi-prompt-submission-profile-") as profile_root,
                tempfile.TemporaryDirectory(prefix="pasi-prompt-submission-extension-") as extension_root,
                tempfile.NamedTemporaryFile(prefix="pasi-prompt-submission-", suffix=".log", delete=False) as log_file,
            ):
                extension_dir = build_extension(Path(extension_root) / "pasi-chatgpt")
                debug_port = free_port()
                profile_dir = Path(profile_root) / "profile"
                profile_dir.mkdir()

                chrome_process = start_chrome(chrome_binary, debug_port, profile_dir, log_file)
                websocket_url = read_devtools_browser_endpoint(debug_port)
                cdp = BrowserCdpClient(websocket_url)

                loaded = cdp.command("Extensions.loadUnpacked", {"path": str(extension_dir)}, timeout=15.0)
                extension_id = loaded.get("id")
                if not isinstance(extension_id, str) or not extension_id:
                    raise RuntimeError(f"Extensions.loadUnpacked returned no extension id: {loaded}")

                created = cdp.command("Target.createTarget", {"url": "about:blank"}, timeout=10.0)
                target_id = created.get("targetId")
                if not isinstance(target_id, str) or not target_id:
                    raise RuntimeError(f"Target.createTarget returned invalid target: {created}")

                attached = cdp.command("Target.attachToTarget", {"targetId": target_id, "flatten": True}, timeout=10.0)
                browser_session = attached.get("sessionId")
                if not isinstance(browser_session, str) or not browser_session:
                    raise RuntimeError(f"Target.attachToTarget returned no session id: {attached}")

                cdp.command("Page.enable", session_id=browser_session)
                cdp.command("Runtime.enable", session_id=browser_session)
                cdp.command(
                    "Page.navigate",
                    {"url": f"https://chatgpt.com:{fixture_port}{CHAT_PATH}"},
                    session_id=browser_session,
                    timeout=10.0,
                )
                wait_for_extension_marker(cdp, browser_session, timeout=10.0)

                deadline = time.monotonic() + 60.0
                while time.monotonic() < deadline:
                    state = runtime_evaluate(
                        cdp,
                        browser_session,
                        """({
                          submissions: window.fixtureSubmissionCount || 0,
                          users: document.querySelectorAll('[data-message-author-role="user"]').length,
                          assistants: document.querySelectorAll('[data-message-author-role="assistant"]').length,
                          active: localStorage.getItem("pasi:active-operation"),
                          url: location.href
                        })""",
                    )
                    if (
                        isinstance(state, dict)
                        and state.get("submissions") == 2
                        and state.get("users") == 2
                        and state.get("assistants") == 2
                        and state.get("active") is None
                    ):
                        break
                    time.sleep(0.1)
                else:
                    with BridgeHandler.lock:
                        bridge_debug = {
                            "next_index": BridgeHandler.next_index,
                            "current_status": dict(BridgeHandler.current_status),
                            "finished_at": dict(BridgeHandler.finished_at),
                            "prompt_injected_events": list(BridgeHandler.prompt_injected_events),
                            "failures": list(BridgeHandler.failures),
                            "observations": [
                                item.get("observation", {}).get("data", {}).get("kind")
                                for item in BridgeHandler.observations
                                if isinstance(item, dict)
                            ],
                        }
                    raise AssertionError(
                        "Prompt submission fixture did not complete both operations: "
                        f"page={state!r} bridge={bridge_debug!r}"
                    )

                final = runtime_evaluate(
                    cdp,
                    browser_session,
                    """({
                      submissions: window.fixtureSubmissionCount || 0,
                      submittedValues: Array.isArray(window.submittedValues) ? window.submittedValues : [],
                      users: Array.from(document.querySelectorAll('[data-message-author-role="user"]')).map((node) => node.textContent),
                      assistants: Array.from(document.querySelectorAll('[data-message-author-role="assistant"]')).map((node) => node.innerText),
                      active: localStorage.getItem("pasi:active-operation")
                    })""",
                )
                if not isinstance(final, dict):
                    raise RuntimeError(f"Final fixture state invalid: {final!r}")

                if final["submissions"] != 2:
                    raise AssertionError(f"Expected exactly 2 form submissions, got {final}")
                if final["active"] is not None:
                    raise AssertionError(f"Active operation marker was not cleared: {final}")

                if len(FixtureHandler.submitted_values) >= 2:
                    first_prompt, second_prompt = FixtureHandler.submitted_values[:2]
                    if first_prompt != OPERATIONS[0]["prompt"]:
                        raise AssertionError("First submitted prompt was modified before send")
                    if second_prompt != OPERATIONS[1]["prompt"]:
                        raise AssertionError("Second submitted prompt was modified before send")

                with BridgeHandler.lock:
                    first_finished = BridgeHandler.finished_at.get(OPERATIONS[0]["operation_id"])
                    second_finished = BridgeHandler.finished_at.get(OPERATIONS[1]["operation_id"])
                    failures = list(BridgeHandler.failures)
                    finished_payloads = list(BridgeHandler.finished_payloads)

                if first_finished is None or second_finished is None:
                    raise AssertionError(
                        f"Expected two verified completions, got finished payloads={finished_payloads}"
                    )
                if failures:
                    raise AssertionError(f"Unexpected browser failure callbacks: {failures}")

                # The controller emits prompt_injected immediately after its
                # send strategy returns. Comparing that second telemetry event
                # with the first /chat/finished receipt measures the actual
                # completion-to-next-injection handoff without a synthetic timer.
                completion_to_second_submit = None
                if len(BridgeHandler.prompt_injected_events) >= 2:
                    completion_to_second_submit = (
                        BridgeHandler.prompt_injected_events[1] - first_finished
                    )
                if (
                    completion_to_second_submit is None
                    or completion_to_second_submit < 0
                    or completion_to_second_submit > 0.5
                ):
                    raise AssertionError(
                        "Completion-to-next-prompt latency exceeded 500 ms: "
                        f"{completion_to_second_submit!r}s"
                    )

                print(
                    "Chromium prompt submission + immediate chaining: PASS "
                    f"(completion_to_second_submit={completion_to_second_submit * 1000:.1f} ms)"
                )
        finally:
            if cdp is not None and target_id:
                try:
                    cdp.command("Target.closeTarget", {"targetId": target_id}, timeout=5.0)
                except Exception:
                    pass
            if cdp is not None:
                cdp.close()
            stop_chrome(chrome_process)

        bridge.shutdown()
        fixture.shutdown()
        bridge.server_close()
        fixture.server_close()


if __name__ == "__main__":
    main()
