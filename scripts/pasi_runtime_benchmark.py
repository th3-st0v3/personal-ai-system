#!/usr/bin/env python3
"""Deterministic PASI runtime contract benchmark.

This benchmark exercises the existing event/metrics pipeline with a fixed synthetic
20-operation chain and a fixed recovery event. It measures contract behavior only;
it is not a live-browser performance claim.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from pasi_m2_metrics import compute as compute_m2
from pasi_runtime_telemetry import analyze as analyze_runtime
from pasi_runtime_telemetry import render_markdown


BENCHMARK_VERSION = 1
REFERENCE = datetime(2026, 1, 1, tzinfo=timezone.utc)
OUTPUT_DIR = Path(".runtime") / "benchmark"
JSON_OUTPUT = OUTPUT_DIR / "runtime-contract.json"
MARKDOWN_OUTPUT = OUTPUT_DIR / "runtime-contract.md"


def iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def ms(value: datetime) -> float:
    return value.timestamp() * 1000.0


def build_events() -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for index in range(1, 21):
        task_id = f"benchmark-task-{index:02d}"
        start = REFERENCE + timedelta(milliseconds=(index - 1) * 60100)
        dispatch = start
        queued = start + timedelta(milliseconds=50)
        injection = start + timedelta(milliseconds=400)
        ack = start + timedelta(milliseconds=450)
        generation = start + timedelta(seconds=2)
        completed = start + timedelta(seconds=60)
        response = completed + timedelta(milliseconds=50)
        evidence = completed + timedelta(milliseconds=100)
        task_done = completed + timedelta(milliseconds=200)

        events.extend(
            [
                {
                    "timestamp": iso(start),
                    "kind": "task_attempt_started",
                    "task_id": task_id,
                    "task_number": index,
                },
                {
                    "timestamp": iso(dispatch),
                    "kind": "prompt_dispatch_started",
                    "task_id": task_id,
                    "task_number": index,
                    "attempt": 1,
                    "queue_file_bytes": 1024 + index,
                },
                {
                    "timestamp": iso(queued),
                    "kind": "prompt_queued",
                    "task_id": task_id,
                    "attempt": 1,
                    "operation_id": f"bench-op-{index:02d}",
                },
                {
                    "timestamp": iso(injection),
                    "kind": "browser_timing",
                    "operation_id": f"bench-op-{index:02d}",
                    "injected_at_ms": ms(injection),
                    "ack_at_ms": ms(ack),
                    "generation_start_ms": ms(generation),
                    "completed_at_ms": ms(completed),
                    "user_messages_added": 1,
                    "ack_verified": True,
                },
                {
                    "timestamp": iso(response),
                    "kind": "response_received",
                    "task_id": task_id,
                    "task_number": index,
                    "attempt": 1,
                    "operation_id": f"bench-op-{index:02d}",
                    "chars": 1200,
                },
                {
                    "timestamp": iso(evidence),
                    "kind": "task_response_evidence",
                    "task_id": task_id,
                    "attempt": 1,
                    "contract_ok": True,
                    "patch_chars": 900,
                    "evidence_chars": 500,
                },
                {
                    "timestamp": iso(task_done),
                    "kind": "task_completed",
                    "task_id": task_id,
                    "task_number": index,
                    "attempt": 1,
                },
            ]
        )

    recovery_time = REFERENCE + timedelta(milliseconds=20 * 60100 + 1000)
    events.append(
        {
            "timestamp": iso(recovery_time),
            "kind": "recovery_finished",
            "task_id": "benchmark-recovery",
            "task_number": 21,
            "reason": "bridge_restart",
            "duration_ms": 2500,
        }
    )
    return events


def _git_commit() -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def run() -> dict[str, Any]:
    events = build_events()
    runtime = analyze_runtime(events)
    m2 = compute_m2(events)

    checks = {
        "exact_operations": len(events) > 0 and m2["prompts_with_timing"] == 20,
        "zero_duplicate_sends": m2["m1"]["duplicate_sends"] == 0,
        "twenty_clean_prompts": m2["m1"]["max_consecutive_clean_prompts"] == 20,
        "full_completion_rate": runtime.completion_rate == 1.0,
        "no_repeated_task_numbers": runtime.repeated_task_numbers == 0,
        "recovery_metric_present": runtime.recovery_events == 1,
        "handoff_p95_within_contract": (
            runtime.p95_browser_handoff_ms is not None
            and runtime.p95_browser_handoff_ms <= 500.0
        ),
        "m2_injection_p95_bounded": (
            m2["injection_latency_ms"]["p95"] is not None
            and m2["injection_latency_ms"]["p95"] <= 400.0
        ),
    }

    return {
        "benchmark_version": BENCHMARK_VERSION,
        "suite": "pasi-runtime-contract",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "commit": _git_commit(),
        "case": {
            "operation_count": 20,
            "synthetic": True,
            "live_browser_claim": False,
        },
        "checks": checks,
        "runtime_metrics": {
            "events": runtime.events,
            "completion_rate": runtime.completion_rate,
            "repeated_task_numbers": runtime.repeated_task_numbers,
            "browser_handoff_p95_ms": runtime.p95_browser_handoff_ms,
            "browser_ack_p95_ms": runtime.p95_browser_ack_ms,
            "generation_max_ms": max(runtime.browser_generation_samples)
            if runtime.browser_generation_samples
            else None,
            "recovery_events": runtime.recovery_events,
        },
        "m1_m2_metrics": m2,
        "evidence_contract": {
            "event_source": "deterministic synthetic fixture",
            "telemetry_implementation": "scripts/pasi_runtime_telemetry.py",
            "m1_m2_metric_implementation": "scripts/pasi_m2_metrics.py",
        },
    }


def write_outputs(result: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    JSON_OUTPUT.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    events = build_events()
    runtime = analyze_runtime(events)
    lines = [
        "# PASI Runtime Contract Benchmark",
        "",
        f"**Status:** {result['status']}",
        "",
        "This is a deterministic contract benchmark. It does not claim live-browser performance.",
        "",
        "## Contract checks",
        "",
        "| Check | Result |",
        "| --- | --- |",
    ]
    lines.extend(
        f"| {name} | {'PASS' if passed else 'FAIL'} |"
        for name, passed in result["checks"].items()
    )
    lines.extend(
        [
            "",
            "## Runtime metrics",
            "",
            f"- Completion rate: {runtime.completion_rate:.1%}",
            f"- Repeated task numbers: {runtime.repeated_task_numbers}",
            f"- Browser handoff P95: {runtime.p95_browser_handoff_ms:.1f} ms",
            f"- Browser acknowledgment P95: {runtime.p95_browser_ack_ms:.1f} ms",
            f"- Generation maximum: {max(runtime.browser_generation_samples):.1f} ms",
            f"- Recovery events: {runtime.recovery_events}",
            "",
            "## Interpretation boundary",
            "",
            "A PASS here proves the event schema, metric calculations, and deterministic invariants stay internally consistent. It does not replace M0/M1/M2 authenticated Chromium acceptance.",
            "",
        ]
    )
    MARKDOWN_OUTPUT.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    result = run()
    write_outputs(result)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
