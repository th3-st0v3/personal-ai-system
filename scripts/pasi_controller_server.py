from __future__ import annotations

import hashlib
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPOSITORY_ROOT / "automation" / "tampermonkey" / "controller-sync.json"
CONTROLLER_PATH = REPOSITORY_ROOT / "automation" / "tampermonkey" / "chatgpt-controller.user.js"
RECOVERY_PATH = REPOSITORY_ROOT / "automation" / "chromium" / "pasi-chatgpt" / "recovery.js"
HOST = "127.0.0.1"
PORT = 8766
MAX_MANIFEST_BYTES = 64 * 1024
MAX_CONTROLLER_BYTES = 2_000_000
MAX_RECOVERY_BYTES = 250_000
ALLOWED_ORIGINS = {
    "https://chatgpt.com",
    "https://www.chatgpt.com",
}


class ControllerDistributionError(RuntimeError):
    pass


def git_blob_sha1(path: Path) -> str:
    data = path.read_bytes()
    header = f"blob {len(data)}\0".encode("utf-8")
    return hashlib.sha1(header + data).hexdigest()


def _read_manifest() -> dict[str, Any]:
    try:
        manifest_bytes = MANIFEST_PATH.read_bytes()
    except OSError as exc:
        raise ControllerDistributionError(f"controller distribution files are unavailable: {exc}") from exc
    if len(manifest_bytes) > MAX_MANIFEST_BYTES:
        raise ControllerDistributionError("controller sync manifest exceeds configured size bound")
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ControllerDistributionError("controller sync manifest is invalid JSON") from exc
    if not isinstance(manifest, dict):
        raise ControllerDistributionError("controller sync manifest must be an object")
    if manifest.get("enabled") is not True:
        raise ControllerDistributionError("controller release is disabled")
    return manifest


def load_verified_release() -> tuple[dict[str, Any], str, str]:
    try:
        controller_bytes = CONTROLLER_PATH.read_bytes()
    except OSError as exc:
        raise ControllerDistributionError(f"controller distribution files are unavailable: {exc}") from exc
    manifest = _read_manifest()
    if len(controller_bytes) > MAX_CONTROLLER_BYTES:
        raise ControllerDistributionError("controller source exceeds configured size bound")

    version = manifest.get("version")
    expected_sha = manifest.get("git_blob_sha")
    if not isinstance(version, str) or not version.strip():
        raise ControllerDistributionError("controller sync manifest version is missing")
    if not isinstance(expected_sha, str) or len(expected_sha) != 40:
        raise ControllerDistributionError("controller sync manifest Git blob SHA is missing")

    source = controller_bytes.decode("utf-8")
    actual_sha = git_blob_sha1(CONTROLLER_PATH)
    if actual_sha.lower() != expected_sha.lower():
        raise ControllerDistributionError(
            f"controller Git blob mismatch: expected {expected_sha}, actual {actual_sha}"
        )
    if f"@version      {version}" not in source and f"@version {version}" not in source:
        raise ControllerDistributionError("controller source version does not match sync manifest")
    return manifest, source, actual_sha


def load_verified_recovery() -> tuple[dict[str, Any], str, str]:
    try:
        recovery_bytes = RECOVERY_PATH.read_bytes()
    except OSError as exc:
        raise ControllerDistributionError(f"recovery companion is unavailable: {exc}") from exc
    manifest = _read_manifest()
    if len(recovery_bytes) > MAX_RECOVERY_BYTES:
        raise ControllerDistributionError("recovery companion exceeds configured size bound")
    version = manifest.get("recovery_version")
    expected_sha = manifest.get("recovery_git_blob_sha")
    if not isinstance(version, str) or not version.strip():
        raise ControllerDistributionError("recovery manifest version is missing")
    if not isinstance(expected_sha, str) or len(expected_sha) != 40:
        raise ControllerDistributionError("recovery manifest Git blob SHA is missing")
    source = recovery_bytes.decode("utf-8")
    actual_sha = git_blob_sha1(RECOVERY_PATH)
    if actual_sha.lower() != expected_sha.lower():
        raise ControllerDistributionError(
            f"recovery Git blob mismatch: expected {expected_sha}, actual {actual_sha}"
        )
    return manifest, source, actual_sha


class ControllerDistributionHandler(BaseHTTPRequestHandler):
    server_version = "PersonalAIControllerDistribution/1.1"

    def _headers(self, status: int, content_type: str) -> None:
        origin = self.headers.get("Origin", "")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _json(self, payload: dict[str, Any], status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8")
        self.wfile.write(body)

    def _text(self, body: str, status: int = HTTPStatus.OK, *, headers: dict[str, str] | None = None) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(encoded)))
        if headers:
            for key, value in headers.items():
                self.send_header(key, value)
        origin = self.headers.get("Origin", "")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(encoded)

    def do_OPTIONS(self) -> None:
        self._headers(HTTPStatus.NO_CONTENT, "text/plain; charset=utf-8")

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            try:
                manifest, _, actual_sha = load_verified_release()
                _, _, recovery_sha = load_verified_recovery()
            except ControllerDistributionError as exc:
                self._json({"status": "error", "error": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE)
                return
            self._json({
                "status": "ok",
                "service": "personal-ai-system-controller-distribution",
                "version": manifest["version"],
                "git_blob_sha": actual_sha,
                "recovery_version": manifest["recovery_version"],
                "recovery_git_blob_sha": recovery_sha,
            })
            return

        if path == "/controller/manifest":
            try:
                manifest, _, actual_sha = load_verified_release()
                _, _, recovery_sha = load_verified_recovery()
            except ControllerDistributionError as exc:
                self._json({"error": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE)
                return
            payload = dict(manifest)
            payload["local_source_url"] = f"http://{HOST}:{PORT}/controller/source"
            payload["local_recovery_source_url"] = f"http://{HOST}:{PORT}/recovery/source"
            payload["git_blob_sha"] = actual_sha
            payload["recovery_git_blob_sha"] = recovery_sha
            self._json(payload)
            return

        if path == "/controller/source":
            try:
                manifest, source, actual_sha = load_verified_release()
            except ControllerDistributionError as exc:
                self._text(str(exc), HTTPStatus.SERVICE_UNAVAILABLE)
                return
            self._text(source, headers={
                "X-PASI-Controller-Version": str(manifest["version"]),
                "X-PASI-Controller-Git-Blob-SHA": actual_sha,
            })
            return

        if path == "/recovery/source":
            try:
                manifest, source, actual_sha = load_verified_recovery()
            except ControllerDistributionError as exc:
                self._text(str(exc), HTTPStatus.SERVICE_UNAVAILABLE)
                return
            self._text(source, headers={
                "X-PASI-Recovery-Version": str(manifest["recovery_version"]),
                "X-PASI-Recovery-Git-Blob-SHA": actual_sha,
            })
            return

        self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args: object) -> None:
        print(f"[PASI Controller Server] {format % args}", flush=True)


class ControllerDistributionServer(ThreadingHTTPServer):
    allow_reuse_address = True


def main() -> None:
    load_verified_release()
    load_verified_recovery()
    server = ControllerDistributionServer((HOST, PORT), ControllerDistributionHandler)
    print(f"PASI controller distribution: http://{HOST}:{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
