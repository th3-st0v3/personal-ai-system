from __future__ import annotations

import os
import json
import sys
import tempfile
import unittest
from unittest import mock
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts import pasi_overnight_engine_v2 as engine
from scripts import pasi_hybrid_planner
from scripts import pasi_prompt_compiler as prompt_compiler


class TestPasiOvernightEngineV2(unittest.TestCase):

    def test_parse_response_allows_scheduler_owned_next_task(self) -> None:
        response = """PASI_RESULT_STATUS: complete
PASI_RESULT_SUMMARY: fixed the task
PASI_RESULT_REQUIREMENTS: complete
PASI_RESULT_LIMITATIONS: none
PASI_RESULT_RESEARCH: not_applicable
PASI_RESULT_UX: not_applicable
PASI_RESULT_BACKEND: verified
PASI_RESULT_EVIDENCE: deterministic verification passed
PASI_RESULT_REPOSITORY_PROGRESS: changed
PASI_RESULT_ALLOW_DELETE: false
PASI_RESULT_PATCH_BEGIN
diff --git a/example.txt b/example.txt
--- a/example.txt
+++ b/example.txt
@@ -1 +1 @@
-old
+new
PASI_RESULT_PATCH_END
"""
        status, summary, next_task, patch, allow_delete, values = engine.parse_response(response)
        self.assertEqual(status, "complete")
        self.assertEqual(summary, "fixed the task")
        self.assertEqual(next_task, "")
        self.assertTrue(patch)
        self.assertFalse(allow_delete)
        self.assertEqual(values["requirements"], "complete")


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

    def test_patch_boundary_rejects_ignored_and_protected_paths(self) -> None:
        import subprocess

        ignored_patch = """diff --git a/.runtime/secret.json b/.runtime/secret.json
new file mode 100644
--- /dev/null
+++ b/.runtime/secret.json
@@ -0,0 +1 @@
+blocked
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            worktree = Path(temp_dir)
            (worktree / ".runtime").mkdir()
            (worktree / ".gitignore").write_text(".runtime/\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=worktree, check=True)
            with self.assertRaisesRegex(ValueError, r"(Git-ignored|forbidden credential/secret)"):
                engine.validate_patch_paths(ignored_patch, False, worktree)

        protected = """diff --git a/scripts/check_all.sh b/scripts/check_all.sh
--- a/scripts/check_all.sh
+++ b/scripts/check_all.sh
@@ -1 +1 @@
-old
+new
"""
        with self.assertRaisesRegex(ValueError, "protected unattended"):
            engine.validate_patch_paths(protected, False, Path.cwd())

    def test_control_script_stays_inside_launcher_checkout(self) -> None:
        script = engine.control_script("pasi_chat_guard.py")
        self.assertEqual(script.parent.resolve(), engine.CONTROL_SCRIPTS_ROOT.resolve())
        with self.assertRaises(ValueError):
            engine.control_script("../pasi_chat_guard.py")

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

    def test_no_change_completion_requires_durable_task_evidence(self) -> None:
        values = {
            "repository_progress": "stopped",
            "requirements": "complete",
            "limitations": "none",
            "research": "not_applicable",
            "ux": "not_applicable",
            "backend": "verified",
            "evidence": "verified existing implementation",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with mock.patch.object(engine, "repository_worktree_is_clean", return_value=True):
                self.assertFalse(
                    engine.no_change_completion_is_satisfied(
                        root, "complete", "next", "", values, False
                    )
                )
                self.assertTrue(
                    engine.no_change_completion_is_satisfied(
                        root, "complete", "next", "", values, True
                    )
                )

    def test_failed_task_retry_cycle_retains_current_task(self) -> None:
        source = Path(engine.__file__).read_text(encoding="utf-8")
        failure_block = source.split("        if not finished:", 1)[1].split("\n\ndef finish_reason", 1)[0]
        self.assertIn('action="retain_current_task"', failure_block)
        self.assertIn("state.task_retry_cycle += 1", failure_block)
        self.assertNotIn("state.current_task = choose_next_task(state, "")", failure_block)

    def test_retry_cycle_state_round_trips(self) -> None:
        now = datetime.now(timezone.utc)
        state = engine.OvernightState(
            schema_version=2,
            run_id="retry-state",
            started_at=now.isoformat(),
            deadline_at=(now + timedelta(hours=8)).isoformat(),
            worktree=str(Path.cwd()),
            branch="pasi/retry-state",
            phase="automation",
            current_task=engine.AUTOMATION_TASKS[0],
            task_retry_cycle=2,
            last_failure_signature="abc123",
            same_failure_cycles=2,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            with mock.patch.object(engine, "STATE_PATH", state_path):
                engine.save_state(state)
                loaded = engine.load_state()
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.task_retry_cycle, 2)
        self.assertEqual(loaded.last_failure_signature, "abc123")
        self.assertEqual(loaded.same_failure_cycles, 2)

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

    def test_existing_branch_worktree_is_reused_instead_of_colliding(self) -> None:
        output = """worktree /tmp/other-pasi-worktree
HEAD deadbeef
branch refs/heads/pasi/test

worktree /tmp/unrelated
HEAD cafebabe
branch refs/heads/main

"""
        with tempfile.TemporaryDirectory() as temp_dir:
            requested = Path(temp_dir) / "requested"
            existing = Path("/tmp/other-pasi-worktree").resolve()
            responses = [
                (0, output),
                (0, ""),
                (0, ""),
                (0, "0 0"),
            ]
            with mock.patch.object(engine, "command", side_effect=responses) as run_command:
                found = engine.ensure_worktree(requested, "pasi/test", resume=False)
        self.assertEqual(found, existing)
        commands = [call.args[0] for call in run_command.call_args_list]
        self.assertNotIn(["git", "worktree", "add", "-B", "pasi/test", str(requested), "origin/main"], commands)

    def test_fresh_worktree_honors_configured_base_ref(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            worktree = Path(temp_dir) / "fresh"
            with mock.patch.dict(os.environ, {"PASI_OVERNIGHT_BASE_REF": "origin/pasi/consolidated"}, clear=False):
                with mock.patch.object(engine, "command", return_value=(0, "")) as run_command:
                    engine.ensure_worktree(worktree, "pasi/test", resume=False)
            command_args = run_command.call_args.args[0]
            self.assertEqual(
                command_args,
                ["git", "worktree", "add", "-B", "pasi/test", str(worktree), "origin/pasi/consolidated"],
            )

    def test_prompt_compiler_contains_only_current_task_and_result_contract(self) -> None:
        prompt = prompt_compiler.compile_task_prompt(
            "Fix the browser-to-Git patch seam and verify it end to end.",
            run_id="run-prompt-compiler",
            task_number=7,
            attempt=2,
            max_attempts=3,
            branch="pasi/test",
            worktree="/tmp/pasi-worktree",
            phase="engineering_os",
            recent_tasks=["previous verified task"],
            roadmap_tasks=["Roadmap task A", "Roadmap task B"],
        )
        self.assertEqual(
            prompt.split("RESULT:", 1)[0],
            "CURRENT TASK:\nFix the browser-to-Git patch seam and verify it end to end.\n\nWork on this task until its acceptance criteria are met. Inspect the relevant code, make the smallest correct change, verify it, and repair any verification failure. Do not start another task.\n\n",
        )
        self.assertNotIn("run-prompt-compiler", prompt)
        self.assertNotIn("Task number", prompt)
        self.assertNotIn("Attempt", prompt)
        self.assertNotIn("Roadmap task A", prompt)
        self.assertNotIn("Roadmap task B", prompt)
        self.assertNotIn("previous verified task", prompt)
        self.assertNotIn("DO NOT STOP UNTIL YOU ARE FINISHED", prompt)
        self.assertNotIn("PASI_RESULT_NEXT_TASK:", prompt)
        self.assertIn("PASI_RESULT_STATUS:", prompt)
        self.assertIn("Work on this task until its acceptance criteria are met.", prompt)
        self.assertIn("PASI_RESULT_PATCH_BEGIN", prompt)

    def test_prompt_compiler_includes_bounded_failure_only_on_retry(self) -> None:
        prompt = prompt_compiler.compile_task_prompt(
            "Fix the browser-to-Git patch seam.",
            run_id="run-retry",
            task_number=2,
            attempt=2,
            max_attempts=3,
            branch="pasi/test",
            worktree="/tmp/pasi-worktree",
            phase="automation",
            previous_failure="git apply received an empty stdin payload",
        )
        self.assertIn("CURRENT TASK:\nFix the browser-to-Git patch seam.", prompt)
        self.assertIn("PREVIOUS FAILURE EVIDENCE:\ngit apply received an empty stdin payload", prompt)
        self.assertNotIn("ROADMAP", prompt)
        self.assertNotIn("RECOVERY RETRY MODE", prompt)
        self.assertNotIn("NEXT_TASK", prompt)


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

    def test_scheduler_ignores_model_task_suggestion(self) -> None:
        now = datetime.now(timezone.utc)
        state = engine.OvernightState(
            schema_version=2,
            run_id="forward-progress-test",
            started_at=now.isoformat(),
            deadline_at=(now + timedelta(hours=8)).isoformat(),
            worktree=str(Path.cwd()),
            branch="test",
            phase="automation",
            current_task="current task",
        )
        selected = pasi_hybrid_planner.TaskSpec(
            id="next.task",
            title="Next task",
            objective="Execute the planner-selected task.",
            acceptance_criteria=("The task is verified.",),
            verification=("Run the targeted test.",),
            phase="automation",
        )
        with mock.patch.object(
            engine,
            "select_planner_task",
            return_value=pasi_hybrid_planner.PlannerDecision(
                selected=selected,
                eligible_ids=("next.task",),
                mode="deterministic",
                reason="only eligible task",
            ),
        ):
            result = engine.choose_next_task(state, "model-invented task")
        self.assertEqual(result, selected.execution_text())
        self.assertEqual(state.current_task_id, "next.task")

    def test_attempt_budget_starts_next_retry_cycle_on_same_task(self) -> None:
        now = datetime.now(timezone.utc)
        state = engine.OvernightState(
            schema_version=2,
            run_id="attempt-budget-progress",
            started_at=now.isoformat(),
            deadline_at=(now + timedelta(hours=1)).isoformat(),
            worktree=str(Path.cwd()),
            branch="test",
            phase="automation",
            current_task=engine.AUTOMATION_TASKS[0],
        )
        attempts: list[tuple[str, int]] = []
        failure_values = {
            "requirements": "complete",
            "limitations": "handled",
            "research": "not_applicable",
            "ux": "not_applicable",
            "backend": "verified",
            "evidence": "attempt failed before a usable patch was produced",
            "repository_progress": "stopped",
        }
        success_values = dict(failure_values, evidence="verified patch for next task", repository_progress="changed")
        parsed = iter(
            [
                ("needs_revision", "first failure", "", "", False, failure_values),
                ("needs_revision", "second failure", "", "", False, failure_values),
                ("needs_revision", "third failure", "", "", False, failure_values),
                ("complete", "next task completed", engine.AUTOMATION_TASKS[2], "diff --git a/example.txt b/example.txt\n", False, success_values),
            ]
        )

        def invoke(task, _state, _failure):
            attempts.append((task, _state.current_attempt))
            return 0, "fixture response"

        def verify(*_args, **_kwargs):
            engine.STOP = True
            return "deadbeef", "verified"

        original_stop = engine.STOP
        try:
            engine.STOP = False
            with mock.patch.object(engine, "runtime_watchdog_is_live", return_value=True):
                with mock.patch.object(
                    engine,
                    "select_planner_task",
                    return_value=pasi_hybrid_planner.PlannerDecision(
                        selected=pasi_hybrid_planner.TaskSpec(
                            id="automation.after-retry",
                            title="After retry",
                            objective="Proceed to the next verified task.",
                            acceptance_criteria=("The task is verified.",),
                            verification=("Run the targeted test.",),
                            phase="automation",
                        ),
                        eligible_ids=("automation.after-retry",),
                        mode="deterministic",
                        reason="planner selected the next eligible task",
                    ),
                ):
                    with mock.patch.object(engine, "completed_task_keys", return_value=set()):
                        with mock.patch.object(engine, "invoke_chat", side_effect=invoke):
                            with mock.patch.object(engine, "parse_response", side_effect=lambda _response: next(parsed)):
                                with mock.patch.object(engine, "completion_contract", side_effect=lambda status, _values: status == "complete"):
                                    with mock.patch.object(engine, "verify_and_commit", side_effect=verify):
                                        with mock.patch.object(engine, "record_task_ledger"):
                                            with mock.patch.object(engine, "save_state"):
                                                with mock.patch.object(engine, "log_event"):
                                                    engine.run(state, push=False)
