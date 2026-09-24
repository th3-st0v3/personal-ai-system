#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BRIDGE_HEALTH_URL = "http://127.0.0.1:8765/health"
BROWSER_HEALTH_URL = "http://127.0.0.1:8765/browser/health"
DEFAULT_MAX_HEARTBEAT_AGE_SECONDS = 30.0
CHAT_URL_PATTERN = re.compile(r"^https://(?:www\.)?chatgpt\.com/c/")


def request_json(url: str, token: str | None = None, timeout: float = 5.0) -> dict[str, Any]:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read(2_000_000).decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"{url} returned a non-object JSON payload")
    return payload


def extract_observation(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    observation = payload.get("observation")
    if not isinstance(observation, dict):
        raise RuntimeError("browser health response does not contain an observation object")
    data = observation.get("data")
    if isinstance(data, dict):
        return observation, data
    return observation, observation


def capture_time(data: dict[str, Any], observation: dict[str, Any]) -> str:
    value = data.get("captured_at")
    if not isinstance(value, str) or not value.strip():
        value = observation.get("captured_at")
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError("browser health observation has no captured_at timestamp")
    return value


def heartbeat_age_seconds(captured_at: str) -> float:
    try:
        timestamp = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError(f"invalid captured_at timestamp: {captured_at!r}") from exc
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - timestamp).total_seconds()


def expected_controller_version(root: Path) -> str:
    source = root / "automation" / "chromium" / "pasi-chatgpt" / "content.js"
    text = source.read_text(encoding="utf-8")
    match = re.search(r"""\bconst\s+CONTROLLER_VERSION\s*=\s*['"]([^'"]+)['"]""", text)
    if not match:
        raise RuntimeError(f"could not determine controller version from {source}")
    return match.group(1).strip()


def expected_extension_manifest_version(root: Path) -> str:
    manifest = root / "automation" / "chromium" / "pasi-chatgpt" / "manifest.json"
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"could not read extension manifest {manifest}: {exc}") from exc
    version = payload.get("version")
    if not isinstance(version, str) or not version.strip():
        raise RuntimeError(f"extension manifest {manifest} has no usable version")
    return version.strip()


def browser_health_is_ready(
    data: dict[str, Any],
    expected_controller_version: str,
    heartbeat_age: float,
    max_heartbeat_age: float,
) -> bool:
    return (
        data.get("kind") == "chatgpt_health"
        and data.get("native_controller") is True
        and data.get("controller_version") == expected_controller_version
        and -5 <= heartbeat_age <= max_heartbeat_age
        and data.get("composer_present") is True
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the real PASI desktop/browser boundary before a run.")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--max-age-seconds", type=float, default=DEFAULT_MAX_HEARTBEAT_AGE_SECONDS)
    parser.add_argument("--wait-seconds", type=float, default=45.0)
    parser.add_argument("--retry-interval-seconds", type=float, default=2.0)
    parser.add_argument("--require-visible", action="store_true")
    args = parser.parse_args()

    root = args.repo.expanduser().resolve()
    token_path = Path.home() / ".pasi" / "bridge-token"
    token = token_path.read_text(encoding="utf-8").strip() if token_path.exists() else ""

    health = request_json(BRIDGE_HEALTH_URL, timeout=3.0)
    if health.get("status") != "ok":
        raise RuntimeError(f"bridge health failed: {health!r}")

    expected = expected_controller_version(root)
    expected_extension_version = expected_extension_manifest_version(root)
    deadline = time.monotonic() + max(0.0, args.wait_seconds)
    observation: dict[str, Any]
    data: dict[str, Any]
    age = float("inf")
    last_retry_reason = ""
    while True:
        payload = request_json(BROWSER_HEALTH_URL, token=token, timeout=5.0)
        try:
            observation, data = extract_observation(payload)
        except RuntimeError as exc:
            last_retry_reason = str(exc)
            age = float("inf")
            if time.monotonic() >= deadline:
                raise
            time.sleep(max(0.05, args.retry_interval_seconds))
            continue
        try:
            captured_at = capture_time(data, observation)
            age = heartbeat_age_seconds(captured_at)
            last_retry_reason = ""
        except RuntimeError as exc:
            last_retry_reason = str(exc)
            age = float("inf")

        native = data.get("native_controller") is True
        kind = data.get("kind")
        actual = data.get("controller_version")
        actual_extension_version = data.get("extension_manifest_version")
        compatible = (
            kind == "chatgpt_health"
            and native
            and actual == expected
            and actual_extension_version == expected_extension_version
            and -5 <= age <= args.max_age_seconds
        )
        terminal_browser_block = (
            data.get("auth_required") is True
            or data.get("provider_usage_limited") is True
            or data.get("conversation_context_exhausted") is True
        )
        if compatible and (data.get("composer_present") is True or terminal_browser_block):
            break
        if native and actual_extension_version != expected_extension_version:
            if actual_extension_version:
                last_retry_reason = (
                    "loaded PASI extension version mismatch: "
                    f"expected {expected_extension_version}, observed {actual_extension_version}"
                )
            else:
                last_retry_reason = (
                    "loaded PASI extension does not report its manifest version; "
                    f"expected PASI extension {expected_extension_version}. "
                    "Reload the native PASI extension and the ChatGPT tab."
                )
        elif compatible and data.get("composer_present") is not True:
            last_retry_reason = "ChatGPT composer is not present"
        if time.monotonic() >= deadline:
            if last_retry_reason:
                raise RuntimeError(last_retry_reason)
            raise RuntimeError(
                f"browser heartbeat is stale or incompatible after {args.wait_seconds:.1f}s: "
                f"age={age:.2f}s"
            )
        time.sleep(max(0.05, args.retry_interval_seconds))

    captured_at = capture_time(data, observation)
    age = heartbeat_age_seconds(captured_at)

    checks = {
        "bridge_healthy": True,
        "observation_kind": kind,
        "native_controller": native,
        "controller_version_expected": expected,
        "controller_version_actual": actual,
        "extension_manifest_version_expected": expected_extension_version,
        "extension_manifest_version_actual": actual_extension_version,
        "heartbeat_age_seconds": round(age, 3),
        "chat_url": data.get("chat_url"),
        "auth_required": data.get("auth_required"),
        "provider_usage_limited": data.get("provider_usage_limited"),
        "conversation_context_exhausted": data.get("conversation_context_exhausted"),
        "thinking_enabled": data.get("thinking_enabled"),
        "thinking_capability": data.get("thinking_capability"),
        "page_visible": data.get("page_visible"),
        "composer_present": data.get("composer_present"),
        "active_operation_id": data.get("active_operation_id"),
    }
    print(json.dumps(checks, indent=2, ensure_ascii=False))

    if kind != "chatgpt_health":
        raise RuntimeError(f"unexpected browser observation kind: {kind!r}")
    if not native:
        raise RuntimeError("native PASI Chromium controller is not active")
    if actual != expected:
        raise RuntimeError(f"controller version mismatch: expected {expected!r}, observed {actual!r}")
    if actual_extension_version != expected_extension_version:
        raise RuntimeError(
            "loaded PASI extension version mismatch: "
            f"expected {expected_extension_version!r}, observed {actual_extension_version!r}; "
            "reload the native PASI extension in Chromium/Opera and reload the ChatGPT tab"
        )
    if age < -5 or age > args.max_age_seconds:
        raise RuntimeError(f"browser heartbeat is stale: age={age:.2f}s, limit={args.max_age_seconds:.2f}s")
    chat_url = data.get("chat_url")
    if not isinstance(chat_url, str) or not CHAT_URL_PATTERN.match(chat_url):
        raise RuntimeError(f"no verified ChatGPT conversation URL: {chat_url!r}")
    if data.get("auth_required") is True:
        raise RuntimeError("ChatGPT authentication/security verification is required")
    if data.get("provider_usage_limited") is True:
        raise RuntimeError("ChatGPT provider usage limit is active")
    if data.get("conversation_context_exhausted") is True:
        raise RuntimeError("current ChatGPT conversation context is exhausted")
    if data.get("composer_present") is not True:
        raise RuntimeError("ChatGPT composer is not present")
    if args.require_visible and data.get("page_visible") is not True:
        raise RuntimeError("ChatGPT page is not visible")

    print("PASI desktop preflight: PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, urllib.error.URLError, RuntimeError, ValueError) as exc:
        print(f"PASI desktop preflight: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
