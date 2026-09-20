from __future__ import annotations

import tempfile
import unittest
import os
from unittest import mock
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts import pasi_overnight_engine_v2 as engine


class TestPasiOvernightEngineV2(unittest.TestCase):
    def test_git_resolved_path_validator_rejects_protected_resolved_paths(self) -> None:
        for record in (
            ".githooks/pre-commit",
            "hooks/pre-push",
            ".github/workflows/test.yml",
            "scripts/check_all.sh",
        ):
            summary = "0\t0\t" + record + "\x00"
            with self.assertRaisesRegex(RuntimeError, "protected unattended path"):
                engine.validate_git_resolved_paths(Path.cwd(), summary)

    def test_git_resolved_path_validator_accepts_rename_records(self) -> None:
        engine.validate_git_resolved_paths(
            Path.cwd(),
            "0\t0\told.txt\x00new.txt\x00",
        )

    def test_git_resolved_path_validator_accepts_normal_paths(self) -> None:
        engine.validate_git_resolved_paths(
            Path.cwd(),
            "1\t0\tREADME.md\x00",
        )

    def test_unattended_patch_rejects_hooks_and_validator_paths(self) -> None:
        safe_patch = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-old
+new
"""
        for path_value in (".githooks/pre-commit", "hooks/pre-push", ".github/workflows/test.yml", "scripts/check_all.sh"):
            patch = safe_patch.replace("app.py", path_value)
            with self.assertRaises(ValueError):
                engine.validate_patch_paths(patch, allow_delete=False)

    def test_parse_response_requires_all_markers_exactly_once_and_preserves_patch_lines(self) -> None:
        response = """PASI_RESULT_STATUS: complete
PASI_RESULT_SUMMARY: parser seam
PASI_RESULT_NEXT_TASK: next
PASI_RESULT_REQUIREMENTS: complete
PASI_RESULT_LIMITATIONS: handled
PASI_RESULT_RESEARCH: not_applicable
PASI_RESULT_UX: verified
PASI_RESULT_BACKEND: verified
PASI_RESULT_EVIDENCE: multiline patch preserved
PASI_RESULT_REPOSITORY_PROGRESS: changed
PASI_RESULT_ALLOW_DELETE: false
PASI_RESULT_PATCH_BEGIN
diff --git a/example.txt b/example.txt
--- a/example.txt
+++ b/example.txt
@@ -1 +1 @@
-old
+new
PASI_RESULT_PATCH_END"""
        status, summary, next_task, patch, allow_delete, values = engine.parse_response(response)
        self.assertEqual(status, "complete")
        self.assertEqual(summary, "parser seam")
        self.assertEqual(next_task, "next")
        self.assertFalse(allow_delete)
        self.assertIn("@@ -1 +1 @@\n-old\n+new", patch)
        self.assertEqual(values["repository_progress"], "changed")

    def test_parse_response_rejects_missing_marker(self) -> None:
        response = "PASI_RESULT_STATUS: complete\nPASI_RESULT_PATCH_BEGIN\nPASI_RESULT_PATCH_END"
        with self.assertRaisesRegex(ValueError, "each marker exactly once"):
            engine.parse_response(response)

    def test_parse_response_honors_optional_automation_continue_signal(self) -> None:
        response = """PASI_RESULT_STATUS: complete
PASI_RESULT_SUMMARY: automation capability still required
PASI_RESULT_NEXT_TASK: build recovery telemetry
PASI_RESULT_REQUIREMENTS: complete
PASI_RESULT_LIMITATIONS: none
PASI_RESULT_RESEARCH: performed
PASI_RESULT_UX: verified
PASI_RESULT_BACKEND: verified
PASI_RESULT_EVIDENCE: verified
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
PASI_RESULT_PATCH_END"""
        _, _, _, _, _, values = engine.parse_response(response)
        self.assertEqual(values["automation_continue"], "true")

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

    def test_offline_remote_fetch_is_deferred_not_fatal(self) -> None:
        source = Path(engine.__file__).read_text(encoding="utf-8")
        self.assertIn('log_event("git_fetch_deferred"', source)
        self.assertIn('if code != 0:', source)
        self.assertIn('saved = load_state() if args.resume else None', source)

    def test_fresh_worktree_starts_from_launcher_head_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            worktree = Path(temp_dir) / "fresh"
            with mock.patch.dict(os.environ, {"PASI_OVERNIGHT_BASE_REF": ""}, clear=False):
                with mock.patch.object(engine, "command", return_value=(0, "")) as run_command:
                    engine.ensure_worktree(worktree, "pasi/test", resume=False)
            command_args = run_command.call_args.args[0]
            self.assertEqual(command_args[-1], "HEAD")

    def test_task_key_canonicalizes_whitespace_for_commit_recovery(self) -> None:
        first = engine.task_key("one\n two")
        second = engine.task_key("one two")
        self.assertEqual(first, second)
        self.assertEqual(first, engine.task_key("  one   two  "))

    def test_controller_observation_requires_current_release_version(self) -> None:
        now = datetime.now(timezone.utc)
        timestamp = now.isoformat()
        current = {
            "kind": "chatgpt_state",
            "controller_version": "2.4.11",
            "captured_at": timestamp,
            "native_controller": True,
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

    def test_controller_observation_rejects_legacy_controller_even_with_current_version(self) -> None:
        now = datetime.now(timezone.utc)
        legacy_observation = {
            "kind": "chatgpt_state",
            "controller_version": "2.4.11",
            "captured_at": now.isoformat(),
            "native_controller": False,
        }
        native_missing = dict(legacy_observation)
        native_missing.pop("native_controller")
        with mock.patch(
            "scripts.pasi_overnight_engine_v2.expected_controller_version",
            return_value="2.4.11",
        ):
            with mock.patch.object(engine, "browser_observation", side_effect=[legacy_observation, native_missing]):
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

    def test_valid_next_task_is_honored_and_completed_ledger_is_skipped(self) -> None:
        now = datetime.now(timezone.utc)
        state = engine.OvernightState(
            schema_version=2,
            run_id="ledger-test",
            started_at=now.isoformat(),
            deadline_at=(now + timedelta(hours=8)).isoformat(),
            worktree=str(Path.cwd()),
            branch="test",
            phase="automation",
            current_task=engine.AUTOMATION_TASKS[0],
            recent_tasks=[],
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger_path = Path(temp_dir) / "task-ledger.json"
            with mock.patch.object(engine, "TASK_LEDGER_PATH", ledger_path):
                engine.record_task_ledger(engine.AUTOMATION_TASKS[1], "completed", commit="abc123", evidence="verified")
                self.assertEqual(
                    engine.choose_next_task(state, engine.AUTOMATION_TASKS[1]),
                    engine.AUTOMATION_TASKS[2],
                )
                candidate = "Implement a concrete seam diagnostic for queued ChatGPT operations."
                self.assertEqual(engine.choose_next_task(state, candidate), candidate)

    def test_commit_message_contains_task_identity_for_restart_reconciliation(self) -> None:
        self.assertIn("commit_tag = f\"task-{task_key(task)[:12]}\"", (Path(engine.__file__).read_text(encoding="utf-8")))

    def test_task_ledger_records_completion_before_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger_path = Path(temp_dir) / "task-ledger.json"
            with mock.patch.object(engine, "TASK_LEDGER_PATH", ledger_path):
                engine.record_task_ledger(
                    engine.AUTOMATION_TASKS[0],
                    "completed",
                    commit="abc123",
                    evidence="verified",
                    phase="automation",
                )
                self.assertIn(
                    engine.task_key(engine.AUTOMATION_TASKS[0]),
                    engine.completed_task_keys(),
                )

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

    def test_choose_next_task_honors_unique_concrete_suggestion(self) -> None:
        now = datetime.now(timezone.utc)
        state = engine.OvernightState(
            schema_version=2,
            run_id="dynamic-next-task-test",
            started_at=now.isoformat(),
            deadline_at=(now + timedelta(hours=8)).isoformat(),
            worktree=str(Path.cwd()),
            branch="test",
            phase="automation",
            current_task=engine.AUTOMATION_TASKS[0],
            recent_tasks=[],
        )
        suggestion = "Implement a concrete seam diagnostic for queued ChatGPT operations."
        self.assertEqual(engine.choose_next_task(state, suggestion), suggestion)

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

    def test_legacy_v1_engine_is_retired(self) -> None:
        self.assertFalse((engine.REPO_ROOT / "scripts" / "pasi_overnight_engine.py").exists())

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


    def test_run_retries_malformed_response_instead_of_terminating(self) -> None:
        now = datetime.now(timezone.utc)
        state = engine.OvernightState(
            schema_version=2,
            run_id="contract-retry",
            started_at=now.isoformat(),
            deadline_at=(now + timedelta(minutes=5)).isoformat(),
            worktree=str(Path.cwd()),
            branch="test",
            phase="automation",
            current_task="Implement response retry seam",
        )
        valid = """PASI_RESULT_STATUS: complete
PASI_RESULT_SUMMARY: recovered after malformed response
PASI_RESULT_NEXT_TASK: advance
PASI_RESULT_REQUIREMENTS: complete
PASI_RESULT_LIMITATIONS: none
PASI_RESULT_RESEARCH: not_applicable
PASI_RESULT_UX: not_applicable
PASI_RESULT_BACKEND: verified
PASI_RESULT_EVIDENCE: second attempt parsed and verified
PASI_RESULT_REPOSITORY_PROGRESS: changed
PASI_RESULT_ALLOW_DELETE: false
PASI_RESULT_PATCH_BEGIN
diff --git a/example.txt b/example.txt
--- a/example.txt
+++ b/example.txt
@@ -1 +1 @@
-old
+new
PASI_RESULT_PATCH_END"""
        responses = iter([
            "PASI_RESULT_STATUS: complete\nPASI_RESULT_PATCH_BEGIN\nPASI_RESULT_PATCH_END",
            valid,
        ])
        calls = []
        original_stop = engine.STOP
        try:
            engine.STOP = False

            def fake_invoke(*_args, **_kwargs):
                calls.append("invoke")
                return 0, next(responses)

            def fake_verify(*_args, **_kwargs):
                engine.STOP = True
                return "abc123", "verification passed"

            with mock.patch.object(engine, "reconcile_committed_task", return_value=False):
                with mock.patch.object(engine, "runtime_watchdog_is_live", return_value=True):
                    with mock.patch.object(engine, "invoke_chat", side_effect=fake_invoke):
                        with mock.patch.object(engine, "verify_and_commit", side_effect=fake_verify):
                            with mock.patch.object(engine, "record_task_ledger"):
                                with mock.patch.object(engine, "save_state"):
                                    with mock.patch.object(engine, "log_event") as log_event:
                                        engine.run(state, push=False)
            self.assertEqual(calls, ["invoke", "invoke"])
            self.assertTrue(any(call.args and call.args[0] == "response_contract_failed" for call in log_event.call_args_list))
            self.assertEqual(state.completed_tasks, 1)
        finally:
            engine.STOP = original_stop

    def test_response_contract_is_shared_with_provider_router(self) -> None:
        contract_source = (Path(engine.REPO_ROOT) / "scripts" / "pasi_response_contract.py").read_text(encoding="utf-8")
        router_source = (Path(engine.REPO_ROOT) / "scripts" / "pasi_provider_router.py").read_text(encoding="utf-8")
        self.assertIn("PASI_RESULT_REPOSITORY_PROGRESS", contract_source)
        self.assertIn("from scripts.pasi_response_contract import CONTRACT", router_source)
        self.assertIn('f"\n\n{CONTRACT}\\n"', router_source)


if __name__ == "__main__":
    unittest.main()
