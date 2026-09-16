"""Run the CI web smoke checks with explicit server lifecycle management."""
from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime" / "ci"
LOG_PATH = RUNTIME / "server.log"
BASE = "http://127.0.0.1:8000"


def fetch(path: str) -> str:
    with urllib.request.urlopen(BASE + path, timeout=10) as response:
        return response.read().decode("utf-8")


def wait_for_server(process: subprocess.Popen[bytes]) -> None:
    for _ in range(40):
        return_code = process.poll()
        if return_code is not None:
            raise RuntimeError(f"web server exited during startup with code {return_code}")
        try:
            if '"status":"ok"' in fetch("/api/health"):
                return
        except (OSError, urllib.error.URLError):
            time.sleep(0.25)
            continue
    raise RuntimeError("web server did not become ready within 10 seconds")


def stop_server(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def main() -> int:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("wb") as log:
        process = subprocess.Popen(
            [sys.executable, "scripts/serve_web.py"],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            wait_for_server(process)

            page = fetch("/")
            if "chat-form" not in page:
                raise AssertionError("web page does not contain chat-form")
            if "production-ui.js" not in page:
                raise AssertionError("web page does not contain production-ui.js")

            health = fetch("/api/health")
            if '"status":"ok"' not in health:
                raise AssertionError("health endpoint did not report status=ok")

            manifest = fetch("/api/manifest")
            if "Engineering" not in manifest:
                raise AssertionError("manifest does not contain Engineering")

            env = os.environ.copy()
            env["PYTHONPATH"] = str(ROOT / "src")
            result = subprocess.run(
                [sys.executable, "scripts/e2e_api_smoke.py"],
                cwd=ROOT,
                env=env,
                check=False,
            )
            return result.returncode
        except Exception as exc:
            print(f"CI web smoke failed: {exc}", file=sys.stderr)
            print(f"Web server exit code: {process.poll()}", file=sys.stderr)
            return 1
        finally:
            stop_server(process)
            print(f"Web server final exit code: {process.returncode}")
            print("=== server.log ===")
            try:
                print(LOG_PATH.read_text(encoding="utf-8"), end="")
            except OSError as exc:
                print(f"Unable to read server log: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
