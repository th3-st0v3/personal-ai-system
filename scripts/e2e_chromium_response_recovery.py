#!/usr/bin/env python3
"""Minimized Chromium acceptance test for PASI late-response recovery."""

from __future__ import annotations

import json
import os
import shutil
import signal
import ssl
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
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_chromium_extension import build_extension
BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 8765
OPERATION_ID = "pasi-e2e-late-response"
EXPECTED_RESPONSE = """PASI_RESULT_STATUS: complete
PASI_RESULT_SUMMARY: multiline Chromium seam recovery
PASI_RESULT_NEXT_TASK: continue with the next incomplete task
PASI_RESULT_REQUIREMENTS: complete
PASI_RESULT_LIMITATIONS: handled
PASI_RESULT_RESEARCH: not_applicable
PASI_RESULT_UX: verified
PASI_RESULT_BACKEND: verified
PASI_RESULT_EVIDENCE: real Chromium DOM preserved parser contract line breaks
PASI_RESULT_REPOSITORY_PROGRESS: changed
PASI_RESULT_ALLOW_DELETE: false
PASI_RESULT_PATCH_BEGIN
diff --git a/example.txt b/example.txt
--- a/example.txt
+++ b/example.txt
@@ -1 +1 @@
-old
+new
PASI_RESULT_PATCH_END""";
CHROMEDRIVER_SESSION_START_TIMEOUT_SECONDS = 45.0
CHROMEDRIVER_START_ATTEMPTS = 2


class BridgeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    finished_payload: dict | None = None
    observations = 0
    observation_payloads: list[dict] = []
    requests: list[dict] = []

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
        BridgeHandler.requests.append({"method": "GET", "path": self.path})
        BridgeHandler.requests = BridgeHandler.requests[-50:]
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
        BridgeHandler.requests.append({"method": "POST", "path": self.path})
        BridgeHandler.requests = BridgeHandler.requests[-50:]
        try:
            payload = self._read_json()
        except (ValueError, json.JSONDecodeError):
            self._send_json(400, {"error": "invalid json"})
            return

        if self.path == "/browser/observation":
            BridgeHandler.observations += 1
            BridgeHandler.observation_payloads.append(payload)
            BridgeHandler.observation_payloads = BridgeHandler.observation_payloads[-20:]
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
  <nav>Sidebar examples mention captcha and cloudflare.</nav>
  <main>
    <div data-message-author-role="user">A normal message can quote rate limit, captcha, and context limit reached without changing provider state.</div>
    <div data-message-author-role="assistant">
      <div class="markdown"><pre>{EXPECTED_RESPONSE}</pre></div>
    </div>
  </main>
</body>
</html>""".encode("utf-8")
            self._send(200, html, "text/html; charset=utf-8")
            return

        self._send(404, b"not found", "text/plain; charset=utf-8")

    def log_message(self, _format: str, *_args: object) -> None:
        return


def generate_fixture_certificate(cert_path: Path, key_path: Path) -> None:
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(key_path),
            "-out",
            str(cert_path),
            "-days",
            "1",
            "-nodes",
            "-subj",
            "/CN=chatgpt.com",
            "-addext",
            "subjectAltName=DNS:chatgpt.com",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


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


def read_browser_logs(base_url: str, session_id: str) -> list[dict]:
    try:
        payload = driver_request(
            base_url,
            "POST",
            f"/session/{session_id}/log",
            {"type": "browser"},
            timeout=3.0,
        )
        value = payload.get("value")
        return value if isinstance(value, list) else []
    except Exception:
        return []


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


def execute_cdp_command(
    driver_url: str,
    session_id: str,
    command: str,
    params: dict | None = None,
    timeout: float = 10.0,
) -> dict:
    payload = driver_request(
        driver_url,
        "POST",
        f"/session/{session_id}/goog/cdp/execute",
        {"cmd": command, "params": params or {}},
        timeout=timeout,
    )
    value = payload.get("value")
    if not isinstance(value, dict):
        raise RuntimeError(f"ChromeDriver CDP {command} returned invalid payload: {payload}")
    return value


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


def wait_for_health_observation(timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(
            isinstance(item.get("observation", {}), dict)
            and item.get("observation", {}).get("data", {}).get("kind") == "chatgpt_health"
            for item in BridgeHandler.observation_payloads
        ):
            return
        time.sleep(0.1)
    raise AssertionError("Chromium did not report native health observation")


def start_driver(
    chromedriver_binary: str,
    driver_port: int,
    log_file,
) -> subprocess.Popen:
    return subprocess.Popen(
        [
            chromedriver_binary,
            f"--port={driver_port}",
            "--host=127.0.0.1",
            "--log-level=SEVERE",
        ],
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )


def stop_driver(driver_process: subprocess.Popen | None) -> None:
    if driver_process is None or driver_process.poll() is not None:
        return
    driver_process.terminate()
    try:
        driver_process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        driver_process.kill()
        driver_process.wait(timeout=3)


def read_devtools_browser_endpoint(port: int, timeout: float = 15.0) -> str:
    url = f"http://127.0.0.1:{port}/json/version"
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urlopen(Request(url), timeout=2.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
            endpoint = payload.get("webSocketDebuggerUrl")
            if isinstance(endpoint, str) and endpoint:
                return endpoint
            last_error = RuntimeError(f"DevTools endpoint missing from response: {payload}")
        except Exception as exc:  # pragma: no cover - bounded startup retry
            last_error = exc
        time.sleep(0.1)
    raise RuntimeError(f"Chrome DevTools endpoint did not become available: {last_error}")


class BrowserCdpClient:
    def __init__(self, websocket_url: str) -> None:
        from websockets.sync.client import connect

        self.websocket = connect(
            websocket_url,
            open_timeout=15,
            close_timeout=5,
            ping_interval=20,
            ping_timeout=20,
            max_size=16 * 1024 * 1024,
            proxy=None,
        )
        self._next_id = 0

    def command(
        self,
        method: str,
        params: dict | None = None,
        *,
        session_id: str | None = None,
        timeout: float = 15.0,
    ) -> dict:
        self._next_id += 1
        request_id = self._next_id
        payload: dict[str, object] = {
            "id": request_id,
            "method": method,
            "params": params or {},
        }
        if session_id:
            payload["sessionId"] = session_id
        self.websocket.send(json.dumps(payload))

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            remaining = max(0.1, deadline - time.monotonic())
            raw = self.websocket.recv(timeout=remaining)
            message = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise RuntimeError(
                    f"CDP {method} failed: {message['error']}"
                )
            result = message.get("result", {})
            if not isinstance(result, dict):
                raise RuntimeError(
                    f"CDP {method} returned invalid result: {message}"
                )
            return result
        raise TimeoutError(f"Timed out waiting for CDP {method}")

    def close(self) -> None:
        try:
            self.websocket.close()
        except Exception:
            pass


def runtime_evaluate(
    cdp: BrowserCdpClient,
    session_id: str,
    expression: str,
    timeout: float = 10.0,
) -> object:
    payload = cdp.command(
        "Runtime.evaluate",
        {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
        },
        session_id=session_id,
        timeout=timeout,
    )
    result = payload.get("result")
    if not isinstance(result, dict):
        raise RuntimeError(f"Runtime.evaluate returned invalid result: {payload}")
    if result.get("type") == "object" and "value" not in result:
        return result.get("description")
    return result.get("value")


def wait_for_extension_marker(
    cdp: BrowserCdpClient,
    session_id: str,
    timeout: float = 10.0,
) -> None:
    deadline = time.monotonic() + timeout
    last_value: object = None
    while time.monotonic() < deadline:
        last_value = runtime_evaluate(
            cdp,
            session_id,
            "Boolean(document.getElementById('pasi-activity-indicator'))",
            timeout=3.0,
        )
        if last_value is True:
            return
        time.sleep(0.2)
    raise AssertionError(
        "PASI Chromium extension did not inject its activity marker into the fixture page; "
        f"last marker state={last_value!r}"
    )


def start_chrome(
    chrome_binary: str,
    debug_port: int,
    profile_dir: Path,
    log_file,
) -> subprocess.Popen:
    return subprocess.Popen(
        [
            chrome_binary,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-sync",
            "--disable-component-update",
            "--disable-default-apps",
            "--enable-unsafe-extension-debugging",
            f"--remote-debugging-port={debug_port}",
            "--remote-allow-origins=*",
            "--ignore-certificate-errors",
            "--host-resolver-rules=MAP chatgpt.com 127.0.0.1",
            f"--user-data-dir={profile_dir}",
        ],
        stdin=subprocess.DEVNULL,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def stop_chrome(chrome_process: subprocess.Popen | None) -> None:
    if chrome_process is None or chrome_process.poll() is not None:
        return
    try:
        os.killpg(chrome_process.pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        chrome_process.terminate()
    try:
        chrome_process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(chrome_process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            chrome_process.kill()
        chrome_process.wait(timeout=5)


def main() -> None:
    BridgeHandler.finished_payload = None
    BridgeHandler.observations = 0
    BridgeHandler.observation_payloads = []
    BridgeHandler.requests = []

    bridge = ThreadingHTTPServer((BRIDGE_HOST, BRIDGE_PORT), BridgeHandler)
    fixture_port = free_port()
    fixture = ThreadingHTTPServer(("127.0.0.1", fixture_port), FixtureHandler)
    with tempfile.TemporaryDirectory(prefix="pasi-fixture-tls-") as tls_root:
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

        chrome_binary = find_chrome()
        with (
            tempfile.TemporaryDirectory(prefix="pasi-chromium-e2e-") as profile_root,
            tempfile.TemporaryDirectory(prefix="pasi-chromium-extension-") as extension_root,
            tempfile.NamedTemporaryFile(
                prefix="pasi-chromium-", suffix=".log", delete=False
            ) as log_file,
        ):
            chrome_process: subprocess.Popen | None = None
            cdp: BrowserCdpClient | None = None
            browser_session: str | None = None
            target_id: str | None = None
            try:
                extension_dir = build_extension(Path(extension_root) / "pasi-chatgpt")
                mutation = os.environ.get("PASI_E2E_MUTATION", "").strip()
                if mutation == "collapse_response_whitespace":
                    mutated_content_path = extension_dir / "content.js"
                    mutated_content = mutated_content_path.read_text(encoding="utf-8")
                    mutated_content = mutated_content.replace(
                        ".replace(/\\r\\n?/g, '\\n')\\n      .replace(/[ \\t]+(?=\\n)/g, '')",
                        ".replace(/\\s+/g, ' ')"
                    )
                    mutated_content_path.write_text(mutated_content, encoding="utf-8")
                elif mutation:
                    raise ValueError(f"unknown PASI_E2E_MUTATION: {mutation}")
                debug_port = free_port()
                profile_dir = Path(profile_root) / "profile"
                profile_dir.mkdir()
                chrome_process = start_chrome(
                    chrome_binary,
                    debug_port,
                    profile_dir,
                    log_file,
                )

                websocket_url = read_devtools_browser_endpoint(debug_port)
                cdp = BrowserCdpClient(websocket_url)

                loaded = cdp.command(
                    "Extensions.loadUnpacked",
                    {"path": str(extension_dir)},
                    timeout=15.0,
                )
                extension_id = loaded.get("id")
                if not isinstance(extension_id, str) or not extension_id:
                    raise RuntimeError(
                        f"Extensions.loadUnpacked returned no extension id: {loaded}"
                    )

                installed = cdp.command("Extensions.getExtensions", timeout=10.0)
                installed_extensions = installed.get("extensions")
                if not isinstance(installed_extensions, list) or not any(
                    isinstance(item, dict) and item.get("id") == extension_id
                    for item in installed_extensions
                ):
                    raise RuntimeError(
                        f"Loaded extension {extension_id} was not reported by "
                        f"Extensions.getExtensions: {installed}"
                    )

                created = cdp.command(
                    "Target.createTarget",
                    {"url": "about:blank"},
                    timeout=10.0,
                )
                target_id = created.get("targetId")
                if not isinstance(target_id, str) or not target_id:
                    raise RuntimeError(f"Target.createTarget returned invalid target: {created}")

                attached = cdp.command(
                    "Target.attachToTarget",
                    {"targetId": target_id, "flatten": True},
                    timeout=10.0,
                )
                browser_session = attached.get("sessionId")
                if not isinstance(browser_session, str) or not browser_session:
                    raise RuntimeError(
                        f"Target.attachToTarget returned no session id: {attached}"
                    )

                cdp.command("Page.enable", session_id=browser_session)
                cdp.command("Runtime.enable", session_id=browser_session)
                cdp.command(
                    "Page.navigate",
                    {"url": f"https://chatgpt.com:{fixture_port}/fixture"},
                    session_id=browser_session,
                    timeout=10.0,
                )

                wait_for_extension_marker(cdp, browser_session, timeout=10.0)

                browser_state = runtime_evaluate(
                    cdp,
                    browser_session,
                    """({
                      href: location.href,
                      active: localStorage.getItem("pasi:active-operation"),
                      response: document.querySelector('[data-message-author-role="assistant"]')?.innerText || ""
                    })""",
                )
                if not isinstance(browser_state, dict):
                    raise RuntimeError(
                        f"Chromium fixture did not return browser state: {browser_state!r}"
                    )
                if browser_state.get("response") != EXPECTED_RESPONSE:
                    raise AssertionError(
                        f"Chromium fixture response mismatch: {browser_state}"
                    )

                wait_for_bridge_event(20.0)
                # Health reporting is intentionally interval-based; a successful response can arrive before the next heartbeat.
                wait_for_health_observation(20.0)

                response_observations = [
                    item.get("observation", {})
                    for item in BridgeHandler.observation_payloads
                    if isinstance(item.get("observation", {}), dict)
                    and item.get("observation", {}).get("data", {}).get("kind") == "chatgpt_response"
                ]
                if not response_observations:
                    raise AssertionError("Chromium did not report a response observation")
                observed_responses = [
                    entry.get("data", {}).get("response_text")
                    for entry in response_observations
                    if isinstance(entry.get("data", {}).get("response_text"), str)
                    and bool(entry.get("data", {}).get("response_text").strip())
                ]
                if EXPECTED_RESPONSE not in observed_responses:
                    raise AssertionError(
                        "Chromium response observation did not preserve multiline text: "
                        f"{observed_responses!r}"
                    )

                health_observations = [
                    item.get("observation", {})
                    for item in BridgeHandler.observation_payloads
                    if isinstance(item.get("observation", {}), dict)
                    and item.get("observation", {}).get("data", {}).get("kind") == "chatgpt_health"
                ]
                if not health_observations:
                    raise AssertionError("Chromium did not report health observation")
                latest_health = health_observations[-1].get("data", {})
                if latest_health.get("provider_usage_limited") is True:
                    raise AssertionError(f"false usage-limit detector positive: {latest_health}")
                if latest_health.get("conversation_context_exhausted") is True:
                    raise AssertionError(f"false context detector positive: {latest_health}")
                if latest_health.get("auth_required") is True:
                    raise AssertionError(f"false auth detector positive: {latest_health}")
                if latest_health.get("native_controller") is not True:
                    raise AssertionError(f"native controller health missing: {latest_health}")

                final_browser_state = runtime_evaluate(
                    cdp,
                    browser_session,
                    """({
                      href: location.href,
                      active: localStorage.getItem("pasi:active-operation")
                    })""",
                )
                if not isinstance(final_browser_state, dict):
                    raise RuntimeError(
                        f"Chromium post-recovery state was invalid: {final_browser_state!r}"
                    )
                if final_browser_state.get("active") is not None:
                    raise AssertionError(
                        "Chromium recovery marker was not cleared after completion: "
                        f"{final_browser_state}"
                    )
            except Exception as exc:
                diagnostic = None
                if cdp is not None and browser_session:
                    try:
                        diagnostic = runtime_evaluate(
                            cdp,
                            browser_session,
                            """({
                              href: location.href,
                              active: localStorage.getItem("pasi:active-operation"),
                              body: document.body?.innerText || ""
                            })""",
                            timeout=3.0,
                        )
                    except Exception:
                        pass
                chrome_log = Path(log_file.name).read_text(
                    encoding="utf-8",
                    errors="replace",
                )[-5000:]
                raise AssertionError(
                    f"Chromium CDP acceptance failed: {exc}; "
                    f"browser={diagnostic}; observations={BridgeHandler.observation_payloads!r}; "
                    f"requests={BridgeHandler.requests!r}; chrome_log={chrome_log}"
                ) from exc
            finally:
                if cdp is not None and target_id:
                    try:
                        cdp.command(
                            "Target.closeTarget",
                            {"targetId": target_id},
                            timeout=5.0,
                        )
                    except Exception:
                        pass
                if cdp is not None:
                    cdp.close()
                stop_chrome(chrome_process)
            Path(log_file.name).unlink(missing_ok=True)

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
    print("Minimized Chromium late-response recovery CDP E2E: PASS")


if __name__ == "__main__":
    main()
