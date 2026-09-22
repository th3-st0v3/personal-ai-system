from __future__ import annotations

import json
from pathlib import Path

from scripts.validate_p0_acceptance_artifacts import validate, validate_m1, validate_m2, validate_p04


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def test_validator_requires_all_live_gate_artifacts(tmp_path: Path) -> None:
    errors = validate(tmp_path, require_live_gates=True)
    assert "M0 artifact is missing" in errors
    assert "M1 artifact is missing" in errors
    assert "M2 artifact is missing" in errors
    assert "P0.4 artifact is missing" in errors


def test_m1_validator_rejects_wrong_count_and_delta(tmp_path: Path) -> None:
    path = tmp_path / "m1-live.json"
    write_json(
        path,
        {
            "gate": "M1",
            "status": "PASS",
            "count": 19,
            "completed_count": 19,
            "false_terminal_chat_verdicts": 0,
            "results": [
                {
                    "index": 1,
                    "operation_id": "op-1",
                    "completion": "complete",
                    "user_delta": 2,
                    "assistant_delta": 1,
                    "marker": "marker",
                }
            ],
        },
    )
    errors = validate_m1(path)
    assert any("exactly 20" in error for error in errors)
    assert any("non-1/+1" in error for error in errors)


def test_m2_validator_rejects_identity_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "m2-live.json"
    write_json(
        path,
        {
            "gate": "M2",
            "status": "PASS",
            "operation_id": "op-1",
            "latest_operation": {"operation_id": "op-2", "response_text": "M2-LIVE-x"},
            "bridge_restart_verified": True,
            "runner_restart_verified": True,
            "duplicate_user_message_delta": 0,
            "pre_restart_chat_url": "https://chatgpt.com/c/test",
            "latest_state": {"data": {"chat_url": "https://chatgpt.com/c/test"}},
            "prompt": "M2 live recovery: reply exactly M2-LIVE-x",
            "handoff_cleared_after_completion": True,
        },
    )
    errors = validate_m2(path)
    assert "M2 final operation identity does not match" in errors


def test_p04_validator_requires_verified_acceptance_checks(tmp_path: Path) -> None:
    path = tmp_path / "p0.4-long-run-evidence.json"
    write_json(
        path,
        {
            "gate": "P0.4",
            "status": "PASS",
            "acceptance_checks": {
                "failures": [],
                "branch_matches": False,
                "worktree_clean": True,
                "resource_sample_count": 12,
                "pr_verified": False,
            },
        },
    )
    errors = validate_p04(path)
    assert "P0.4 branch identity is not verified" in errors
    assert "P0.4 PR provenance is not verified" in errors
