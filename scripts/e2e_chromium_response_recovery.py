#!/usr/bin/env python3
"""Minimized Chromium acceptance test for PASI late-response recovery."""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[1]
BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 8765
OPERATION_ID = "pasi-e2e-late-response"
EXPECTED_RESPONSE = "response recovered by the real Chromium controller"


class BridgeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    finished_payload: dict | None = None
    observations = 0

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/operation":
            operation_id = parse_qs(parsed.query).get("operation_id", [""])[0]
            if operation_id != OPERATION_ID:
                self._send_json(404, {"error": "operation not found"})
                return
            self._send_json(
                200,
                {
                    "operation": {
                        "operation_id": OPERATION_ID,
                        "operation_type": "prompt",
                        "status": "completed",
                        "response_text": "",
                        "response_text_available": False,
                        "created_at": "2026-09-18T00:00:00Z",
                        "updated_at": "2026-09-18T00:00:01Z",
                    }
                },
            )
            return

        if parsed.path == "/next-operation":
            self._send_json(200, {"operation": None})
            return

        if parsed.path == "/status":
            self._send_json(200, {"status": "ok"})
            return

        if parsed.path == "/browser/observation":
            self._send_json(
                200,
                {
                    "observation": {
                        "captured_at": "2026-09-18T00:00:00Z",
                        "data": {"active_operation_id": OPERATION_ID},
                    }
                },
            )
            return

        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        try:
            payload = self._read_json()
        except (ValueError, json.JSONDecodeError):
            self._send_json(400, {"error": "invalid json"})
            return

        if self.path == "/browser/observation":
            BridgeHandler.observations += 1
            self._send_json(200, {"ok": True})
            return

        if self.path == "/chat/finished":
            if payload.get("operation_id") != OPERATION_ID:
                self._send_json(409, {"error": "unexpected operation"})
                return
            if payload.get("response_text_available") is not True:
                self._send_json(409, {"error": "verified response required"})
                return
            response_text = payload.get("response_text")
            if response_text != EXPECTED_RESPONSE:
                self._send_json(409, {"error": "unexpected response evidence"})
                return
            BridgeHandler.finished_payload = payload
            self._send_json(
                200,
                {
                    "operation": {
                        "operation_id": OPERATION_ID,
                        "operation_type": "prompt",
                        "status": "completed",
                        "response_text": EXPECTED_RESPONSE,
                        "response_text_available": True,
                    }
                },
            )
            return

        if self.path == "/chat/failed":
            self._send_json(200, {"ok": True})
            return

        self._send_json(404, {"error": "not found"})

    def log_message(self, _format: str, *_args: object) -> None:
        return


class FixtureHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/fixture":
            html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>PASI Chromium Recovery Fixture</title>
  <script>
    localStorage.setItem("pasi:active-operation", JSON.stringify({{
      operation_id: "{OPERATION_ID}",
      operation_type: "prompt",
      started_at: "2026-09-18T00:00:00Z",
      baseline: "older assistant response",
      chat_url: null
    }}));
  </script>
</head>
<body>
  <div data-message-author-role="assistant">
    <div class="markdown">{EXPECTED_RESPONSE}</div>
  </div>
  <script src="/automation/chromium/pasi-chatgpt/content.js"></script>
</body>
</html>""".encode("utf-8")
            self._send(200, html, "text/html; charset=utf-8")
            return

        if path == "/automation/chromium/pasi-chatgpt/content.js":
            source = (
                ROOT / "automation" / "chromium" / "pasi-chatgpt" / "content.js"
            ).read_bytes()
            self._send(200, source, "text/javascript; charset=utf-8")
            return

        self._send(404, b"not found", "text/plain; charset=utf-8")

    def log_message(self, _format: str, *_args: object) -> None:
        return


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def find_chromium() -> str:
    for candidate in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        path = shutil.which(candidate)
        if path:
            return path
    raise RuntimeError("Chromium binary not found")


def wait_for_bridge_event(timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if BridgeHandler.finished_payload is not None:
            return
        time.sleep(0.1)
    raise AssertionError("Chromium did not submit the recovered response evidence")


def main() -> None:
    BridgeHandler.finished_payload = None
    BridgeHandler.observations = 0

    bridge = ThreadingHTTPServer((BRIDGE_HOST, BRIDGE_PORT), BridgeHandler)
    fixture_port = free_port()
    fixture = ThreadingHTTPServer(("127.0.0.1", fixture_port), FixtureHandler)
    bridge_thread = threading.Thread(target=bridge.serve_forever, daemon=True)
    fixture_thread = threading.Thread(target=fixture.serve_forever, daemon=True)
    bridge_thread.start()
    fixture_thread.start()

    chromium = find_chromium()
    with tempfile.TemporaryDirectory(prefix="pasi-chromium-e2e-") as profile_dir:
        command = [
            chromium,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-sync",
            f"--user-data-dir={profile_dir}",
            f"http://127.0.0.1:{fixture_port}/fixture",
        ]
        process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            wait_for_bridge_event(8.0)
        finally:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
            bridge.shutdown()
            fixture.shutdown()
            bridge.server_close()
            fixture.server_close()

    payload = BridgeHandler.finished_payload
    assert payload is not None
    assert payload["operation_id"] == OPERATION_ID
    assert payload["response_text"] == EXPECTED_RESPONSE
    assert payload["response_text_available"] is True
    assert BridgeHandler.observations >= 1
    print("Minimized Chromium late-response recovery E2E: PASS")


if __name__ == "__main__":
    main()
