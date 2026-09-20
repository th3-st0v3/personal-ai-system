from __future__ import annotations

import json
from pathlib import Path

from scripts.pasi_timeout_policy import POLICY_PATH, load_timeout_policy


def test_shared_timeout_policy_enforces_ordering() -> None:
    policy = load_timeout_policy()
    assert policy["stale_seconds"] >= policy["heartbeat_seconds"] * 3
    assert policy["generation_seconds"] >= policy["recovery_trigger_seconds"]
    assert policy["python_wait_seconds"] >= policy["generation_seconds"]
    assert policy["bridge_claim_lease_seconds"] >= policy["python_wait_seconds"]


def test_browser_json_and_python_loader_are_same_source() -> None:
    raw = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    assert raw["heartbeat_seconds"] == 15
    assert raw["stale_seconds"] == 45
    assert raw["generation_seconds"] == 1500
    assert raw["recovery_trigger_seconds"] == 1500
    assert raw["python_wait_seconds"] == 1800
    assert raw["controller_poll_ms"] == 500
    assert raw["dom_poll_ms"] == 100
    assert raw["click_settle_ms"] == 75
    assert raw["thinking_verify_ms"] == 3000
    assert raw["response_settle_ms"] == 750
    assert raw["submission_ack_ms"] == 2500
