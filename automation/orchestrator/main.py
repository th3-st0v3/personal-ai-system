from __future__ import annotations

import argparse
from uuid import uuid4

from .config import CONFIG, ensure_runtime_directories
from .context_builder import ContextBuilder
from .context_schema import (
    ExecutionPolicy,
    ObjectiveContext,
    ResearchContext,
)
from .fake_planner_adapter import FakePlannerAdapter
from .fake_research_collector import FakeResearchCollector
from .git_manager import GitManager
from .models import CurrentTask, ProjectState
from .orchestration_state import transition
from .planner import Planner
from .planner_schema import PlannerResult
from .research_collector_schema import ResearchRequest
from .research_state import ResearchState
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
        status="queued",
        phase="selection",
    )

    project_state = ProjectState(
        project="personal-ai-system",
        status="idle",
        current_feature=task.feature,
        current_phase=task.phase,
        current_task_id=task.task_id,
        current_branch=branch,
        last_successful_commit=head,
    )

    state.save_current_task(task)
    state.save_project_state(project_state)

    transition(task, project_state, "precheck")
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
    print(f"Objective: {task.objective}")
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

    transition(task, project_state, "research")
    state.save_current_task(task)
    state.save_project_state(project_state)

    execution_policy = ExecutionPolicy()

    research_request = ResearchRequest(
        objective=task.objective,
    )

    research_collector = FakeResearchCollector()
    research_result = research_collector.collect(research_request)
    research_state = ResearchState(
        task_id=task.task_id,
        observations=list(research_result.observations),
        findings=list(research_result.findings),
        sources_considered=list(
            research_result.sources_considered
        ),
        unanswered_questions=list(
            research_result.unanswered_questions
        ),
        evidence_quality=research_result.evidence_quality,
    )

    state.save_research_state(research_state)

    research_context = ResearchContext(
        objective=research_result.objective,
        observations=list(research_result.observations),
        findings=list(research_result.findings),
        sources_considered=list(
            research_result.sources_considered
        ),
        unanswered_questions=list(
            research_result.unanswered_questions
        ),
        evidence_quality=research_result.evidence_quality,
    )

    transition(task, project_state, "context_ready")
    state.save_current_task(task)
    state.save_project_state(project_state)

    agent_request = planner.build_request(
        task=task,
        execution_policy=execution_policy,
    )

    context_package = context_builder.build(
        objective=ObjectiveContext(
            primary=task.objective,
        ),
        execution_policy=execution_policy,
        research=research_context,
        agent_request=agent_request,
    )
    state.save_context_package(context_package)

    transition(task, project_state, "planning")
    state.save_current_task(task)
    state.save_project_state(project_state)

    planner_adapter = FakePlannerAdapter()

    planner_result = PlannerResult.model_validate(
        planner_adapter.plan(
            agent_request,
            context_package,
        ).model_dump()
    )

    task.status = "ready"
    project_state.status = "idle"

    state.save_current_task(task)
    state.save_project_state(project_state)

    print()
    print("=== RESEARCH RESULT ===")
    print(f"Objective: {research_result.objective}")
    print(f"Observations: {len(research_result.observations)}")
    print(f"Findings: {len(research_result.findings)}")
    print(
        f"Sources considered: "
        f"{research_result.sources_considered}"
    )
    print(
        f"Unanswered questions: "
        f"{research_result.unanswered_questions}"
    )
    print(
        f"Evidence quality: "
        f"{research_result.evidence_quality}"
    )

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
