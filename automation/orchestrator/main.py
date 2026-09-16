from __future__ import annotations

import argparse
from uuid import uuid4

from .config import CONFIG, ensure_runtime_directories
from .context_builder import ContextBuilder
from .context_schema import ExecutionPolicy, ObjectiveContext
from .git_manager import GitManager
from .models import CurrentTask, ProjectState
from .planner import Planner
from .planner_schema import PlannerResult
from .fake_planner_adapter import FakePlannerAdapter
from .state import StateManager
from .test_runner import TestRunner


DEFAULT_OBJECTIVE = "Inspect the current project state."
DEFAULT_FEATURE = "orchestrator"


def main(objective: str = DEFAULT_OBJECTIVE) -> PlannerResult:
    ensure_runtime_directories()

    state = StateManager(CONFIG.ai_dir)
    git = GitManager(CONFIG.project_root)
    tests = TestRunner(CONFIG.project_root)
    context_builder = ContextBuilder(
        project_root=CONFIG.project_root,
        git=git,
        state=state,
    )
    planner = Planner()

    branch = git.current_branch()
    head = git.head_commit()

    task = CurrentTask(
        task_id=f"task_{uuid4().hex}",
        feature=DEFAULT_FEATURE,
        objective=objective,
        status="running",
        phase="precheck",
    )

    project_state = ProjectState(
        project="personal-ai-system",
        status="running",
        current_feature=task.feature,
        current_phase=task.phase,
        current_task_id=task.task_id,
        current_branch=branch,
        last_successful_commit=head,
    )

    state.save_current_task(task)
    state.save_project_state(project_state)

    git_status = git.status()

    print()
    print("=== PERSONAL AI SYSTEM ORCHESTRATOR ===")
    print()
    print(f"Project:   {CONFIG.project_root}")
    print(f"Branch:    {branch}")
    print(f"HEAD:      {head}")
    print(f"Task:      {task.task_id}")
    print(f"Objective: {objective}")
    print()

    print("=== GIT STATUS ===")

    if git_status.stdout.strip():
        print(git_status.stdout)
    else:
        print("Working tree appears clean.")

    print()
    print("=== TEST DISCOVERY ===")

    commands = tests.detect_commands()

    if not commands:
        print("No supported test configuration detected.")
    else:
        print("Detected test commands:")

        for command in commands:
            print(f"  {' '.join(command)}")

        print()
        print("=== TEST EXECUTION ===")

        results = tests.run_project_tests()

        for result in results:
            print()
            print(f"Command: {' '.join(result.command)}")
            print(f"Exit:    {result.return_code}")
            print(f"Status:  {'PASS' if result.success else 'FAIL'}")
            print(f"Time:    {result.duration_seconds:.2f}s")

            if result.stdout:
                print()
                print("STDOUT:")
                print(result.stdout)

            if result.stderr:
                print()
                print("STDERR:")
                print(result.stderr)

            state.save_test_results(
                {
                    "success": result.success,
                    "command": result.command,
                    "return_code": result.return_code,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "duration_seconds": result.duration_seconds,
                }
            )

    execution_policy = ExecutionPolicy()

    agent_request = planner.build_request(
        task=task,
        execution_policy=execution_policy,
    )

    context_package = context_builder.build(
        objective=ObjectiveContext(
            primary=objective,
        ),
        execution_policy=execution_policy,
        agent_request=agent_request,
    )
    state.save_context_package(context_package)

    planner_adapter = FakePlannerAdapter()

    planner_result = PlannerResult.model_validate(
        planner_adapter.plan(
            agent_request,
            context_package,
        ).model_dump()
    )

    task.status = "ready"
    task.phase = "context_ready"

    project_state.status = "idle"
    project_state.current_phase = "context_ready"

    state.save_current_task(task)
    state.save_project_state(project_state)

    print()
    print("=== CONTEXT PACKAGE ===")
    print(f"Context ID: {context_package.context_id}")
    print(f"Objective:  {context_package.objective.primary}")
    print(
        f"Git:       "
        f"{context_package.git_wsl.branch} @ {context_package.git_wsl.head}"
    )
    print(f"Tests:     {context_package.tests.status}")

    browser_status = (
        "available"
        if context_package.browser.available
        else "unavailable"
    )
    print(f"Browser:   {browser_status}")
    print(f"Saved:     {state.context_package_path}")
    print(f"Task:      {task.task_id}")
    print(f"Task state: {task.status}/{task.phase}")
    print()
    print("=== PLANNER RESULT ===")
    print(f"Proposed steps: {len(planner_result.proposed_steps)}")
    print(f"Required capabilities: {planner_result.required_capabilities}")
    print(
        f"Verification requirements: "
        f"{planner_result.verification_requirements}"
    )
    print(f"Blockers: {planner_result.blockers}")

    print()
    print("Orchestrator context preparation and planning complete.")

    return planner_result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run the PASI read-only project precheck."
    )
    parser.add_argument(
        "objective",
        nargs="?",
        default=DEFAULT_OBJECTIVE,
        help="Objective used to create the CurrentTask and ContextPackage.",
    )
    main(parser.parse_args().objective)
