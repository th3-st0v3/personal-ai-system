from __future__ import annotations

import hashlib
import json
import re
import subprocess
import threading
import time
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
REMOTE_MAIN_REF = "origin/main"
REMOTE_REFRESH_SECONDS = 30.0
REMOTE_FETCH_TIMEOUT_SECONDS = 8.0
MAX_MANIFEST_BYTES = 64 * 1024
MAX_CONTROLLER_BYTES = 2_000_000
MAX_RECOVERY_BYTES = 250_000
ALLOWED_ORIGINS = {
    "https://chatgpt.com",
    "https://www.chatgpt.com",
}

_remote_lock = threading.Lock()
_last_remote_refresh = 0.0


class ControllerDistributionError(RuntimeError):
    pass


def git_blob_sha1(path: Path) -> str:
    data = path.read_bytes()
    header = f"blob {len(data)}\0".encode("utf-8")
    return hashlib.sha1(header + data).hexdigest()


def _run_git(command: list[str], *, timeout: float = 5.0) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            command,
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)
    return result.returncode, (result.stdout or "").strip(), (result.stderr or "").strip()


def refresh_remote_main(*, force: bool = False) -> bool:
    """Refresh origin/main without changing the working tree."""
    global _last_remote_refresh
    now = time.monotonic()
    if not force and now - _last_remote_refresh < REMOTE_REFRESH_SECONDS:
        return True
    with _remote_lock:
        now = time.monotonic()
        if not force and now - _last_remote_refresh < REMOTE_REFRESH_SECONDS:
            return True
        code, _, _ = _run_git(
            ["git", "fetch", "--quiet", "--no-tags", "origin", "main"],
            timeout=REMOTE_FETCH_TIMEOUT_SECONDS,
        )
        if code == 0:
            _last_remote_refresh = now
            return True
        return False


def _git_show(ref: str, path: str) -> bytes:
    code, stdout, stderr = _run_git(["git", "show", f"{ref}:{path}"], timeout=5.0)
    if code != 0:
        raise ControllerDistributionError(f"Git could not read {ref}:{path}: {stderr or 'unknown error'}")
    return stdout.encode("utf-8")


def _git_ref_sha(ref: str) -> str:
    code, stdout, stderr = _run_git(["git", "rev-parse", ref], timeout=5.0)
    if code != 0 or not re.fullmatch(r"[0-9a-f]{40}", stdout, re.IGNORECASE):
        raise ControllerDistributionError(f"Git ref {ref} is unavailable: {stderr or 'unknown error'}")
    return stdout.lower()


def _controller_version(source: str) -> str:
    match = re.search(r"^//\s*@version\s+(\d+\.\d+\.\d+)\s*$", source, re.MULTILINE)
    if not match:
        raise ControllerDistributionError("controller source does not contain a semantic @version")
    return match.group(1)


def _recovery_version(source: str) -> str:
    match = re.search(r"RECOVERY_VERSION\s*=\s*['\"](\d+\.\d+\.\d+)['\"]", source)
    if not match:
        raise ControllerDistributionError("recovery source does not contain a semantic RECOVERY_VERSION")
    return match.group(1)


def _load_manifest() -> dict[str, Any]:
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
    return manifest


def load_verified_release() -> tuple[dict[str, Any], str, str]:
    try:
        controller_bytes = CONTROLLER_PATH.read_bytes()
    except OSError as exc:
        raise ControllerDistributionError(f"controller distribution files are unavailable: {exc}") from exc
    manifest = _load_manifest()
    if manifest.get("enabled") is not True:
        raise ControllerDistributionError("controller release is disabled")
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
    manifest = _load_manifest()
    if manifest.get("enabled") is not True:
        raise ControllerDistributionError("controller release is disabled")
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
    if f"RECOVERY_VERSION = '{version}'" not in source and f'RECOVERY_VERSION = "{version}"' not in source:
        raise ControllerDistributionError("recovery source version does not match sync manifest")
    return manifest, source, actual_sha


def _canonical_from_remote() -> tuple[dict[str, Any], str, str, str, str]:
    ref_sha = _git_ref_sha(REMOTE_MAIN_REF)
    controller_path = "automation/tampermonkey/chatgpt-controller.user.js"
    recovery_path = "automation/chromium/pasi-chatgpt/recovery.js"
    controller_bytes = _git_show(REMOTE_MAIN_REF, controller_path)
    recovery_bytes = _git_show(REMOTE_MAIN_REF, recovery_path)
    if len(controller_bytes) > MAX_CONTROLLER_BYTES:
        raise ControllerDistributionError("remote controller source exceeds configured size bound")
    if len(recovery_bytes) > MAX_RECOVERY_BYTES:
        raise ControllerDistributionError("remote recovery companion exceeds configured size bound")

    controller_source = controller_bytes.decode("utf-8")
    recovery_source = recovery_bytes.decode("utf-8")
    version = _controller_version(controller_source)
    recovery_version = _recovery_version(recovery_source)
    controller_sha = hashlib.sha1(f"blob {len(controller_bytes)}\0".encode("utf-8") + controller_bytes).hexdigest()
    recovery_sha = hashlib.sha1(f"blob {len(recovery_bytes)}\0".encode("utf-8") + recovery_bytes).hexdigest()

    local_manifest: dict[str, Any] = {}
    try:
        local_manifest = _load_manifest()
    except ControllerDistributionError:
        pass
    reason = local_manifest.get("reason") if isinstance(local_manifest.get("reason"), str) else "Verified from canonical origin/main."
    manifest = {
        "schema_version": "1",
        "enabled": True,
        "version": version,
        "source_url": "https://raw.githubusercontent.com/th3-st0v3/personal-ai-system/main/automation/tampermonkey/chatgpt-controller.user.js",
        "git_blob_sha": controller_sha,
        "release_commit": ref_sha,
        "recovery_version": recovery_version,
        "recovery_source_url": "https://raw.githubusercontent.com/th3-st0v3/personal-ai-system/main/automation/chromium/pasi-chatgpt/recovery.js",
        "recovery_git_blob_sha": recovery_sha,
        "reason": reason,
        "distribution_source": REMOTE_MAIN_REF,
    }
    return manifest, controller_source, controller_sha, recovery_source, recovery_sha


def _local_main_is_safe() -> bool:
    branch_code, branch, _ = _run_git(["git", "branch", "--show-current"], timeout=5.0)
    status_code, status, _ = _run_git(["git", "status", "--porcelain"], timeout=5.0)
    return branch_code == 0 and status_code == 0 and branch == "main" and not status


def load_verified_canonical_bundle() -> tuple[dict[str, Any], str, str, str, str]:
    remote_ready = refresh_remote_main()
    if remote_ready:
        try:
            return _canonical_from_remote()
        except ControllerDistributionError:
            pass

    if _local_main_is_safe():
        manifest, controller_source, controller_sha = load_verified_release()
        _, recovery_source, recovery_sha = load_verified_recovery()
        return manifest, controller_source, controller_sha, recovery_source, recovery_sha

    raise ControllerDistributionError("canonical origin/main controller release is unavailable and local checkout is not a clean main branch")


class ControllerDistributionHandler(BaseHTTPRequestHandler):
    server_version = "PersonalAIControllerDistribution/1.2"

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
        try:
            manifest, controller_source, controller_sha, recovery_source, recovery_sha = load_verified_canonical_bundle()
        except ControllerDistributionError as exc:
            self._json({"status": "error", "error": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE)
            return

        if path == "/health":
            self._json({
                "status": "ok",
                "service": "personal-ai-system-controller-distribution",
                "version": manifest["version"],
                "git_blob_sha": controller_sha,
                "recovery_version": manifest["recovery_version"],
                "recovery_git_blob_sha": recovery_sha,
                "release_commit": manifest.get("release_commit", ""),
                "distribution_source": manifest.get("distribution_source", "local-main"),
            })
            return

        if path == "/controller/manifest":
            payload = dict(manifest)
            payload["local_source_url"] = f"http://{HOST}:{PORT}/controller/source"
            payload["local_recovery_source_url"] = f"http://{HOST}:{PORT}/recovery/source"
            payload["git_blob_sha"] = controller_sha
            payload["recovery_git_blob_sha"] = recovery_sha
            self._json(payload)
            return

        if path == "/controller/source":
            self._text(controller_source, headers={
                "X-PASI-Controller-Version": str(manifest["version"]),
                "X-PASI-Controller-Git-Blob-SHA": controller_sha,
            })
            return

        if path == "/recovery/source":
            self._text(recovery_source, headers={
                "X-PASI-Recovery-Version": str(manifest["recovery_version"]),
                "X-PASI-Recovery-Git-Blob-SHA": recovery_sha,
            })
            return

        self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args: object) -> None:
        print(f"[PASI Controller Server] {format % args}", flush=True)


class ControllerDistributionServer(ThreadingHTTPServer):
    allow_reuse_address = True


def main() -> None:
    load_verified_canonical_bundle()
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
