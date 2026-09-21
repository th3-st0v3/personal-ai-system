from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts import pasi_runtime_telemetry as telemetry


class TestPasiRuntimeTelemetry(unittest.TestCase):
    def test_analyzer_measures_churn_short_responses_and_latency(self) -> None:
        events = [
            {"timestamp": "2026-09-20T20:00:00+00:00", "kind": "task_attempt_started", "task_id": "a", "task_number": 1},
            {"timestamp": "2026-09-20T20:00:10+00:00", "kind": "prompt_dispatch_started", "task_id": "a", "task_number": 1},
            {"timestamp": "2026-09-20T20:00:11+00:00", "kind": "response_received", "task_id": "a", "task_number": 1, "chars": 200},
            {"timestamp": "2026-09-20T20:00:12+00:00", "kind": "task_completed", "task_id": "a", "task_number": 1},
            {"timestamp": "2026-09-20T20:01:00+00:00", "kind": "prompt_compiled", "prompt_chars": 3400},
            {"timestamp": "2026-09-20T20:01:10+00:00", "kind": "task_attempt_started", "task_id": "a", "task_number": 2},
            {"timestamp": "2026-09-20T20:01:20+00:00", "kind": "prompt_dispatch_started", "task_id": "a", "task_number": 2},
            {"timestamp": "2026-09-20T20:01:21+00:00", "kind": "response_received", "task_id": "a", "task_number": 2, "chars": 220},
            {"timestamp": "2026-09-20T20:01:22+00:00", "kind": "task_failed", "task_id": "a", "task_number": 2},
            {"timestamp": "2026-09-20T20:01:22+00:00", "kind": "task_failed", "task_id": "a", "task_number": 2},
            {"timestamp": "2026-09-20T20:01:23+00:00", "kind": "task_response_evidence", "contract_ok": True, "response_chars": 1200, "patch_chars": 900, "evidence_chars": 140},
            {"timestamp": "2026-09-20T20:01:24+00:00", "kind": "browser_timing", "injected_at_ms": 200000, "ack_at_ms": 200020, "generation_start_ms": 200100, "completed_at_ms": 201100},
            {"timestamp": "2026-09-20T20:01:25+00:00", "kind": "browser_timing", "injected_at_ms": 201155, "ack_at_ms": 201175, "generation_start_ms": 201300, "completed_at_ms": 202300},
        ]
        report = telemetry.analyze(events)
        self.assertEqual(report.events, len(events))
        self.assertEqual(report.task_attempts, 2)
        self.assertEqual(report.completed_tasks, 1)
        self.assertEqual(report.failed_tasks, 1)
        self.assertEqual(report.repeated_task_numbers, 1)
        self.assertEqual(report.short_responses, 2)
        self.assertEqual(report.short_response_streak_max, 2)
        self.assertEqual(report.prompt_sizes, (3400,))
        self.assertEqual(len(report.response_latency_samples), 2)
        self.assertEqual(len(report.response_to_next_dispatch_samples), 1)
        self.assertEqual(len(report.browser_handoff_samples), 1)
        self.assertEqual(len(report.browser_ack_samples), 2)
        self.assertEqual(len(report.browser_generation_samples), 2)
        self.assertEqual(report.accepted_patch_sizes, (900,))
        self.assertEqual(report.accepted_evidence_sizes, (140,))
        self.assertEqual(report.thin_evidence_count, 1)
        self.assertAlmostEqual(report.response_latency_samples[0], 1000.0)
        self.assertAlmostEqual(report.response_latency_samples[1], 1000.0)
        self.assertAlmostEqual(report.response_to_next_dispatch_samples[0], 49000.0)
        self.assertAlmostEqual(report.browser_handoff_samples[0], 55.0)
        self.assertAlmostEqual(report.browser_ack_samples[0], 20.0)
        self.assertAlmostEqual(report.browser_generation_samples[1], 1000.0)

    def test_malformed_json_is_counted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            path.write_text(
                '{"timestamp":"2026-09-20T20:00:00+00:00","kind":"task_completed"}\n'
                'not-json\n'
                '{"kind":123}\n',
                encoding="utf-8",
            )
            events, malformed = telemetry.load_events(path)
        self.assertEqual(len(events), 1)
        self.assertEqual(malformed, 2)

    def test_render_marks_three_short_responses_for_attention(self) -> None:
        events = [
            {"timestamp": f"2026-09-20T20:00:0{i}+00:00", "kind": "response_received", "chars": 100}
            for i in range(1, 4)
        ]
        report = telemetry.render_markdown(telemetry.analyze(events))
        self.assertIn("**Status:** ATTENTION", report)
        self.assertIn("three or more short responses", report)

    def test_report_does_not_claim_short_responses_are_incorrect(self) -> None:
        report = telemetry.render_markdown(telemetry.RuntimeReport(
            events=1,
            malformed_lines=0,
            task_attempts=0,
            completed_tasks=1,
            failed_tasks=0,
            repeated_task_numbers=0,
            short_responses=1,
            short_response_streak_max=1,
            response_latency_samples=(),
            response_to_next_dispatch_samples=(),
            browser_handoff_samples=(),
            browser_ack_samples=(),
            browser_generation_samples=(),
            accepted_patch_sizes=(),
            accepted_evidence_sizes=(),
            thin_evidence_count=0,
            prompt_sizes=(),
            recovery_events=0,
            provider_limit_events=0,
            auth_events=0,
        ))
        self.assertIn("does not declare a short response incorrect", report)


if __name__ == "__main__":
    unittest.main()
