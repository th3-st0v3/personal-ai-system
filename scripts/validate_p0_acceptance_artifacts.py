#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read valid JSON: {path}") from exc


def validate_m0(path: Path) -> list[str]:
    value = read_json(path)
    errors: list[str] = []
    if not isinstance(value, dict) or value.get("gate") != "M0" or value.get("status") != "PASS":
        errors.append("M0 artifact is not a PASS")
        return errors
    proof_file = value.get("proof_file")
    if not isinstance(proof_file, str) or not proof_file:
        errors.append("M0 proof_file is missing")
    else:
        proof = Path(proof_file)
        try:
            if proof.read_text(encoding="utf-8") != "PASI M0 LIVE PROOF":
                errors.append("M0 proof file content is not exact")
        except OSError:
            errors.append("M0 proof file is unavailable")
    return errors


def validate_m1(path: Path) -> list[str]:
    value = read_json(path)
    errors: list[str] = []
    if not isinstance(value, dict) or value.get("gate") != "M1" or value.get("status") != "PASS":
        errors.append("M1 artifact is not a PASS")
        return errors
    if value.get("count") != 20 or value.get("completed_count") != 20:
        errors.append("M1 does not report exactly 20 completed operations")
    if value.get("false_terminal_chat_verdicts") != 0:
        errors.append("M1 reports terminal CHAT_* verdicts")
    results = value.get("results")
    if not isinstance(results, list) or len(results) != 20:
        errors.append("M1 results do not contain exactly 20 entries")
        return errors
    operation_ids: set[str] = set()
    indexes: list[int] = []
    for entry in results:
        if not isinstance(entry, dict):
            errors.append("M1 result entry is not an object")
            continue
        operation_id = entry.get("operation_id")
        if not isinstance(operation_id, str) or not operation_id.strip():
            errors.append("M1 result is missing operation_id")
        elif operation_id in operation_ids:
            errors.append("M1 contains a duplicate operation_id")
        else:
            operation_ids.add(operation_id)
        indexes.append(entry.get("index", 0) if isinstance(entry.get("index", 0), int) else 0)
        if entry.get("completion") != "complete":
            errors.append("M1 contains a non-complete operation")
        if entry.get("user_delta") != 1 or entry.get("assistant_delta") != 1:
            errors.append("M1 contains a non-1/+1 conversation delta")
        marker = entry.get("marker")
        if not isinstance(marker, str) or not marker.strip():
            errors.append("M1 result is missing its unique marker")
    if indexes != list(range(1, 21)):
        errors.append("M1 result indexes are not exactly 1..20 in order")
    if int(value.get("duplicate_message_deltas", 0) or 0) != 0:
        errors.append("M1 reports duplicate message deltas")
    return errors


def validate_m2(path: Path) -> list[str]:
    value = read_json(path)
    errors: list[str] = []
    if not isinstance(value, dict) or value.get("gate") != "M2" or value.get("status") != "PASS":
        errors.append("M2 artifact is not a PASS")
        return errors
    operation_id = value.get("operation_id")
    latest_operation = value.get("latest_operation")
    if not isinstance(operation_id, str) or not operation_id.strip():
        errors.append("M2 operation_id is missing")
        return errors
    if not isinstance(latest_operation, dict) or latest_operation.get("operation_id") != operation_id:
        errors.append("M2 final operation identity does not match")
    if isinstance(latest_operation, dict) and latest_operation.get("status") != "completed":
        errors.append("M2 final operation is not completed")
    if value.get("bridge_restart_verified") is not True or value.get("runner_restart_verified") is not True:
        errors.append("M2 did not verify both bridge and runner restart")
    if value.get("duplicate_user_message_delta") != 0:
        errors.append("M2 reports a duplicate user-message delta")
    before = str(value.get("pre_restart_chat_url") or "")
    latest_state = value.get("latest_state")
    latest_data = (
        latest_state.get("data")
        if isinstance(latest_state, dict) and isinstance(latest_state.get("data"), dict)
        else latest_state
    )
    after = str(latest_data.get("chat_url") or "") if isinstance(latest_data, dict) else ""
    if not before or not after or before != after:
        errors.append("M2 did not preserve exact conversation identity")
    response_text = str(latest_operation.get("response_text") or "")
    prompt = str(value.get("prompt") or "")
    import re
    match = re.search(r"M2-LIVE-[0-9]{8}-[0-9]{6}-[0-9]+", prompt)
    marker = match.group(0) if match else ""
    if marker and marker not in response_text:
        errors.append("M2 final response does not contain its original marker")
    if value.get("manual_tab_recovery_recorded") is not True:
        errors.append("M2 manual tab recovery was not explicitly recorded")
    if value.get("handoff_cleared_after_completion") is not True:
        errors.append("M2 did not verify active-operation handoff clearance")
    return errors


def validate_p04(path: Path) -> list[str]:
    value = read_json(path)
    errors: list[str] = []
    if not isinstance(value, dict) or value.get("gate") != "P0.4" or value.get("status") != "PASS":
        errors.append("P0.4 artifact is not a PASS")
        return errors
    checks = value.get("acceptance_checks")
    if not isinstance(checks, dict):
        errors.append("P0.4 acceptance_checks is missing")
        return errors
    if checks.get("failures") not in ([], None):
        errors.append("P0.4 reports acceptance failures")
    if checks.get("branch_matches") is not True:
        errors.append("P0.4 branch identity is not verified")
    if checks.get("worktree_clean") is not True:
        errors.append("P0.4 worktree is not verified clean")
    if checks.get("pr_verified") is not True:
        errors.append("P0.4 PR provenance is not verified")
    if checks.get("pr_head_matches") is not True:
        errors.append("P0.4 PR head does not match final Git HEAD")
    if not isinstance(checks.get("resource_sample_count"), int) or checks["resource_sample_count"] <= 0:
        errors.append("P0.4 has no historical resource samples")
    return errors


def validate(runtime_dir: Path, require_live_gates: bool) -> list[str]:
    errors: list[str] = []
    acceptance = runtime_dir / "acceptance"
    required = {
        "M0": acceptance / "m0-live.json",
        "M1": acceptance / "m1-live.json",
        "M2": None,
        "P0.4": runtime_dir / "p0.4-long-run-evidence.json",
    }
    if not required["M0"].is_file():
        errors.append("M0 artifact is missing")
    elif require_live_gates:
        errors.extend(validate_m0(required["M0"]))
    if not required["M1"].is_file():
        errors.append("M1 artifact is missing")
    elif require_live_gates:
        errors.extend(validate_m1(required["M1"]))

    m2_files = sorted(acceptance.glob("m2-live-*.json"))
    if not m2_files:
        errors.append("M2 artifact is missing")
    elif require_live_gates:
        pass
    if required["P0.4"].is_file():
        if require_live_gates:
            errors.extend(validate_p04(required["P0.4"]))
    elif require_live_gates:
        errors.append("P0.4 artifact is missing")

    if m2_files and require_live_gates:
        latest_m2 = max(m2_files, key=lambda path: path.stat().st_mtime)
        errors.extend(validate_m2(latest_m2))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate PASI live acceptance artifacts before changing roadmap gate status.")
    parser.add_argument("--runtime-dir", type=Path, default=Path("~/.pasi/overnight"))
    parser.add_argument("--require-live-gates", action="store_true")
    args = parser.parse_args()

    runtime_dir = args.runtime_dir.expanduser().resolve()
    errors = validate(runtime_dir, args.require_live_gates)
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 2
    print("P0 ACCEPTANCE ARTIFACTS STRUCTURALLY VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
