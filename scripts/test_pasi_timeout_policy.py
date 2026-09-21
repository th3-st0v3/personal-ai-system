from pathlib import Path
import json

from scripts.pasi_timeout_policy import load_timeout_policy


ROOT = Path(__file__).resolve().parents[1]


def test_browser_json_and_python_loader_share_the_same_normal_path_policy() -> None:
    raw = json.loads(
        (ROOT / "automation" / "chromium" / "pasi-chatgpt" / "timeout-policy.json").read_text(
            encoding="utf-8"
        )
    )
    policy = load_timeout_policy()
    assert raw["heartbeat_seconds"] == 15
    assert raw["stale_seconds"] == 45
    assert raw["controller_poll_ms"] == 2000
    assert raw["dom_poll_ms"] == 100
    assert raw["click_settle_ms"] == 250
    assert raw["thinking_verify_ms"] == 3000
    assert raw["response_settle_ms"] == 10
    assert raw["submission_ack_ms"] == 1000
    assert raw["generation_seconds"] == 3600
    assert raw["recovery_trigger_seconds"] == 3600
    assert raw["recovery_grace_seconds"] == 600
    assert raw["recovery_stall_seconds"] == 480
    assert raw["recovery_hard_ceiling_seconds"] == 5400
    assert raw["recovery_progress_sample_ms"] == 250
    assert raw["recovery_progress_poll_ms"] == 5000
    assert raw["python_wait_seconds"] == 3600
    assert policy["controller_poll_ms"] == 2000
    assert policy["heartbeat_seconds"] == 15
    assert policy["stale_seconds"] == 45
    assert policy["dom_poll_ms"] == 100
    assert policy["click_settle_ms"] == 250
    assert policy["response_settle_ms"] == 10
    assert policy["submission_ack_ms"] == 1000
    assert policy["generation_seconds"] == 3600
    assert policy["recovery_trigger_seconds"] == 3600
    assert policy["recovery_stall_seconds"] == 480
    assert policy["recovery_hard_ceiling_seconds"] == 5400
    assert policy["recovery_progress_sample_ms"] == 250
    assert policy["recovery_progress_poll_ms"] == 5000
    assert policy["python_wait_seconds"] == 3600


def test_timeout_policy_uses_fast_defaults_when_file_is_absent() -> None:
    policy = load_timeout_policy(ROOT / "missing-timeout-policy.json")
    assert policy["menu_ms"] == 5000
    assert policy["composer_ms"] == 10000
    assert policy["send_ms"] == 5000
    assert policy["submit_ms"] == 2500
    assert policy["dom_poll_ms"] == 100
    assert policy["response_settle_ms"] == 10


def test_timeout_policy_enforces_safe_relationships() -> None:
    policy = load_timeout_policy()
    assert policy["stale_seconds"] >= policy["heartbeat_seconds"] * 3
    assert policy["generation_seconds"] >= policy["recovery_trigger_seconds"]
    assert policy["recovery_stall_seconds"] < policy["recovery_hard_ceiling_seconds"]
    assert policy["python_wait_seconds"] >= policy["generation_seconds"]
