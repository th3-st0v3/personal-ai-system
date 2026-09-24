#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Protocol
from urllib.error import URLError
from urllib.request import urlopen

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class BrowserStateReader(Protocol):
    def read_browser_state(self) -> Any: ...
    def read_browser_observation(self) -> Any: ...


class BrowserEvidenceReader(BrowserStateReader, Protocol):
    def read_browser_response_observation(self) -> Any: ...


if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from automation.computer_use.chatgpt import ChatGPTAdapter, UrllibBridgeTransport

BRIDGE_URL = "http://127.0.0.1:8765/health"
TOKEN_FILE = Path.home() / ".pasi" / "bridge-token"


def parse_conversation_signature(value: object) -> tuple[int, int, str] | None:
    if not isinstance(value, str):
        return None
    parts = value.split(":", 2)
    if len(parts) != 3:
        return None
    user_text, assistant_text, fingerprint = parts
    if not user_text.isdigit() or not assistant_text.isdigit():
        return None
    user_count = int(user_text)
    assistant_count = int(assistant_text)
    if not fingerprint and (user_count != 0 or assistant_count != 0):
        return None
    return user_count, assistant_count, fingerprint


def signature_counts(value: object) -> tuple[int, int] | None:
    parsed = parse_conversation_signature(value)
    return parsed[:2] if parsed is not None else None


def response_fingerprint(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split()).strip()[-4000:]


def wait_for_conversation_signature(
    adapter: BrowserStateReader,
    expected_chat_url: str | None = None,
    *,
    timeout_seconds: float = 15.0,
    poll_seconds: float = 0.5,
) -> tuple[dict[str, Any], str]:
    deadline = time.monotonic() + timeout_seconds
    last_url = ""
    while True:
        state = data_from_observation(adapter.read_browser_observation())
        signature = state.get("conversation_signature")
        current_url = str(state.get("chat_url") or "")
        if current_url:
            last_url = current_url
        parsed = parse_conversation_signature(signature)
        valid_baseline = parsed is not None and (
            parsed[2] or parsed[:2] == (0, 0)
        )
        active_operation_id = state.get("active_operation_id")
        if (
            valid_baseline
            and current_url.startswith("https://chatgpt.com/c/")
            and (expected_chat_url is None or current_url == expected_chat_url)
            and not active_operation_id
        ):
            return state, str(signature)
        if time.monotonic() >= deadline:
            target = expected_chat_url or "<current ChatGPT conversation>"
            raise RuntimeError(
                f"current chat did not publish a valid conversation_signature within "
                f"{timeout_seconds:.1f}s: expected={target!r}, observed={last_url!r}"
            )
        time.sleep(poll_seconds)


def wait_for_signature_progression(
    adapter: BrowserStateReader,
    expected_chat_url: str,
    previous_signature: str,
    index: int,
    *,
    # chatgpt_state is published on a 10s cadence independently of the fast completion path;
    # allow two cadence intervals so a valid completion cannot fail only because telemetry is late.
    timeout_seconds: float = 30.0,
    poll_seconds: float = 0.5,
) -> tuple[dict[str, Any], str]:
    previous = parse_conversation_signature(previous_signature)
    if previous is None:
        raise RuntimeError(f"prompt {index} had an invalid previous conversation_signature")
    expected_user = previous[0] + 1
    expected_assistant = previous[1] + 1
    deadline = time.monotonic() + timeout_seconds
    while True:
        state = data_from_observation(adapter.read_browser_state())
        current_url = str(state.get("chat_url") or "")
        if current_url and current_url != expected_chat_url:
            raise RuntimeError(
                f"prompt {index} changed ChatGPT conversation URL: {current_url!r}"
            )
        current = parse_conversation_signature(state.get("conversation_signature"))
        if current is not None:
            if current[0] > expected_user or current[1] > expected_assistant:
                raise RuntimeError(
                    f"prompt {index} observed conversation-signature counts beyond the expected "
                    f"{expected_user}:{expected_assistant}: got {current[0]}:{current[1]}"
                )
            if (
                current[0] == expected_user
                and current[1] == expected_assistant
                and current[2]
                and current[2] != previous[2]
            ):
                return state, str(state["conversation_signature"])
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"prompt {index} did not publish the exact +1/+1 conversation-signature "
                f"progression within {timeout_seconds:.1f}s"
            )
        time.sleep(poll_seconds)



def wait_for_durable_response_progression(
    adapter: BrowserEvidenceReader,
    expected_chat_url: str,
    operation_id: str,
    marker: str,
    previous_signature: str,
    index: int,
    *,
    timeout_seconds: float = 30.0,
    poll_seconds: float = 0.5,
) -> tuple[dict[str, Any], str]:
    previous = parse_conversation_signature(previous_signature)
    if previous is None:
        raise RuntimeError(f"prompt {index} had an invalid previous conversation_signature")
    expected_user = previous[0] + 1
    expected_assistant = previous[1] + 1
    deadline = time.monotonic() + timeout_seconds
    last_state: dict[str, Any] = {}
    while True:
        observation = adapter.read_browser_response_observation()
        state = data_from_observation(observation)
        last_state = state
        observed_operation_id = state.get("operation_id") or state.get("active_operation_id")
        current_url = str(state.get("chat_url") or "")
        response_text = str(state.get("response_text") or "")
        current = parse_conversation_signature(state.get("conversation_signature"))
        if observed_operation_id == operation_id and marker in response_text:
            if current_url and current_url != expected_chat_url:
                raise RuntimeError(
                    f"prompt {index} changed ChatGPT conversation URL: {current_url!r}"
                )
            if current is not None:
                if current[0] > expected_user or current[1] > expected_assistant:
                    raise RuntimeError(
                        f"prompt {index} durable response signature counts beyond the expected "
                        f"{expected_user}:{expected_assistant}: got {current[0]}:{current[1]}"
                    )
                durable_fingerprint = response_fingerprint(response_text)
                if (
                    current[0] == expected_user
                    and current[1] == expected_assistant
                    and current[2]
                    and durable_fingerprint
                    and current[2] == durable_fingerprint
                    and durable_fingerprint != previous[2]
                ):
                    return state, str(state["conversation_signature"])
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"prompt {index} did not publish the exact +1/+1 durable response signature "
                f"within {timeout_seconds:.1f}s; "
                f"last_observed_operation={last_state.get('operation_id') or last_state.get('active_operation_id')!r}, "
                f"last_observed_signature={last_state.get('conversation_signature')!r}, "
                f"marker_present={marker in str(last_state.get('response_text') or '')}"
            )
        time.sleep(poll_seconds)


def validate_signature_progression(previous: object, current: object, index: int) -> tuple[int, int]:
    previous_signature = parse_conversation_signature(previous)
    current_signature = parse_conversation_signature(current)
    if previous_signature is None:
        raise RuntimeError(f"prompt {index} had an invalid previous conversation_signature")
    if current_signature is None:
        raise RuntimeError(f"prompt {index} had an invalid conversation_signature")
    expected_user = previous_signature[0] + 1
    expected_assistant = previous_signature[1] + 1
    if current_signature[0] != expected_user or current_signature[1] != expected_assistant:
        raise RuntimeError(
            f"prompt {index} expected exact conversation-signature count progression "
            f"{expected_user}:{expected_assistant}, got {current_signature[0]}:{current_signature[1]}"
        )
    if current_signature[2] == previous_signature[2]:
        raise RuntimeError(f"prompt {index} conversation_signature fingerprint did not change")
    if not current_signature[2]:
        raise RuntimeError(f"prompt {index} conversation_signature has no assistant fingerprint")
    return current_signature[0], current_signature[1]


def data_from_observation(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    data = value.get("data")
    return data if isinstance(data, dict) else value


def bridge_is_healthy() -> bool:
    try:
        with urlopen(BRIDGE_URL, timeout=3.0):
            return True
    except (OSError, URLError):
        return False


def provision_bridge_token() -> None:
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not TOKEN_FILE.is_file() or not TOKEN_FILE.read_text(encoding="utf-8").strip():
        TOKEN_FILE.write_text(secrets.token_urlsafe(48) + "\n", encoding="utf-8")
        TOKEN_FILE.chmod(0o600)
    token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    if not token:
        raise RuntimeError("PASI bridge token is empty")
    extension_root = Path(
        os.environ.get(
            "PASI_BROWSER_EXTENSION_ROOT",
            str(REPOSITORY_ROOT / "automation" / "chromium" / "pasi-chatgpt"),
        )
    ).expanduser()
    if not (extension_root / "manifest.json").is_file():
        raise RuntimeError(f"PASI ChatGPT extension root is missing: {extension_root}")
    bridge_token = extension_root / ".bridge-token"
    bridge_token.write_text(token + "\n", encoding="utf-8")
    bridge_token.chmod(0o600)


def ensure_bridge() -> subprocess.Popen[bytes] | None:
    if bridge_is_healthy():
        return None
    provision_bridge_token()
    process = subprocess.Popen(
        [sys.executable, "-m", "automation.orchestrator.bridge"],
        cwd=REPOSITORY_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        if bridge_is_healthy():
            return process
        if process.poll() is not None:
            raise RuntimeError(
                f"PASI bridge exited before becoming healthy (exit code {process.returncode})"
            )
        time.sleep(0.5)
    process.terminate()
    try:
        process.wait(timeout=3.0)
    except subprocess.TimeoutExpired:
        process.kill()
    raise RuntimeError("PASI bridge did not become healthy on 127.0.0.1:8765")


def require_live_browser() -> None:
    preflight = subprocess.run(
        [
            sys.executable,
            str(REPOSITORY_ROOT / "scripts" / "pasi_desktop_preflight.py"),
            "--repo",
            str(REPOSITORY_ROOT),
            "--wait-seconds",
            "45",
            "--max-age-seconds",
            "30",
        ],
        cwd=REPOSITORY_ROOT,
        check=False,
        text=True,
    )
    if preflight.returncode != 0:
        raise RuntimeError(
            "PASI desktop preflight failed; keep the authenticated native ChatGPT "
            "session attached and retry"
        )


def require_usable_current_chat(state: dict[str, Any]) -> None:
    if state.get("conversation_context_exhausted") is True or state.get("chat_exhausted") is True:
        raise RuntimeError(
            "M1 requires a usable current ChatGPT conversation; verified context exhaustion "
            "is a separate recovery gate and must not trigger an automatic new chat here"
        )
    if state.get("provider_usage_limited") is True:
        raise RuntimeError(
            "M1 requires provider usage to be available; provider usage limits are a separate "
            "condition and must not trigger a new chat here"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the M1 20-prompt live duplicate-send/false-verdict gate in the current ChatGPT conversation."
    )
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--session-id", default="")
    args = parser.parse_args()
    if args.count != 20:
        parser.error("--count must be exactly 20")

    adapter = ChatGPTAdapter(
        transport=UrllibBridgeTransport(timeout_seconds=10.0),
        session_id=args.session_id.strip() or f"m1-{uuid.uuid4().hex}",
        poll_interval_seconds=0.25,
        max_wait_seconds=args.timeout,
    )

    bridge_process = ensure_bridge()
    try:
        require_live_browser()
        evidence_dir = Path(".runtime/acceptance")
        evidence_dir.mkdir(parents=True, exist_ok=True)
        evidence_path = evidence_dir / "m1-live.json"

        baseline, baseline_signature = wait_for_conversation_signature(adapter)
        require_usable_current_chat(baseline)
        baseline_counts = signature_counts(baseline_signature)
        if baseline_counts is None:
            raise RuntimeError("current chat did not expose valid conversation-signature counts")
        chat_url = str(baseline.get("chat_url") or "")
        if not chat_url.startswith("https://chatgpt.com/c/"):
            raise RuntimeError(
                f"current chat did not expose a verified ChatGPT conversation URL: {chat_url!r}"
            )
        previous_signature = baseline_signature
        expected_user, expected_assistant = baseline_counts
        seen_operation_ids: set[str] = set()
        seen_markers: set[str] = set()
        results: list[dict[str, object]] = []

        for index in range(1, 21):
            marker = f"PASI_M1_ACCEPTANCE_{index:02d}_{uuid.uuid4().hex[:8]}"
            prompt = (
                f"Reply with exactly this marker and no other text: {marker}. "
                "This is a PASI live acceptance prompt."
            )
            if marker in seen_markers:
                raise RuntimeError(f"prompt {index} generated a duplicate marker")
            seen_markers.add(marker)
            operation_id = adapter.submit_prompt(prompt, completion_markers=[marker])
            if operation_id in seen_operation_ids:
                raise RuntimeError(f"prompt {index} reused operation_id {operation_id}")
            seen_operation_ids.add(operation_id)
            response = adapter.wait_for_completion(operation_id, timeout_seconds=args.timeout)

            if response.completion != "complete":
                raise RuntimeError(
                    f"prompt {index} did not complete: {response.completion!r} {response.error!r}"
                )
            if response.error and str(response.error).startswith("CHAT_"):
                raise RuntimeError(
                    f"prompt {index} produced terminal CHAT_* verdict: {response.error}"
                )
            if marker not in response.text:
                raise RuntimeError(f"prompt {index} response missing unique marker")

            before_signature = previous_signature
            state, current_signature = wait_for_durable_response_progression(
                adapter,
                chat_url,
                operation_id,
                marker,
                before_signature,
                index,
            )
            expected_user, expected_assistant = validate_signature_progression(
                before_signature, current_signature, index
            )
            before_parsed = parse_conversation_signature(before_signature)
            if before_parsed is None:
                raise RuntimeError(
                    f"prompt {index} had an invalid previous conversation_signature"
                )
            user_delta = expected_user - before_parsed[0]
            assistant_delta = expected_assistant - before_parsed[1]
            previous_signature = current_signature
            observed_chat_url = str(response.chat_url or state.get("chat_url") or "")
            if observed_chat_url != chat_url:
                raise RuntimeError(
                    f"prompt {index} changed ChatGPT conversation URL: {observed_chat_url!r}"
                )
            results.append(
                {
                    "index": index,
                    "operation_id": operation_id,
                    "marker": marker,
                    "completion": response.completion,
                    "user_delta": user_delta,
                    "assistant_delta": assistant_delta,
                    "chat_url": observed_chat_url,
                    "before_signature": before_signature,
                    "after_signature": current_signature,
                }
            )
            print(json.dumps(results[-1], ensure_ascii=False), flush=True)

        final_signature = parse_conversation_signature(previous_signature)
        if len(seen_operation_ids) != 20 or len(seen_markers) != 20 or final_signature is None:
            raise RuntimeError(
                "M1 did not complete 20 unique operations and markers with a final conversation signature"
            )
        if (
            final_signature[0] != baseline_counts[0] + 20
            or final_signature[1] != baseline_counts[1] + 20
        ):
            raise RuntimeError("M1 final conversation signature counts are not exactly baseline + 20")

        payload = {
            "gate": "M1",
            "status": "PASS",
            "count": 20,
            "created_new_chat": False,
            "false_terminal_chat_verdicts": 0,
            "duplicate_message_deltas": 0,
            "baseline": {
                "chat_url": chat_url,
                "user": baseline_counts[0],
                "assistant": baseline_counts[1],
            },
            "results": results,
            "completed_at": time.time(),
        }
        evidence_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print("M1 PASS: 20 prompts in the existing chat; zero duplicate message deltas; zero terminal CHAT_* verdicts")
        print(f"Evidence: {evidence_path}")
        return 0
    finally:
        if bridge_process is not None and bridge_process.poll() is None:
            bridge_process.terminate()
            try:
                bridge_process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                bridge_process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
