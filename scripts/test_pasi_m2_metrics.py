from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone

from scripts import pasi_m2_metrics as m
from scripts import pasi_stage_events as s

T0 = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)


def iso(ms: float) -> str:
    return (T0 + timedelta(milliseconds=ms)).isoformat()


def ms(dt_ms: float) -> int:
    return int((T0.timestamp() * 1000) + dt_ms)


def stream(prompts: int = 3, dup_at: int | None = None):
    """Synthetic run: each prompt = dispatch(t) -> injected(+400) -> ack(+450) -> gen start(+2000) -> done(+60000);
    then a 5000 ms gate; next dispatch 1000 ms after the gate ends."""
    ev, t = [], 0.0
    for i in range(1, prompts + 1):
        op = f"op-{i}"
        ev.append({"kind": "prompt_dispatch_started", "timestamp": iso(t), "task_id": "T-1", "attempt": i, "queue_file_bytes": 100 + i})
        ev.append({"kind": "prompt_queued", "timestamp": iso(t + 50), "task_id": "T-1", "attempt": i, "operation_id": op})
        ev.append({"kind": "browser_timing", "timestamp": iso(t + 60500), "operation_id": op,
                   "injected_at_ms": ms(t + 400), "ack_at_ms": ms(t + 450), "generation_start_ms": ms(t + 2000),
                   "completed_at_ms": ms(t + 60000), "user_messages_added": 2 if dup_at == i else 1, "ack_verified": True})
        ev.append({"kind": "gate_finished", "timestamp": iso(t + 65000), "tier": 0, "task_id": "T-1", "attempt": i,
                   "result": "pass", "duration_ms": 5000, "classification": "none"})
        t += 60000 + 5000 + 1000
    return ev


class MetricsTests(unittest.TestCase):
    def test_baseline_numbers_come_from_events(self):
        r = m.compute(stream(4))
        self.assertEqual(r["injection_latency_ms"]["median"], 400)
        self.assertEqual(r["submit_ack_ms"]["median"], 50)
        self.assertEqual(r["generation_start_ms"]["median"], 1550)
        self.assertEqual(r["generation_duration_ms"]["median"], 58000)
        # completion -> next injection: gate 5000 + dispatch wait 1000 + injection 400 = 6400 raw
        self.assertEqual(r["completion_to_next_injection_ms"]["median"], 6400)
        self.assertEqual(r["completion_to_next_injection_excl_gates_ms"]["median"], 1400)
        self.assertEqual(r["completion_to_next_dispatch_ms"]["median"], 6000)
        self.assertEqual(r["gate_duration_ms"]["tier0"]["median"], 5000)
        self.assertEqual(r["retries_per_task"]["median"], 3.0)
        self.assertEqual(r["queue_file_bytes"]["median"], 102.5)
        self.assertEqual(r["queue_file_bytes"]["max"], 104)

    def test_m1_counts_duplicates_and_clean_runs(self):
        r = m.compute(stream(6, dup_at=4))
        self.assertEqual(r["m1"]["duplicate_sends"], 1)
        self.assertEqual(r["m1"]["max_consecutive_clean_prompts"], 3)  # prompts 1-3 clean, 4 dup, 5-6 clean

    def test_missing_data_reports_none_not_zero(self):
        r = m.compute([])
        self.assertIsNone(r["completion_to_next_injection_ms"]["median"])
        self.assertEqual(r["prompts_with_timing"], 0)

    def test_tolerates_partial_and_foreign_lines(self):
        lines = [json.dumps(e) for e in stream(2)] + ['{"kind": "task_completed"', "not json", ""]
        self.assertEqual(m.compute(m.load_events(lines))["prompts_with_timing"], 2)

    def test_recovery_and_classification_summaries(self):
        ev = stream(1) + [
            {"kind": "recovery_finished", "timestamp": iso(1), "operation_id": "op-1", "reason": "no_progress", "duration_ms": 90000, "outcome": "resumed"},
            {"kind": "failure_classified", "timestamp": iso(2), "classification": "infra"},
            {"kind": "failure_classified", "timestamp": iso(3), "classification": "code"},
        ]
        r = m.compute(ev)
        self.assertEqual(r["recovery_duration_ms_by_reason"]["no_progress"]["median"], 90000)
        self.assertEqual(r["failure_classification"], {"infra": 1, "code": 1})


class StageEventTests(unittest.TestCase):
    def test_stage_timer_emits_started_then_finished_in_order_with_duration(self):
        out = []
        with s.StageTimer(lambda k, **f: out.append((k, f)), "gate", tier=1, task_id="T", attempt=1) as st:
            st.result = "fail"; st.classification = "code"
        self.assertEqual([k for k, _ in out], ["gate_started", "gate_finished"])
        self.assertEqual(out[1][1]["result"], "fail")
        self.assertGreaterEqual(out[1][1]["duration_ms"], 0)
        self.assertEqual(out[1][1]["tier"], 1)

    def test_stage_timer_marks_exceptions_as_not_evaluated_infra_and_reraises(self):
        out = []
        with self.assertRaises(RuntimeError):
            with s.StageTimer(lambda k, **f: out.append((k, f)), "gate", tier=0):
                raise RuntimeError("runner crashed")
        self.assertEqual(out[-1][1]["result"], "not_evaluated")
        self.assertEqual(out[-1][1]["classification"], "infra")

    def test_classifier_never_blames_code_on_infra_or_ambiguous_evidence(self):
        self.assertEqual(s.classify_failure("gate", 1, "FAILED scripts/test_x.py::t - AssertionError"), "code")
        self.assertEqual(s.classify_failure("gate", 1, "npx: command not found"), "infra")
        self.assertEqual(s.classify_failure("chat", 1, "PASI_NATIVE: Thinking/model selection control unavailable"), "infra")
        self.assertEqual(s.classify_failure("gate", 1, "FAILED t - AssertionError\nnpm ERR! network timeout"), "not_evaluated")
        self.assertEqual(s.classify_failure("gate", 1, "something odd"), "not_evaluated")
        self.assertEqual(s.classify_failure("gate", 0, ""), "not_evaluated")


if __name__ == "__main__":
    unittest.main()