#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from automation.computer_use.chatgpt import ChatGPTAdapter, UrllibBridgeTransport


def signature_counts(value: object) -> tuple[int, int] | None:
    if not isinstance(value, str):
        return None
    match = re.match(r"^(\d+):(\d+):", value)
    return (int(match.group(1)), int(match.group(2))) if match else None


def data_from_observation(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    data = value.get("data")
    return data if isinstance(data, dict) else value


def write_evidence(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the M1 20-prompt live duplicate-send/false-verdict gate.")
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--session-id", default="")
    args = parser.parse_args()
    if args.count != 20:
        parser.error("--count must be exactly 20")

    evidence_dir = Path(".runtime/acceptance")
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = evidence_dir / "m1-live.json"
    results: list[dict[str, object]] = []
    started_at = time.time()
    evidence: dict[str, Any] = {
        "gate": "M1",
        "status": "STARTED",
        "count": 20,
        "false_terminal_chat_verdicts": 0,
        "duplicate_message_deltas": 0,
        "results": results,
        "started_at": started_at,
    }
    write_evidence(evidence_path, evidence)

    adapter = ChatGPTAdapter(
        transport=UrllibBridgeTransport(timeout_seconds=10.0),
        session_id=args.session_id.strip() or f"m1-{uuid.uuid4().hex}",
        poll_interval_seconds=0.25,
        max_wait_seconds=args.timeout,
    )

    try:
        adapter.new_session()
        baseline = data_from_observation(adapter.read_browser_state())
        baseline_counts = signature_counts(baseline.get("conversation_signature"))
        if baseline_counts is None:
            raise RuntimeError("fresh chat did not expose a parseable conversation_signature")
        chat_url = str(baseline.get("chat_url") or "")
        if not chat_url.startswith("https://chatgpt.com/c/"):
            raise RuntimeError(f"fresh chat did not produce a verified ChatGPT conversation URL: {chat_url!r}")

        evidence["baseline"] = {
            "chat_url": chat_url,
            "user": baseline_counts[0],
            "assistant": baseline_counts[1],
        }
        write_evidence(evidence_path, evidence)

        expected_user, expected_assistant = baseline_counts
        for index in range(1, 21):
            marker = f"PASI_M1_ACCEPTANCE_{index:02d}_{uuid.uuid4().hex[:8]}"
            prompt = f"Reply with exactly this marker and no other text: {marker}. This is a PASI live acceptance prompt."
            operation_id = adapter.submit_prompt(prompt)
            response = adapter.wait_for_completion(operation_id, timeout_seconds=args.timeout)

            if response.completion != "complete":
                raise RuntimeError(f"prompt {index} did not complete: {response.completion!r} {response.error!r}")
            if response.error and str(response.error).startswith("CHAT_"):
                evidence["false_terminal_chat_verdicts"] += 1
                raise RuntimeError(f"prompt {index} produced terminal CHAT_* verdict: {response.error}")
            if marker not in response.text:
                raise RuntimeError(f"prompt {index} response missing unique marker")

            state = data_from_observation(adapter.read_browser_state())
            counts = signature_counts(state.get("conversation_signature"))
            if counts is None:
                raise RuntimeError(f"prompt {index} lacked conversation_signature")
            user_delta = counts[0] - expected_user
            assistant_delta = counts[1] - expected_assistant
            if user_delta != 1 or assistant_delta != 1:
                evidence["duplicate_message_deltas"] += max(0, abs(user_delta) - 1) + max(0, abs(assistant_delta) - 1)
                raise RuntimeError(
                    f"prompt {index} expected +1/+1 message delta, got +{user_delta}/+{assistant_delta}"
                )
            expected_user, expected_assistant = counts
            results.append(
                {
                    "index": index,
                    "operation_id": operation_id,
                    "marker": marker,
                    "completion": response.completion,
                    "user_delta": user_delta,
                    "assistant_delta": assistant_delta,
                    "chat_url": response.chat_url or state.get("chat_url"),
                }
            )
            evidence["completed_count"] = len(results)
            write_evidence(evidence_path, evidence)
            print(json.dumps(results[-1], ensure_ascii=False), flush=True)

        evidence.update({
            "status": "PASS",
            "completed_count": 20,
            "completed_at": time.time(),
        })
        write_evidence(evidence_path, evidence)
        print("M1 PASS: 20 prompts; zero duplicate message deltas; zero terminal CHAT_* verdicts")
        print(f"Evidence: {evidence_path}")
        return 0
    except Exception as exc:
        evidence.update({
            "status": "FAIL",
            "completed_count": len(results),
            "failed_at": time.time(),
            "failure": str(exc)[-4000:],
        })
        write_evidence(evidence_path, evidence)
        print(f"M1 FAIL: {exc}", flush=True)
        print(f"Failure evidence: {evidence_path}", flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
