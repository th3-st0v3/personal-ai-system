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
from scripts.pasi_overnight_engine_v2 import (
    PROTECTED_UNATTENDED_PATHS,
    completion_effort_floor_reason,
    consume_runner_control,
    write_handoff_summary,
)
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


    def test_response_contract_parse_failure_retries_current_task(self) -> None:
        now = datetime.now(timezone.utc)
        state = engine.OvernightState(
            schema_version=2,
            run_id="contract-retry-test",
            started_at=now.isoformat(),
            deadline_at=(now + timedelta(hours=1)).isoformat(),
            worktree=str(Path.cwd()),
            branch="test",
            phase="automation",
            current_task=engine.AUTOMATION_TASKS[0],
        )
        attempts: list[int] = []
        failures: list[str] = []
        success_values = {
            "requirements": "complete",
            "limitations": "handled",
            "research": "not_applicable",
            "ux": "verified",
            "backend": "verified",
            "evidence": "contract retry evidence is verified and complete",
            "repository_progress": "changed",
        }
        parser_results = iter([
            ValueError("missing summary/evidence/allow_delete"),
            ("complete", "completed after contract repair", "", "diff --git a/example.txt b/example.txt\n", False, success_values),
        ])

        def invoke(_task, state_arg, failure):
            attempts.append(state_arg.current_attempt)
            failures.append(failure)
            return 0, "fixture response"

        def parse(_response):
            value = next(parser_results)
            if isinstance(value, Exception):
                raise value
            return value

        def verify(*_args, **_kwargs):
            engine.STOP = True
            return "deadbeef", "verified"

        original_stop = engine.STOP
        try:
            engine.STOP = False
            with mock.patch.object(engine, "runtime_watchdog_is_live", return_value=True):
                with mock.patch.object(engine, "invoke_chat", side_effect=invoke):
                    with mock.patch.object(engine, "parse_response", side_effect=parse):
                        with mock.patch.object(engine, "completion_contract", return_value=True):
                            with mock.patch.object(engine, "verify_and_commit", side_effect=verify):
                                with mock.patch.object(engine, "record_task_ledger"):
                                    with mock.patch.object(engine, "save_state"):
                                        with mock.patch.object(engine, "log_event"):
                                            engine.run(state, push=False)
        finally:
            engine.STOP = original_stop

        self.assertEqual(attempts, [1, 2])
        self.assertEqual(failures[0], "")
        self.assertIn("response_contract:", failures[1])
        self.assertEqual(state.completed_tasks, 1)

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

    def test_m2_fast_start_skips_only_no_push_startup_fetch(self) -> None:
        original = os.environ.pop("PASI_M2_FAST_START", None)
        try:
            with mock.patch.dict(os.environ, {"PASI_M2_FAST_START": "1"}, clear=False):
                self.assertTrue(engine.should_skip_startup_fetch(no_push=True))
                self.assertFalse(engine.should_skip_startup_fetch(no_push=False))
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("PASI_M2_FAST_START", None)
                self.assertFalse(engine.should_skip_startup_fetch(no_push=True))
        finally:
            if original is not None:
                os.environ["PASI_M2_FAST_START"] = original

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
            "CURRENT TASK:\nFix the browser-to-Git patch seam and verify it end to end.\n\nComplete the task as an implementation task when implementation is required; tracked-file changes are allowed unless the task explicitly scopes them out. Keep working until the stated acceptance criteria are met. Run every relevant test, type check, lint, or other deterministic verification check needed for the task; repair failures and do not report completion while required checks are failing. Keep the response focused on the task and actionable results; do not expose internal routing, planner, browser-controller, capability-gateway, or orchestration details.\n\n",
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
        self.assertIn("Keep working until the stated acceptance criteria are met.", prompt)
        self.assertIn("do not report completion while required checks are failing", prompt)
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
        success_values = dict(failure_values, evidence="verified patch for the next task and deterministic acceptance checks", repository_progress="changed")
        parsed = iter(
            [
                ("needs_revision", "first failure", "", "", False, failure_values),
                ("needs_revision", "second failure", "", "", False, failure_values),
                ("needs_revision", "third failure", "", "", False, failure_values),
                ("complete", "completed the next verified task successfully", engine.AUTOMATION_TASKS[2], "diff --git a/example.txt b/example.txt\n", False, success_values),
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
        finally:
            engine.STOP = original_stop

        self.assertEqual(
            attempts,
            [
                (engine.AUTOMATION_TASKS[0], 1),
                (engine.AUTOMATION_TASKS[0], 2),
                (engine.AUTOMATION_TASKS[0], 3),
                (engine.AUTOMATION_TASKS[0], 1),
            ],
        )
        self.assertEqual(state.failed_tasks, 1)
        self.assertEqual(state.completed_tasks, 1)
        self.assertEqual(
            state.current_task,
            "TITLE: After retry\nOBJECTIVE: Proceed to the next verified task.\n"
            "ACCEPTANCE CRITERIA:\n- The task is verified.\n"
            "VERIFICATION:\n- Run the targeted test.",
        )
        self.assertEqual(state.current_task_id, "automation.after-retry")
        self.assertEqual(state.task_retry_cycle, 0)

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
        selected = pasi_hybrid_planner.TaskSpec(
            id="automation.repair",
            title="Automation repair",
            objective="Repair the failed task using new evidence.",
            acceptance_criteria=("The repair is verified.",),
            verification=("Run the targeted test.",),
            phase="automation",
        )
        with mock.patch.object(
            engine,
            "select_planner_task",
            return_value=pasi_hybrid_planner.PlannerDecision(
                selected=selected,
                eligible_ids=("automation.repair",),
                mode="deterministic",
                reason="planner selected the next eligible task",
            ),
        ):
            result = engine.choose_next_task(state, "")
        self.assertEqual(result, selected.execution_text())

    def test_provider_conditions_are_distinct_from_chat_completion_failures(self) -> None:
        self.assertEqual(engine.provider_condition(90, "CHAT_USAGE_LIMITED: provider limit"), "provider_usage_limit")
        self.assertEqual(engine.provider_condition(91, "CHAT_AUTH_REQUIRED: login"), "auth_required")
        self.assertEqual(engine.provider_condition(92, "CHAT_GUARD_TIMEOUT: timeout"), "runtime_guard")
        self.assertIsNone(engine.provider_condition(1, "CHAT_EXHAUSTED: conversation context"))

    def test_provider_limit_recovery_does_not_consume_task_attempt_budget(self) -> None:
        now = datetime.now(timezone.utc)
        state = engine.OvernightState(
            schema_version=2,
            run_id="provider-limit-attempt-budget",
            started_at=now.isoformat(),
            deadline_at=(now + timedelta(hours=1)).isoformat(),
            worktree=str(Path.cwd()),
            branch="test",
            phase="automation",
            current_task=engine.AUTOMATION_TASKS[0],
        )
        attempts: list[int] = []
        provider_failures = 4
        responses = iter(
            [(90, "CHAT_USAGE_LIMITED: provider limit")] * provider_failures
            + [(0, "fixture response")]
        )
        parsed = (
            "complete",
            "provider recovery test passed",
            engine.AUTOMATION_TASKS[1],
            "diff --git a/example.txt b/example.txt\n",
            False,
            {
                "evidence": "provider recovery preserved the same task attempt",
                "automation_continue": "false",
            },
        )

        def invoke(_task, local_state, _failure):
            attempts.append(local_state.current_attempt)
            return next(responses)

        def verify(*_args, **_kwargs):
            engine.STOP = True
            return "provider-recovery-commit", "verified"

        original_stop = engine.STOP
        try:
            engine.STOP = False
            with mock.patch.object(engine, "runtime_watchdog_is_live", return_value=True):
                with mock.patch.object(
                    engine,
                    "select_planner_task",
                    return_value=pasi_hybrid_planner.PlannerDecision(
                        selected=pasi_hybrid_planner.TaskSpec(
                            id="automation.after-provider-recovery",
                            title="After provider recovery",
                            objective="Proceed to the next verified task.",
                            acceptance_criteria=("The task is verified.",),
                            verification=("Run the targeted test.",),
                            phase="automation",
                        ),
                        eligible_ids=("automation.after-provider-recovery",),
                        mode="deterministic",
                        reason="planner selected the next eligible task",
                    ),
                ):
                    with mock.patch.object(engine, "invoke_chat", side_effect=invoke):
                        with mock.patch.object(engine, "parse_response", return_value=parsed):
                            with mock.patch.object(engine, "completion_contract", return_value=True):
                                with mock.patch.object(engine, "verify_and_commit", side_effect=verify):
                                    with mock.patch.object(engine, "record_task_ledger"):
                                        with mock.patch.object(engine, "save_state"):
                                            with mock.patch.object(engine, "sleep_until_retry", return_value=True):
                                                with mock.patch.object(engine, "log_event"):
                                                    engine.run(state, push=False)
        finally:
            engine.STOP = original_stop

        self.assertEqual(attempts, [1, 1, 1, 1, 1])
        self.assertEqual(state.completed_tasks, 1)
        self.assertEqual(state.failed_tasks, 0)

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

    def test_choose_next_task_does_not_consume_model_next_task(self) -> None:
        now = datetime.now(timezone.utc)
        state = engine.OvernightState(
            schema_version=2,
            run_id="non-roadmap-test",
            started_at=now.isoformat(),
            deadline_at=(now + timedelta(hours=8)).isoformat(),
            worktree=str(Path.cwd()),
            branch="test",
            phase="automation",
            current_task="operator task",
            recent_tasks=[],
        )
        with mock.patch.object(
            engine,
            "select_planner_task",
            return_value=pasi_hybrid_planner.PlannerDecision(
                selected=pasi_hybrid_planner.TaskSpec(
                    id="next.task",
                    title="Next task",
                    objective="Do the next thing",
                    acceptance_criteria=("It is verified.",),
                    verification=("Run the test.",),
                    phase="automation",
                ),
                eligible_ids=("next.task",),
                mode="deterministic",
                reason="only eligible task",
            ),
        ):
            selected = engine.choose_next_task(
                state,
                "model-selected task must be ignored",
            )
        self.assertEqual(selected, "TITLE: Next task\nOBJECTIVE: Do the next thing\nACCEPTANCE CRITERIA:\n- It is verified.\nVERIFICATION:\n- Run the test.")
        self.assertEqual(state.current_task_id, "next.task")

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

    def test_command_feeds_unified_patch_to_git_apply_stdin(self) -> None:
        import subprocess

        with tempfile.TemporaryDirectory() as temp_dir:
            worktree = Path(temp_dir)
            subprocess.run(
                ["git", "init", "-q"],
                cwd=worktree,
                check=True,
                capture_output=True,
                text=True,
            )
            (worktree / "example.txt").write_text("old\n", encoding="utf-8")
            subprocess.run(["git", "add", "example.txt"], cwd=worktree, check=True)
            subprocess.run(
                [
                    "git",
                    "-c", "user.email=test@example.com",
                    "-c", "user.name=PASI Test",
                    "commit", "-q", "-m", "baseline",
                ],
                cwd=worktree,
                check=True,
                capture_output=True,
                text=True,
            )
            patch = """diff --git a/example.txt b/example.txt
--- a/example.txt
+++ b/example.txt
@@ -1 +1,2 @@
 old
+new
"""
            code, output = engine.command(
                ["git", "apply", "--check", "--whitespace=nowarn"],
                worktree,
                30.0,
                input_text=patch,
            )
            self.assertEqual(code, 0, output)
            code, output = engine.command(
                ["git", "apply", "--whitespace=nowarn"],
                worktree,
                30.0,
                input_text=patch,
            )
            self.assertEqual(code, 0, output)
            self.assertEqual((worktree / "example.txt").read_text(encoding="utf-8"), "old\nnew\n")

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

        def fake_command(argv, cwd, timeout, **kwargs):
            if argv[:3] == ["git", "apply", "--check"]:
                return 0, ""
            if argv[:3] == ["git", "apply", "--whitespace=nowarn"]:
                return 0, ""
            if argv[:3] == ["git", "diff", "--check"]:
                return 0, ""
            if argv[:3] == ["git", "diff", "--name-only"]:
                return 0, "automation/chromium/pasi-chatgpt/content.js\n"
            if argv[:2] == [sys.executable, "-m"]:
                return 0, "1 passed"
            if argv[:2] == ["node", "--check"]:
                return 0, ""
            if argv[:2] == ["node", "--test"]:
                return 0, "2 tests passed"
            if argv[:3] == ["git", "status", "--porcelain"]:
                if "--untracked-files=all" in argv:
                    return 0, ""
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
                                engine,
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


    def test_operation_id_extraction_and_queue_size_telemetry(self) -> None:
        self.assertEqual(
            engine.extract_operation_id("Prompt operation: op-1234-abcd"),
            "op-1234-abcd",
        )
        self.assertEqual(
            engine.extract_operation_id("Resuming persisted ChatGPT operation: op-9"),
            "op-9",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            queue_path = Path(temp_dir) / "queue.json"
            queue_path.write_text("{}\n", encoding="utf-8")
            with mock.patch.object(engine, "BRIDGE_QUEUE_PATH", queue_path):
                self.assertEqual(engine.queue_file_bytes(), 3)

    def test_native_controller_version_comes_from_native_source(self) -> None:
        self.assertEqual(
            engine.CONTROLLER_SOURCE_PATH,
            engine.REPO_ROOT / "automation" / "chromium" / "pasi-chatgpt" / "content.js",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "content.js"
            source.write_text("const CONTROLLER_VERSION = '2.4.11';\n", encoding="utf-8")
            self.assertEqual(engine.expected_controller_version(source), "2.4.11")

    def test_engine_does_not_start_retired_controller_distribution_service(self) -> None:
        import inspect

        source = inspect.getsource(engine.ensure_services)
        self.assertNotIn("8766", source)
        self.assertNotIn("pasi_controller_server.py", source)


    def test_168h_runtime_control_paths_are_protected(self) -> None:
        from scripts import pasi_overnight_hardening as hardening

        expected = {
            "scripts/check_all.sh",
            "scripts/check_offline.sh",
            "scripts/pasi_overnight_hardening.py",
            "scripts/pasi_overnight_engine_v2.py",
            "scripts/pasi_extended_runtime_entrypoint.py",
            "scripts/start_pasi_168h.sh",
            "scripts/pasi_168h_supervisor.sh",
            "scripts/pasi_timeout_policy.py",
            "scripts/pasi_chat_guard.py",
            "scripts/pasi_provider_router.py",
            "scripts/pasi_setup.py",
            "scripts/pasi_promote.py",
            "automation/chromium/pasi-chatgpt/manifest.json",
            "automation/chromium/pasi-chatgpt/timeout-policy.json",
        }
        self.assertTrue(expected.issubset(hardening.PROTECTED_UNATTENDED_PATHS))
        self.assertTrue(expected.issubset(PROTECTED_UNATTENDED_PATHS))
        for path in sorted(expected):
            patch = (
                f"diff --git a/{path} b/{path}\n"
                f"--- a/{path}\n"
                f"+++ b/{path}\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+new\n"
            )
            with self.assertRaisesRegex(ValueError, "protected unattended"):
                engine.validate_patch_paths(patch, False, Path.cwd())

    def test_completion_effort_floor_rejects_low_content_new_task(self) -> None:
        values = {"evidence": "verified"}
        self.assertIn("summary is too short", completion_effort_floor_reason("complete", "done", values, False))
        self.assertIn(
            "evidence is too short",
            completion_effort_floor_reason(
                "complete", "Implemented and verified the requested change.", values, False
            ),
        )

    def test_completion_effort_floor_allows_existing_no_change_task(self) -> None:
        self.assertEqual(completion_effort_floor_reason("complete", "done", {"evidence": ""}, True), "")

    def test_completion_effort_floor_only_applies_to_complete_status(self) -> None:
        self.assertEqual(completion_effort_floor_reason("needs_revision", "done", {"evidence": ""}, False), "")

    def test_handoff_summary_is_durable_and_bounded(self) -> None:
        now = datetime.now(timezone.utc)
        state = engine.OvernightState(
            schema_version=2, run_id="handoff-test", started_at=now.isoformat(),
            deadline_at=(now + timedelta(hours=168)).isoformat(), worktree="/tmp/pasi-worktree",
            branch="pasi/handoff-test", phase="automation", current_task="current task",
            requested_task="requested task", completed_tasks=4, failed_tasks=2, current_attempt=3,
            task_retry_cycle=2, same_failure_cycles=2, last_failure_signature="failure-signature",
            last_provider="chatgpt_browser", provider_limit_pauses=1,
            fallback_router_disabled_until="2026-09-22T00:00:00+00:00", last_result="x" * 8000,
            next_task="next task", recent_tasks=["one", "two", "three"],
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "handoff.json"
            with mock.patch.object(engine, "HANDOFF_PATH", path), mock.patch.object(engine, "RUNTIME_DIR", Path(temp_dir)):
                write_handoff_summary(state, reason="deadline_reached")
                payload = __import__("json").loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["run_id"], "handoff-test")
        self.assertEqual(payload["stop_reason"], "deadline_reached")
        self.assertEqual(payload["completed_tasks"], 4)
        self.assertEqual(payload["failed_tasks"], 2)
        self.assertEqual(len(payload["last_result"]), 6000)
        self.assertEqual(payload["recent_tasks"], ["one", "two", "three"])

    def test_finish_state_writes_handoff_summary_after_state(self) -> None:
        now = datetime.now(timezone.utc)
        state = engine.OvernightState(
            schema_version=2, run_id="finish-handoff-test", started_at=now.isoformat(),
            deadline_at=(now + timedelta(hours=168)).isoformat(), worktree="/tmp/pasi-worktree",
            branch="pasi/finish-handoff-test", phase="automation", current_task="current task",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"; handoff_path = Path(temp_dir) / "handoff.json"
            with mock.patch.object(engine, "STATE_PATH", state_path), mock.patch.object(engine, "HANDOFF_PATH", handoff_path), mock.patch.object(engine, "RUNTIME_DIR", Path(temp_dir)), mock.patch.object(engine, "log_event"):
                engine.finish_state(state, "stopped")
                self.assertTrue(state_path.is_file()); self.assertTrue(handoff_path.is_file())
                payload = __import__("json").loads(handoff_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["stop_reason"], "stopped")
        self.assertEqual(payload["run_id"], "finish-handoff-test")

    def test_consume_runner_control_accepts_matching_current_task(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            control = root / "control.json"
            state = engine.OvernightState(
                schema_version=2,
                run_id="control-test",
                started_at=datetime.now(timezone.utc).isoformat(),
                deadline_at=(datetime.now(timezone.utc) + timedelta(hours=168)).isoformat(),
                worktree=str(root),
                branch="pasi/control-test",
                phase="engineering_os",
                current_task="task",
                current_task_id="task.id",
                task_retry_cycle=4,
                current_attempt=3,
                last_failure_signature="failure",
                same_failure_cycles=2,
                last_result="failed",
            )
            control.write_text(json.dumps({
                "schema_version": 1,
                "action": "retry_current",
                "task_id": "task.id",
            }), encoding="utf-8")
            with (
                mock.patch.object(engine, "RUNNER_CONTROL_PATH", control),
                mock.patch.object(engine, "RUNTIME_DIR", root),
                mock.patch.object(engine, "STATE_PATH", root / "state.json"),
                mock.patch.object(engine, "log_event"),
            ):
                assert consume_runner_control(state) is True
            self.assertEqual(state.task_retry_cycle, 0)
            self.assertEqual(state.current_attempt, 0)
            self.assertEqual(state.last_failure_signature, "")
            self.assertFalse(control.exists())

    def test_consume_runner_control_rejects_wrong_task_without_resetting_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            control = root / "control.json"
            state = engine.OvernightState(
                schema_version=2,
                run_id="control-test",
                started_at=datetime.now(timezone.utc).isoformat(),
                deadline_at=(datetime.now(timezone.utc) + timedelta(hours=168)).isoformat(),
                worktree=str(root),
                branch="pasi/control-test",
                phase="engineering_os",
                current_task="task",
                current_task_id="task.id",
                task_retry_cycle=4,
                current_attempt=3,
                last_failure_signature="failure",
            )
            control.write_text(json.dumps({
                "schema_version": 1,
                "action": "retry_current",
                "task_id": "other.id",
            }), encoding="utf-8")
            with (
                mock.patch.object(engine, "RUNNER_CONTROL_PATH", control),
                mock.patch.object(engine, "log_event"),
            ):
                assert consume_runner_control(state) is False
            self.assertEqual(state.task_retry_cycle, 4)
            self.assertEqual(state.current_attempt, 3)
            self.assertEqual(state.last_failure_signature, "failure")
            self.assertFalse(control.exists())


if __name__ == "__main__":
    unittest.main()


def test_verify_and_commit_skips_duplicate_pre_commit_status_only_for_fast_gate() -> None:
    source = Path(__file__).resolve().parents[0] / "pasi_overnight_engine_v2.py"
    content = source.read_text(encoding="utf-8")
    fast_index = content.index('if gate_mode == "fast":')
    status_index = content.index('code, status = command(["git", "status", "--porcelain"], worktree, 30.0)', fast_index)
    else_index = content.index("else:", fast_index)
    assert fast_index < status_index
    assert else_index < status_index
    assert 'changed_file_count = int(gate_match.group(1)) if gate_match else 0' in content
