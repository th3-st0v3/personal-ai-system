from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
BRIDGE_URL = "http://127.0.0.1:8765"
POLL_SECONDS = 2.0
DEFAULT_TIMEOUT = 900.0
GUARD_EXIT_USAGE_LIMIT = 90
GUARD_EXIT_AUTH_REQUIRED = 91
GUARD_EXIT_CONTROLLER_OFFLINE = 92

_CONTEXT_LIMIT_PHRASES = (
    "conversation has reached its limit",
    "conversation is too long",
    "context limit reached",
    "start a new chat to continue",
)
_USAGE_LIMIT_PHRASES = (
    "current usage limit",
    "usage limit reached",
    "free tier limit",
    "message limit",
    "daily limit",
    "weekly limit",
    "model usage limit",
    "rate limit",
    "too many requests",
)
_AUTH_PHRASES = (
    "log in to continue",
    "sign in to continue",
    "verify you're human",
    "security check",
    "captcha",
    "session has expired",
)


def request_json(path: str, timeout: float = 3.0) -> dict[str, Any] | None:
    request = Request(f"{BRIDGE_URL}{path}", method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read(2_000_000).decode("utf-8"))
    except (OSError, URLError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def observation_text(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    values: list[str] = []
    for key in ("error", "message", "response_text", "text", "signals", "status", "reason"):
        value = data.get(key)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list):
            values.extend(str(item) for item in value)
    return " ".join(values).strip().lower()


def classify_observation(payload: dict[str, Any] | None) -> str | None:
    if not payload:
        return None
    observation = payload.get("observation")
    data = observation.get("data") if isinstance(observation, dict) else None
    if not isinstance(data, dict):
        return None

    if data.get("provider_usage_limited") is True or data.get("usage_limited") is True or data.get("rate_limited") is True:
        return "usage_limit"
    if data.get("auth_required") is True or data.get("login_required") is True:
        return "auth_required"

    text = observation_text(data)
    if any(phrase in text for phrase in _AUTH_PHRASES):
        return "auth_required"
    if data.get("kind") == "chatgpt_response" and any(phrase in text for phrase in _CONTEXT_LIMIT_PHRASES):
        return None
    if any(phrase in text for phrase in _USAGE_LIMIT_PHRASES):
        return "usage_limit"
    return None


def _reader(stream: Any, chunks: list[str]) -> None:
    try:
        for line in iter(stream.readline, ""):
            if line:
                chunks.append(line)
    finally:
        try:
            stream.close()
        except Exception:
            pass


def run_guarded(command: list[str], *, timeout: float, bridge_poll_seconds: float = POLL_SECONDS) -> int:
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    process = subprocess.Popen(
        command,
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    output: list[str] = []
    reader = threading.Thread(target=_reader, args=(process.stdout, output), daemon=True)
    reader.start()
    started = time.monotonic()
    classification: str | None = None

    while process.poll() is None:
        if time.monotonic() - started >= timeout:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            classification = "guard_timeout"
            break

        classification = classify_observation(request_json("/browser/observation"))
        if classification in {"usage_limit", "auth_required"}:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            break
        time.sleep(bridge_poll_seconds)

    reader.join(timeout=2)
    combined = "".join(output)
    if combined:
        print(combined, end="")

    if classification == "usage_limit":
        print("CHAT_USAGE_LIMITED: ChatGPT reported a provider/account/model usage restriction. New chats cannot reset this limit.", file=sys.stderr)
        return GUARD_EXIT_USAGE_LIMIT
    if classification == "auth_required":
        print("CHAT_AUTH_REQUIRED: ChatGPT requires interactive authentication or a security challenge.", file=sys.stderr)
        return GUARD_EXIT_AUTH_REQUIRED
    if classification == "guard_timeout":
        print("CHAT_GUARD_TIMEOUT: bounded ChatGPT task runtime elapsed without a terminal result.", file=sys.stderr)
        return GUARD_EXIT_CONTROLLER_OFFLINE
    return process.returncode if process.returncode is not None else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Bound a PASI ChatGPT run and stop safely on provider-wide limits or auth challenges.")
    parser.add_argument("task", nargs="+", help="Task arguments forwarded to scripts/pasi_chat.py")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--github", choices=["public", "fallback", "never", "auto", "always"], default="public")
    args = parser.parse_args()

    forwarded = [
        sys.executable,
        "scripts/pasi_chat.py",
        *args.task,
        "--github",
        args.github,
        "--timeout",
        str(args.timeout),
    ]
    return run_guarded(forwarded, timeout=args.timeout + 15.0)


if __name__ == "__main__":
    raise SystemExit(main())
