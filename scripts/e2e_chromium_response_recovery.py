#!/usr/bin/env python3
"""Minimized Chromium acceptance test for PASI late-response recovery."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen


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


def find_chrome() -> str:
    for candidate in (
        "google-chrome-stable",
        "google-chrome",
        "chromium",
        "chromium-browser",
    ):
        path = shutil.which(candidate)
        if path:
            return path
    raise RuntimeError("Chrome/Chromium binary not found")


def find_chromedriver() -> str:
    env_path = os.environ.get("CHROMEWEBDRIVER", "").strip()
    candidates = [
        shutil.which("chromedriver"),
        "/usr/local/bin/chromedriver",
        "/usr/bin/chromedriver",
    ]
    if env_path:
        candidates.extend(
            [
                env_path,
                str(Path(env_path) / "chromedriver"),
                str(Path(env_path) / "chromedriver-linux64" / "chromedriver"),
            ]
        )
    candidates.append("/usr/local/share/chromedriver-linux64/chromedriver")

    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise RuntimeError("ChromeDriver binary not found")


def driver_request(
    base_url: str,
    method: str,
    path: str,
    payload: dict | None = None,
    timeout: float = 5.0,
) -> dict:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        base_url + path,
        data=body,
        headers={"Content-Type": "application/json"} if body is not None else {},
        method=method,
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"ChromeDriver {method} {path} returned HTTP {exc.code}: {detail}"
        ) from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"ChromeDriver {method} {path} failed: {exc}") from exc


def wait_for_driver(base_url: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            payload = driver_request(base_url, "GET", "/status", timeout=2.0)
            if payload.get("value", {}).get("ready") is True:
                return
            last_error = RuntimeError(f"ChromeDriver not ready: {payload}")
        except Exception as exc:  # pragma: no cover - diagnostic retry loop
            last_error = exc
        time.sleep(0.1)
    raise RuntimeError(f"ChromeDriver did not become ready: {last_error}")


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

    driver_port = free_port()
    chrome_binary = find_chrome()
    chromedriver_binary = find_chromedriver()

    with (
        tempfile.TemporaryDirectory(prefix="pasi-chromium-e2e-") as profile_dir,
        tempfile.NamedTemporaryFile(
            prefix="pasi-chromedriver-", suffix=".log", delete=False
        ) as log_file,
    ):
        driver_log_path = Path(log_file.name)
        driver_process = subprocess.Popen(
            [
                chromedriver_binary,
                f"--port={driver_port}",
                "--host=127.0.0.1",
                "--log-level=SEVERE",
            ],
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )

        driver_url = f"http://127.0.0.1:{driver_port}"
        session_id: str | None = None
        try:
            wait_for_driver(driver_url, 10.0)
            created = driver_request(
                driver_url,
                "POST",
                "/session",
                {
                    "capabilities": {
                        "alwaysMatch": {
                            "browserName": "chrome",
                            "goog:chromeOptions": {
                                "binary": chrome_binary,
                                "args": [
                                    "--headless=new",
                                    "--no-sandbox",
                                    "--disable-gpu",
                                    "--disable-dev-shm-usage",
                                    "--no-first-run",
                                    "--no-default-browser-check",
                                    "--disable-sync",
                                    "--remote-allow-origins=*",
                                    f"--user-data-dir={profile_dir}",
                                ],
                            },
                        }
                    }
                },
                timeout=10.0,
            )
            value = created.get("value")
            if not isinstance(value, dict):
                raise RuntimeError(f"ChromeDriver returned invalid session payload: {created}")
            session_id = value.get("sessionId") or created.get("sessionId")
            if not isinstance(session_id, str) or not session_id:
                raise RuntimeError(f"ChromeDriver did not return a session id: {created}")

            driver_request(
                driver_url,
                "POST",
                f"/session/{session_id}/url",
                {"url": f"http://127.0.0.1:{fixture_port}/fixture"},
                timeout=10.0,
            )

            diagnostics = driver_request(
                driver_url,
                "POST",
                f"/session/{session_id}/execute/sync",
                {
                    "script": """return {
                      href: location.href,
                      active: localStorage.getItem("pasi:active-operation"),
                      response: document.querySelector('[data-message-author-role="assistant"]')?.innerText || ""
                    };""",
                    "args": [],
                },
                timeout=5.0,
            )
            browser_state = diagnostics.get("value")
            if not isinstance(browser_state, dict):
                raise RuntimeError(f"Chromium fixture did not return browser state: {diagnostics}")
            if browser_state.get("response") != EXPECTED_RESPONSE:
                raise AssertionError(f"Chromium fixture response mismatch: {browser_state}")

            wait_for_bridge_event(20.0)

            completed_state = driver_request(
                driver_url,
                "POST",
                f"/session/{session_id}/execute/sync",
                {
                    "script": """return {
                      href: location.href,
                      active: localStorage.getItem("pasi:active-operation")
                    };""",
                    "args": [],
                },
                timeout=5.0,
            )
            final_browser_state = completed_state.get("value")
            if not isinstance(final_browser_state, dict):
                raise RuntimeError(
                    f"Chromium post-recovery state was invalid: {completed_state}"
                )
            if final_browser_state.get("active") is not None:
                raise AssertionError(
                    f"Chromium recovery marker was not cleared after completion: {final_browser_state}"
                )
        except Exception as exc:
            try:
                diagnostic = driver_request(
                    driver_url,
                    "POST",
                    f"/session/{session_id}/execute/sync",
                    {"script": "return {href: location.href, body: document.body?.innerText || ''};", "args": []},
                    timeout=2.0,
                ) if session_id else None
            except Exception:
                diagnostic = None
            driver_process.terminate()
            try:
                driver_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                driver_process.kill()
                driver_process.wait(timeout=3)
            driver_log = driver_log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
            raise AssertionError(
                f"Chromium WebDriver acceptance failed: {exc}; "
                f"browser={diagnostic}; chromedriver_log={driver_log}"
            ) from exc
        finally:
            if session_id:
                try:
                    driver_request(
                        driver_url,
                        "DELETE",
                        f"/session/{session_id}",
                        timeout=3.0,
                    )
                except Exception:
                    pass
            if driver_process.poll() is None:
                driver_process.terminate()
                try:
                    driver_process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    driver_process.kill()
                    driver_process.wait(timeout=3)
            bridge.shutdown()
            fixture.shutdown()
            bridge.server_close()
            fixture.server_close()
        driver_log_path.unlink(missing_ok=True)

    payload = BridgeHandler.finished_payload
    assert payload is not None
    assert payload["operation_id"] == OPERATION_ID
    assert payload["response_text"] == EXPECTED_RESPONSE
    assert payload["response_text_available"] is True
    assert BridgeHandler.observations >= 1
    print("Minimized Chromium late-response recovery WebDriver E2E: PASS")


if __name__ == "__main__":
    main()
