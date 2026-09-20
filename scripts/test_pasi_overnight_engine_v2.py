from __future__ import annotations

import tempfile
import unittest
from unittest import mock
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts import pasi_overnight_engine_v2 as engine


class TestPasiOvernightEngineV2(unittest.TestCase):

    def test_parse_response_records_optional_automation_continue(self) -> None:
        response = """PASI_RESULT_STATUS: complete
PASI_RESULT_SUMMARY: fixed the issue
PASI_RESULT_NEXT_TASK: improve automation
PASI_RESULT_REQUIREMENTS: complete
PASI_RESULT_LIMITATIONS: handled
PASI_RESULT_RESEARCH: performed
PASI_RESULT_UX: verified
PASI_RESULT_BACKEND: verified
PASI_RESULT_EVIDENCE: pytest passed
PASI_RESULT_REPOSITORY_PROGRESS: changed
PASI_RESULT_ALLOW_DELETE: false
PASI_AUTOMATION_CONTINUE: true
PASI_RESULT_PATCH_BEGIN
diff --git a/example.txt b/example.txt
--- a/example.txt
+++ b/example.txt
@@ -1 +1 @@
-old
+new
PASI_RESULT_PATCH_END
"""
        *_, values = engine.parse_response(response)
        self.assertEqual(values["automation_continue"], "true")

    def test_automation_gate_reads_durable_task_evidence(self) -> None:
        now = datetime.now(timezone.utc)
        state = engine.OvernightState(
            schema_version=2,
            run_id="gate-test",
            started_at=now.isoformat(),
            deadline_at=(now + timedelta(hours=8)).isoformat(),
            worktree=str(Path.cwd()),
            branch="test",
            phase="automation",
            current_task=engine.AUTOMATION_TASKS[0],
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger_path = Path(temp_dir) / "task-ledger.json"
            with mock.patch.object(engine, "TASK_LEDGER_PATH", ledger_path):
                engine.record_task_ledger(
                    engine.AUTOMATION_TASKS[0],
                    "completed",
                    evidence="verified automation fix",
                    phase="automation",
                )
                engine.record_task_ledger(
                    engine.AUTOMATION_TASKS[1],
                    "completed",
                    evidence="verified second automation fix",
                    phase="automation",
                )
                evidence = engine.automation_gate_evidence(state)
                self.assertEqual(evidence["automation_gate"], "proceed_engineering")
                engine.record_task_ledger(
                    engine.AUTOMATION_TASKS[1],
                    "completed",
                    evidence="there is still a browser recovery improvement to implement",
                    phase="automation",
                    automation_continue=True,
                )
                evidence = engine.automation_gate_evidence(state)
                self.assertEqual(evidence["automation_gate"], "continue_automation")

    def test_automation_gate_requires_consistent_evidence(self) -> None:
        self.assertTrue(
            engine.automation_gate_is_satisfied(
                {
                    "automation_gate": "proceed_engineering",
                    "automation_opportunity": "none",
                    "automation_evidence": "Repeated automation audits found no concrete remaining reliability improvement.",
                }
            )
        )
        self.assertTrue(
            engine.automation_gate_is_satisfied(
                {
                    "automation_gate": "continue_automation",
                    "automation_opportunity": "concrete",
                    "automation_evidence": "A verified controller failure mode still has a concrete fix.",
                }
            )
        )
        self.assertFalse(
            engine.automation_gate_is_satisfied(
                {
                    "automation_gate": "proceed_engineering",
                    "automation_opportunity": "concrete",
                    "automation_evidence": "There is still a concrete fix.",
                }
            )
        )
        self.assertFalse(
            engine.automation_gate_is_satisfied(
                {
                    "automation_gate": "continue_automation",
                    "automation_opportunity": "none",
                    "automation_evidence": "No concrete automation work remains.",
                }
            )
        )

    def test_unexpected_early_exit_is_not_treated_as_operator_stop(self) -> None:
        finish_reason = getattr(engine, "finish_reason")
        self.assertEqual(finish_reason(stop_requested=False, deadline_reached=False), "unexpected_early_exit")
        self.assertEqual(finish_reason(stop_requested=True, deadline_reached=False), "stopped")
        self.assertEqual(finish_reason(stop_requested=True, deadline_reached=True), "deadline_reached")

    def test_controller_observation_requires_current_release_version(self) -> None:
        now = datetime.now(timezone.utc)
        timestamp = now.isoformat()
        current = {
            "kind": "chatgpt_state",
            "controller_version": "2.4.11",
            "captured_at": timestamp,
        }
        stale = dict(current, controller_version="2.4.10")
        missing = dict(current)
        missing.pop("controller_version")

        with mock.patch(
            "scripts.pasi_overnight_engine_v2.expected_controller_version",
            return_value="2.4.11",
        ):
            with mock.patch.object(engine, "browser_observation", side_effect=[current, stale, missing]):
                self.assertTrue(engine.runtime_watchdog_is_live())
                self.assertFalse(engine.runtime_watchdog_is_live())
                self.assertFalse(engine.runtime_watchdog_is_live())

    def test_build_prompt_contains_anti_loop_continuation_rule(self) -> None:
        now = datetime.now(timezone.utc)
        state = engine.OvernightState(
            schema_version=2,
            run_id="prompt-test",
            started_at=now.isoformat(),
            deadline_at=(now + timedelta(hours=8)).isoformat(),
            worktree=str(Path.cwd()),
            branch="test",
            phase="engineering_os",
            current_task="Improve task continuation",
            recent_tasks=["already completed task"],
        )
        prompt = engine.build_prompt(state.current_task, state)
        self.assertIn("TASK CONTINUATION:", prompt)
        self.assertIn("Keep working on the CURRENT TASK until the requirement is implemented, tested, diagnosed, and verified.", prompt)
        self.assertRegex(
            prompt,
            r"immediately (?:work on|continue to) the next incomplete roadmap (?:item|task)",
        )
        self.assertIn("If the same failure repeats, change approach", prompt)
        self.assertIn("do not invent work or cosmetic changes", prompt)
        self.assertNotIn("KEEP WORKING UNTIL YOU'RE FINISHED:", prompt)
        self.assertNotIn("Keep inspecting, implementing, testing, diagnosing, and repairing", prompt)
        self.assertIn("RECENT TASKS:", prompt)
        self.assertIn("PASI_RESULT_REPOSITORY_PROGRESS: changed|stopped", prompt)
        self.assertIn("PASI_AUTOMATION_CONTINUE: true", prompt)
        self.assertIn("machine-read as task evidence", prompt)
        self.assertIn("empty patch", prompt)
        self.assertNotIn("PASI_RESULT_REPOSITORY_PROGRESS: ongoing", prompt)

    def test_cross_run_loop_guard_skips_repeated_roadmap_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            guard_path = Path(temp_dir) / "roadmap-loop-guard.json"
            with mock.patch.object(engine, "ROADMAP_LOOP_GUARD_PATH", guard_path):
                first, guarded, repeats = getattr(engine, "choose_run_start_task")("automation", "", "run-1")
                self.assertEqual(first, engine.AUTOMATION_TASKS[0])
                self.assertFalse(guarded)
                self.assertEqual(repeats, 0)

                second, guarded, repeats = getattr(engine, "choose_run_start_task")("automation", "", "run-2")
                self.assertEqual(second, engine.AUTOMATION_TASKS[0])
                self.assertFalse(guarded)
                self.assertEqual(repeats, 1)

                third, guarded, repeats = getattr(engine, "choose_run_start_task")("automation", "", "run-3")
                self.assertEqual(third, engine.AUTOMATION_TASKS[1])
                self.assertTrue(guarded)
                self.assertEqual(repeats, 2)

                history = getattr(engine, "load_roadmap_selection_history")()
                self.assertEqual([item["task"] for item in history[-3:]], [
                    engine.AUTOMATION_TASKS[0],
                    engine.AUTOMATION_TASKS[0],
                    engine.AUTOMATION_TASKS[1],
                ])

    def test_cross_run_loop_guard_preserves_custom_task(self) -> None:
        custom = "Do this explicitly requested task."
        with tempfile.TemporaryDirectory() as temp_dir:
            guard_path = Path(temp_dir) / "roadmap-loop-guard.json"
            with mock.patch.object(engine, "ROADMAP_LOOP_GUARD_PATH", guard_path):
                for run_id in ("run-1", "run-2", "run-3"):
                    selected, guarded, repeats = getattr(engine, "choose_run_start_task")("automation", custom, run_id)
                    self.assertEqual(selected, custom)
                    self.assertFalse(guarded)
                    self.assertEqual(repeats, 0)
                self.assertEqual(getattr(engine, "load_roadmap_selection_history")(), [])

    def test_same_task_suggestion_advances_to_next_roadmap_item(self) -> None:
        now = datetime.now(timezone.utc)
        current = engine.AUTOMATION_TASKS[1]
        state = engine.OvernightState(
            schema_version=2,
            run_id="forward-progress-test",
            started_at=now.isoformat(),
            deadline_at=(now + timedelta(hours=8)).isoformat(),
            worktree=str(Path.cwd()),
            branch="test",
            phase="automation",
            current_task=current,
            recent_tasks=list(engine.AUTOMATION_TASKS),
        )
        self.assertEqual(engine.choose_next_task(state, current), engine.AUTOMATION_TASKS[2])

    def test_failed_task_is_excluded_before_next_selection(self) -> None:
        now = datetime.now(timezone.utc)
        failed = engine.AUTOMATION_TASKS[0]
        state = engine.OvernightState(
            schema_version=2,
            run_id="failed-task-test",
            started_at=now.isoformat(),
            deadline_at=(now + timedelta(hours=8)).isoformat(),
            worktree=str(Path.cwd()),
            branch="test",
            phase="automation",
            current_task=failed,
            recent_tasks=[failed],
        )
        self.assertEqual(engine.choose_next_task(state, ""), engine.AUTOMATION_TASKS[1])

    def test_provider_conditions_are_distinct_from_chat_completion_failures(self) -> None:
        self.assertEqual(engine.provider_condition(90, "CHAT_USAGE_LIMITED: provider limit"), "provider_usage_limit")
        self.assertEqual(engine.provider_condition(91, "CHAT_AUTH_REQUIRED: login"), "auth_required")
        self.assertEqual(engine.provider_condition(92, "CHAT_GUARD_TIMEOUT: timeout"), "runtime_guard")
        self.assertIsNone(engine.provider_condition(1, "CHAT_EXHAUSTED: conversation context"))

    def test_auth_recovery_waits_for_interactive_recovery_before_resuming_same_session(self) -> None:
        now = datetime.now(timezone.utc)
        state = engine.OvernightState(
            schema_version=2,
            run_id="auth-recovery-test",
            started_at=now.isoformat(),
            deadline_at=(now + timedelta(minutes=5)).isoformat(),
            worktree=str(Path.cwd()),
            branch="test",
            phase="automation",
            current_task=engine.AUTOMATION_TASKS[0],
        )
        with mock.patch.object(engine, "ensure_services", return_value=[]):
            with mock.patch.object(engine, "browser_auth_required", side_effect=[True, False]):
                with mock.patch.object(engine, "runtime_watchdog_is_live", return_value=True):
                    with mock.patch.object(engine, "log_event") as log_event:
                        with mock.patch("time.sleep"):
                            self.assertTrue(engine.standby_until_ready(state, wait_for_auth=True, max_wait_seconds=30.0))
        events = [call.args[0] for call in log_event.call_args_list if call.args]
        self.assertIn("auth_recovery_wait_started", events)
        self.assertIn("standby_recovered", events)

    def test_auth_condition_is_deferred_before_provider_fallback(self) -> None:
        now = datetime.now(timezone.utc)
        state = engine.OvernightState(
            schema_version=2,
            run_id="auth-boundary-test",
            started_at=now.isoformat(),
            deadline_at=(now + timedelta(minutes=5)).isoformat(),
            worktree=str(Path.cwd()),
            branch="test",
            phase="automation",
            current_task=engine.AUTOMATION_TASKS[0],
        )
        with mock.patch.object(
            engine,
            "command",
            return_value=(91, "CHAT_AUTH_REQUIRED: interactive authentication is required"),
        ) as command:
            code, output = engine.invoke_chat(state.current_task, state, "")
        self.assertEqual(code, 91)
        self.assertIn("CHAT_AUTH_REQUIRED", output)
        self.assertEqual(command.call_count, 1)

    def test_failed_fallback_router_enters_bounded_cooldown(self) -> None:
        now = datetime.now(timezone.utc)
        state = engine.OvernightState(
            schema_version=2,
            run_id="fallback-cooldown-test",
            started_at=now.isoformat(),
            deadline_at=(now + timedelta(hours=1)).isoformat(),
            worktree=str(Path.cwd()),
            branch="test",
            phase="automation",
            current_task=engine.AUTOMATION_TASKS[0],
        )
        responses = iter((
            (90, "CHAT_USAGE_LIMITED: provider limit"),
            (1, "all configured fallback providers failed: ollama: no model; openrouter: HTTP 429 after bounded 429 retry"),
        ))
        with mock.patch.object(engine, "command", side_effect=lambda *args, **kwargs: next(responses)) as command:
            with mock.patch.object(engine, "save_state") as save_state:
                code, output = engine.invoke_chat(state.current_task, state, "")
        self.assertEqual(code, 90)
        self.assertIn("PASI FALLBACK ROUTER", output)
        self.assertFalse(engine.fallback_router_available(state))
        self.assertEqual(command.call_count, 2)
        save_state.assert_called_once()

    def test_fallback_cooldown_skips_router_without_losing_primary_provider_condition(self) -> None:
        now = datetime.now(timezone.utc)
        state = engine.OvernightState(
            schema_version=2,
            run_id="fallback-skip-test",
            started_at=now.isoformat(),
            deadline_at=(now + timedelta(hours=1)).isoformat(),
            worktree=str(Path.cwd()),
            branch="test",
            phase="automation",
            current_task=engine.AUTOMATION_TASKS[0],
            fallback_router_disabled_until=(now + timedelta(minutes=5)).isoformat(),
        )
        with mock.patch.object(engine, "command", return_value=(90, "CHAT_USAGE_LIMITED: provider limit")) as command:
            code, output = engine.invoke_chat(state.current_task, state, "")
        self.assertEqual(code, 90)
        self.assertIn("PASI FALLBACK ROUTER SKIPPED", output)
        self.assertEqual(command.call_count, 1)

    def test_successful_fallback_clears_previous_cooldown(self) -> None:
        now = datetime.now(timezone.utc)
        state = engine.OvernightState(
            schema_version=2,
            run_id="fallback-clear-test",
            started_at=now.isoformat(),
            deadline_at=(now + timedelta(hours=1)).isoformat(),
            worktree=str(Path.cwd()),
            branch="test",
            phase="automation",
            current_task=engine.AUTOMATION_TASKS[0],
            fallback_router_disabled_until=(now - timedelta(seconds=1)).isoformat(),
        )
        with mock.patch.object(
            engine,
            "command",
            side_effect=((90, "CHAT_USAGE_LIMITED: provider limit"), (0, "fallback response")),
        ):
            with mock.patch.object(engine, "save_state") as save_state:
                code, output = engine.invoke_chat(state.current_task, state, "")
        self.assertEqual((code, output), (0, "fallback response"))
        self.assertEqual(state.fallback_router_disabled_until, "")
        self.assertGreaterEqual(save_state.call_count, 1)

    def test_auth_recovery_wait_budget_is_bounded(self) -> None:
        now = datetime.now(timezone.utc)
        state = engine.OvernightState(
            schema_version=2,
            run_id="auth-budget-test",
            started_at=now.isoformat(),
            deadline_at=(now + timedelta(minutes=5)).isoformat(),
            worktree=str(Path.cwd()),
            branch="test",
            phase="automation",
            current_task=engine.AUTOMATION_TASKS[0],
        )
        with mock.patch.object(engine, "ensure_services", return_value=[]):
            with mock.patch.object(engine, "browser_auth_required", return_value=True):
                with mock.patch.object(engine, "runtime_watchdog_is_live", return_value=False):
                    with mock.patch.object(engine, "log_event"):
                        with mock.patch("time.sleep"):
                            with mock.patch.object(
                                engine,
                                "now_utc",
                                side_effect=[
                                    now,
                                    now,
                                    now,
                                    now + timedelta(seconds=2),
                                    now + timedelta(seconds=6),
                                    now + timedelta(seconds=6),
                                    now + timedelta(seconds=6),
                                ],
                            ):
                                self.assertFalse(engine.standby_until_ready(state, wait_for_auth=True, max_wait_seconds=5.0))

    def test_choose_next_task_ignores_non_roadmap_suggestion(self) -> None:
        now = datetime.now(timezone.utc)
        state = engine.OvernightState(
            schema_version=2,
            run_id="non-roadmap-test",
            started_at=now.isoformat(),
            deadline_at=(now + timedelta(hours=8)).isoformat(),
            worktree=str(Path.cwd()),
            branch="test",
            phase="automation",
            current_task=engine.AUTOMATION_TASKS[0],
            recent_tasks=[],
        )
        self.assertEqual(
            engine.choose_next_task(state, "invented task outside roadmap"),
            engine.AUTOMATION_TASKS[0],
        )

    def test_unique_task_selection_avoids_recent_tasks(self) -> None:
        now = datetime.now(timezone.utc)
        state = engine.OvernightState(
            schema_version=2,
            run_id="test",
            started_at=now.isoformat(),
            deadline_at=(now + timedelta(hours=8)).isoformat(),
            worktree=str(Path.cwd()),
            branch="test",
            phase="automation",
            current_task="",
            requested_task="",
            recent_tasks=[engine.AUTOMATION_TASKS[0]],
        )
        self.assertEqual(engine.choose_unique(engine.AUTOMATION_TASKS, state), engine.AUTOMATION_TASKS[1])

    def test_standby_self_heals_local_services_before_waiting_for_browser(self) -> None:
        now = datetime.now(timezone.utc)
        state = engine.OvernightState(
            schema_version=2,
            run_id="standby-service-recovery",
            started_at=now.isoformat(),
            deadline_at=(now + timedelta(minutes=5)).isoformat(),
            worktree=str(Path.cwd()),
            branch="test",
            phase="automation",
            current_task=engine.AUTOMATION_TASKS[0],
        )
        service_checks = []
        watchdog_results = iter((False, True))

        def fake_ensure_services() -> list[object]:
            service_checks.append("checked")
            return []

        with mock.patch.object(engine, "ensure_services", side_effect=fake_ensure_services):
            with mock.patch.object(engine, "browser_observation", return_value=None):
                with mock.patch.object(engine, "runtime_watchdog_is_live", side_effect=watchdog_results):
                    with mock.patch.object(engine, "log_event"):
                        with mock.patch("time.sleep"):
                            self.assertTrue(engine.standby_until_ready(state))

        self.assertEqual(service_checks, ["checked", "checked"])

    def test_state_round_trip_uses_schema_v2(self) -> None:
        now = datetime.now(timezone.utc)
        state = engine.OvernightState(
            schema_version=2,
            run_id="round-trip",
            started_at=now.isoformat(),
            deadline_at=(now + timedelta(hours=10)).isoformat(),
            worktree="/tmp/pasi-worktree",
            branch="pasi/test",
            phase="engineering_os",
            current_task="Improve engineering verification",
            requested_task="Improve engineering verification",
            completed_tasks=4,
            automation_tasks_since_gate=0,
            automation_gates=1,
            provider_limit_pauses=1,
            recent_tasks=["one", "two"],
        )
        with tempfile.TemporaryDirectory() as directory:
            original_runtime = engine.RUNTIME_DIR
            original_state = engine.STATE_PATH
            try:
                engine.RUNTIME_DIR = Path(directory)
                engine.STATE_PATH = Path(directory) / "state.json"
                engine.save_state(state)
                restored = engine.load_state()
            finally:
                engine.RUNTIME_DIR = original_runtime
                engine.STATE_PATH = original_state
        self.assertIsNotNone(restored)
        assert restored is not None
        self.assertEqual(restored.schema_version, 2)
        self.assertEqual(restored.phase, "engineering_os")
        self.assertEqual(restored.provider_limit_pauses, 1)

    def test_verify_and_commit_records_gate_timing_and_supports_fast_gate(self) -> None:
        events: list[str] = []

        def fake_command(argv, cwd, timeout):
            if argv[:3] == ["git", "apply", "--check"]:
                return 0, ""
            if argv[:3] == ["git", "apply", "--whitespace=nowarn"]:
                return 0, ""
            if argv[:3] == ["git", "diff", "--check"]:
                return 0, ""
            if argv[:3] == ["git", "diff", "--name-only"]:
                return 0, "automation/chromium/pasi-chatgpt/content.js\n"
            if argv[:2] == [engine.legacy.sys.executable, "-m"]:
                return 0, "1 passed"
            if argv[:2] == ["node", "--check"]:
                return 0, ""
            if argv[:2] == ["node", "--test"]:
                return 0, "2 tests passed"
            if argv[:3] == ["git", "status", "--porcelain"]:
                return 0, " M automation/chromium/pasi-chatgpt/content.js"
            raise AssertionError(f"unexpected command: {argv!r}")

        with tempfile.TemporaryDirectory() as root:
            worktree = Path(root)
            changed = worktree / "automation" / "chromium" / "pasi-chatgpt"
            changed.mkdir(parents=True)
            (changed / "content.js").write_text("console.log('fixture');\n", encoding="utf-8")

            with mock.patch.dict("os.environ", {"PASI_LOCAL_GATE_MODE": "fast"}, clear=False):
                with mock.patch.object(engine, "command", side_effect=fake_command):
                    with mock.patch.object(engine, "validate_patch_paths"):
                        with mock.patch.object(
                            engine,
                            "log_event",
                            side_effect=lambda name, **_kwargs: events.append(name),
                        ):
                            with mock.patch.object(
                                engine.legacy,
                                "commit_and_push",
                                return_value="deadbeef",
                            ):
                                commit, output = engine.verify_and_commit(
                                    worktree,
                                    "test",
                                    "latency regression",
                                    "diff --git a/automation/chromium/pasi-chatgpt/content.js "
                                    "b/automation/chromium/pasi-chatgpt/content.js\n",
                                    False,
                                    push=False,
                                )

        self.assertEqual(commit, "deadbeef")
        self.assertIn("FAST LOCAL GATE PASSED", output)
        self.assertIn("verify_started", events)
        self.assertIn("verify_finished", events)


if __name__ == "__main__":
    unittest.main()
