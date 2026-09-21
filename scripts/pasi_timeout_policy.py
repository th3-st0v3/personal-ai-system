from __future__ import annotations

import json
from pathlib import Path
from typing import Any

POLICY_PATH = Path(__file__).resolve().parents[1] / "automation" / "chromium" / "pasi-chatgpt" / "timeout-policy.json"

DEFAULTS: dict[str, float] = {
    "heartbeat_seconds": 5.0,
    "stale_seconds": 15.0,
    "controller_poll_ms": 500.0,
    "dom_poll_ms": 20.0,
    "menu_ms": 5000.0,
    "composer_ms": 10000.0,
    "send_ms": 5000.0,
    "submit_ms": 2500.0,
    "generation_seconds": 3600.0,
    "recovery_trigger_seconds": 3600.0,
    "recovery_grace_seconds": 600.0,
    "recovery_stall_seconds": 480.0,
    "recovery_hard_ceiling_seconds": 5400.0,
    "recovery_progress_sample_ms": 250.0,
    "recovery_progress_poll_ms": 5000.0,
    "python_wait_seconds": 3600.0,
    "bridge_claim_lease_seconds": 1800.0,
    "queue_ttl_seconds": 86400.0,
    "click_settle_ms": 20.0,
    "thinking_verify_ms": 3000.0,
    "response_settle_ms": 20.0,
    "submission_ack_ms": 1000.0,
}


def load_timeout_policy(path: Path = POLICY_PATH) -> dict[str, float]:
    values: dict[str, float] = dict(DEFAULTS)
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raw = {}
    if isinstance(raw, dict):
        for key in DEFAULTS:
            value = raw.get(key)
            if isinstance(value, (int, float)) and value > 0:
                values[key] = float(value)

    if values["stale_seconds"] < values["heartbeat_seconds"] * 3:
        raise ValueError("timeout policy requires stale_seconds >= 3 * heartbeat_seconds")
    if values["generation_seconds"] < values["recovery_trigger_seconds"]:
        raise ValueError("timeout policy requires generation_seconds >= recovery_trigger_seconds")
    if values["recovery_stall_seconds"] >= values["recovery_hard_ceiling_seconds"]:
        raise ValueError("timeout policy requires recovery_stall_seconds < recovery_hard_ceiling_seconds")
    if values["python_wait_seconds"] < values["generation_seconds"]:
        raise ValueError("timeout policy requires python_wait_seconds >= generation_seconds")
    return values
