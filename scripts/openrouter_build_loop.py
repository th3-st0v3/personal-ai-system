#!/usr/bin/env python3
"""Safe, resumable OpenRouter engineering build-assistant loop.

The loop asks a free OpenRouter model for exactly one proposed repository
change per cycle. It never writes model-generated code automatically. Proposed
changes are stored in an approval queue for a human to inspect and apply.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_MODEL = "openrouter/free"
DEFAULT_MAX_DAILY_REQUESTS = 45
DEFAULT_MIN_INTERVAL_SECONDS = 2100
MAX_RESPONSE_BYTES = 2_000_000
STATE_SCHEMA = 1
SYSTEM_PROMPT = """You are the supervised engineering build assistant for Personal AI System.
Work on one small repository improvement at a time.
Never request secrets, credentials, destructive commands, deployment, brokerage,
financial execution, or unrestricted shell access.
Return exactly one proposed file change or one planning step as JSON.
Prefer existing project architecture over rewrites.
Preserve deterministic engineering calculations and explicit safety boundaries.
Before proposing code, consider tests and backwards compatibility.
The human reviews every file change before it is applied.
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_state() -> dict[str, object]:
    return {
        "schema": STATE_SCHEMA,
        "phase": "beta",
        "completed_tasks": [],
        "backlog": [
            "Build the supervised engineering workload execution path.",
            "Add safe local sandbox integration behind a capability boundary.",
            "Connect deterministic calculations to workload manifests.",
            "Add simulation study and provenance primitives.",
            "Add shadow-mode telemetry and verification reporting.",
        ],
        "approval_queue": [],
        "request_history": [],
        "last_request_at": None,
    }


def load_state(path: Path) -> dict[str, object]:
    if not path.exists():
        state = default_state()
        save_state(path, state)
        return state
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("schema") != STATE_SCHEMA:
        raise ValueError("Unsupported state schema version.")
    return state


def save_state(path: Path, state: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def day_key() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def request_count_today(state: dict[str, object]) -> int:
    return sum(1 for item in state["request_history"] if item.get("day") == day_key())


def sleep_for_budget(state: dict[str, object], minimum_interval: int) -> None:
    last = state.get("last_request_at")
    if not last:
        return
    elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds()
    remaining = minimum_interval - elapsed
    if remaining > 0:
        time.sleep(remaining)


def validate_proposal(proposal: dict[str, object]) -> None:
    required = {"action_justification", "file_path", "code_to_execute", "new_state"}
    if set(proposal) != required:
        raise ValueError("Model response does not match the required proposal schema.")
    if not isinstance(proposal["action_justification"], str) or not proposal["action_justification"].strip():
        raise ValueError("Proposal justification must be non-empty.")
    path = str(proposal["file_path"] or "").strip()
    if path and (Path(path).is_absolute() or ".." in Path(path).parts):
        raise ValueError("Proposal path must stay inside the repository.")
    if not isinstance(proposal["code_to_execute"], str):
        raise ValueError("Proposal code must be a string.")
    if not isinstance(proposal["new_state"], dict):
        raise ValueError("Proposal new_state must be an object.")


def call_openrouter(api_key: str, model: str, state: dict[str, object], max_output_tokens: int) -> dict[str, object]:
    user_payload = {
        "phase": state.get("phase"),
        "backlog": state.get("backlog", [])[:20],
        "recent_queue": state.get("approval_queue", [])[-10:],
        "completed_tasks": state.get("completed_tasks", [])[-20:],
        "instruction": "Propose exactly one next repository change. Do not apply it.",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user_payload, separators=(",", ":"))},
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": max_output_tokens,
    }
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost",
            "X-Title": "Personal AI System Engineering Build Assistant",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("OpenRouter response exceeded the safety size limit.")
    data = json.loads(body.decode("utf-8"))
    result = json.loads(data["choices"][0]["message"]["content"])
    validate_proposal(result)
    return result


def enqueue_proposal(state: dict[str, object], proposal: dict[str, object]) -> None:
    queue = state.setdefault("approval_queue", [])
    queue.append({
        "created_at": utc_now(),
        "action_justification": proposal["action_justification"],
        "file_path": proposal["file_path"],
        "code": proposal["code_to_execute"],
        "status": "pending_review",
    })
    if len(queue) > 50:
        del queue[:-50]
    new_state = proposal["new_state"]
    if isinstance(new_state.get("backlog"), list):
        state["backlog"] = new_state["backlog"]
    if isinstance(new_state.get("completed_tasks"), list):
        state["completed_tasks"] = new_state["completed_tasks"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the supervised OpenRouter engineering build assistant.")
    parser.add_argument("--state", default=".runtime/ai_os_project_state.json")
    parser.add_argument("--model", default=os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL))
    parser.add_argument("--max-daily-requests", type=int, default=DEFAULT_MAX_DAILY_REQUESTS)
    parser.add_argument("--min-interval-seconds", type=int, default=DEFAULT_MIN_INTERVAL_SECONDS)
    parser.add_argument("--max-output-tokens", type=int, default=2500)
    parser.add_argument("--once", action="store_true", help="Run one model cycle and exit.")
    args = parser.parse_args()
    if not 1 <= args.max_daily_requests <= 50:
        raise SystemExit("--max-daily-requests must be between 1 and 50.")
    if args.min_interval_seconds < 30:
        raise SystemExit("--min-interval-seconds must be at least 30.")
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise SystemExit("OPENROUTER_API_KEY is not set. See docs/openrouter-build-assistant.md.")

    state_path = Path(args.state)
    state = load_state(state_path)
    print(f"Engineering build assistant ready. Model: {args.model}")
    print(f"Requests today: {request_count_today(state)}/{args.max_daily_requests}")
    print("Model changes are queued for human review; they are not written automatically.")

    while True:
        if request_count_today(state) >= args.max_daily_requests:
            print("Daily request budget reached; preserving state and exiting safely.")
            save_state(state_path, state)
            return 0
        sleep_for_budget(state, args.min_interval_seconds)
        attempts = 0
        while True:
            try:
                proposal = call_openrouter(api_key, args.model, state, args.max_output_tokens)
                state["last_request_at"] = utc_now()
                state["request_history"].append({"day": day_key(), "at": state["last_request_at"]})
                enqueue_proposal(state, proposal)
                save_state(state_path, state)
                print(f"Queued: {proposal['action_justification']}")
                break
            except urllib.error.HTTPError as exc:
                if exc.code != 429:
                    raise
                delay = min(300 * (2 ** attempts), 3600) + random.randint(0, 30)
                attempts += 1
                print(f"Rate limited; backing off for {delay}s.")
                time.sleep(delay)
            except (urllib.error.URLError, TimeoutError) as exc:
                delay = min(30 * (2 ** attempts), 600) + random.randint(0, 10)
                attempts += 1
                print(f"Connection problem: {exc}; retrying in {delay}s.")
                time.sleep(delay)
        if args.once:
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
