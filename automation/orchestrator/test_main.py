from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from automation.orchestrator.context_schema import (
    AgentRequest,
    ContextPackage,
)
from automation.orchestrator.research_collector_schema import (
    ResearchRequest,
    ResearchResult,
)
from automation.orchestrator.research_schema import ResearchObservation
from automation.orchestrator.research_state import ResearchState
from automation.orchestrator.main import main
from automation.orchestrator.state import StateManager
from automation.orchestrator.planner_schema import PlannerResult


def make_fake_config(
    project_root: Path,
    ai_dir: Path,
):
    return type(
        "Config",
        (),
        {
            "project_root": project_root,
            "ai_dir": ai_dir,
        },
    )()


def make_fake_test_runner():
    class FakeTests:
        def detect_commands(self):
            return []

        def run_project_tests(self):
            return []

    return FakeTests()


def run_main(
    project_root: Path,
    ai_dir: Path,
    objective: str | None = None,
) -> PlannerResult:
    fake_config = make_fake_config(project_root, ai_dir)
    fake_tests = make_fake_test_runner()

    with patch(
        "automation.orchestrator.main.CONFIG",
        fake_config,
    ), patch(
        "automation.orchestrator.main.TestRunner",
        return_value=fake_tests,
    ), patch(
        "automation.orchestrator.main.ensure_runtime_directories",
    ):
        if objective is None:
            return main()
        else:
            return main(objective)


def test_main_builds_and_persists_context_package(
    tmp_path: Path,
) -> None:
    ai_dir = tmp_path / ".ai"
    ai_dir.mkdir()

    project_root = tmp_path / "project"
    project_root.mkdir()

    run_main(
        project_root,
        ai_dir,
        "Make the login button work.",
    )

    state = StateManager(ai_dir)
    payload = state.load_context_package()

    assert payload["schema_version"] == "1.0"
    assert (
        payload["objective"]["primary"]
        == "Make the login button work."
    )

    package = ContextPackage.model_validate(payload)

    assert (
        package.objective.primary
        == "Make the login button work."
    )
    assert package.project.name == "project"

    raw = state.context_package_path.read_text(
        encoding="utf-8",
    )
    assert json.loads(raw) == payload


def test_main_persists_planning_request_in_context(
    tmp_path: Path,
) -> None:
    ai_dir = tmp_path / ".ai"
    ai_dir.mkdir()

    project_root = tmp_path / "project"
    project_root.mkdir()

    run_main(
        project_root,
        ai_dir,
        "Make the login button work.",
    )

    context = StateManager(ai_dir).load_context_package()

    assert (
        context["agent_request"]["task"]
        == "Make the login button work."
    )
    assert context["agent_request"]["expected_output"] == [
        "proposed plan",
        "required verification",
        "identified blockers",
    ]
    assert (
        "Do not execute actions."
        in context["agent_request"]["restrictions"]
    )


def test_main_uses_default_objective_when_called_without_argument(
    tmp_path: Path,
) -> None:
    ai_dir = tmp_path / ".ai"
    ai_dir.mkdir()

    project_root = tmp_path / "project"
    project_root.mkdir()

    run_main(
        project_root,
        ai_dir,
    )

    payload = StateManager(ai_dir).load_context_package()

    assert (
        payload["objective"]["primary"]
        == "Inspect the current project state."
    )


def test_main_marks_precheck_complete(
    tmp_path: Path,
) -> None:
    ai_dir = tmp_path / ".ai"
    ai_dir.mkdir()

    project_root = tmp_path / "project"
    project_root.mkdir()

    run_main(
        project_root,
        ai_dir,
        "Verify precheck integration.",
    )

    project_state = StateManager(ai_dir).load_project_state()

    assert project_state["status"] == "idle"
    assert (
        project_state["current_phase"]
        == "context_ready"
    )


def test_main_creates_and_advances_current_task(
    tmp_path: Path,
) -> None:
    ai_dir = tmp_path / ".ai"
    ai_dir.mkdir()

    project_root = tmp_path / "project"
    project_root.mkdir()

    run_main(
        project_root,
        ai_dir,
        "Make the login button work.",
    )

    state = StateManager(ai_dir)
    task = state.load_current_task()
    project_state = state.load_project_state()

    assert task["objective"] == "Make the login button work."
    assert task["feature"] == "orchestrator"
    assert task["status"] == "ready"
    assert task["phase"] == "context_ready"
    assert task["attempt"] == 0

    assert project_state["current_task_id"] == task["task_id"]
    assert project_state["current_feature"] == "orchestrator"
    assert project_state["current_phase"] == "context_ready"


def test_main_uses_same_task_for_context_objective(
    tmp_path: Path,
) -> None:
    ai_dir = tmp_path / ".ai"
    ai_dir.mkdir()

    project_root = tmp_path / "project"
    project_root.mkdir()

    objective = "Verify the authentication flow."

    run_main(
        project_root,
        ai_dir,
        objective,
    )

    state = StateManager(ai_dir)
    task = state.load_current_task()
    context = state.load_context_package()

    assert task["objective"] == objective
    assert context["objective"]["primary"] == task["objective"]


def test_main_converts_context_package_into_planner_result(
    tmp_path: Path,
) -> None:
    ai_dir = tmp_path / ".ai"
    ai_dir.mkdir()

    project_root = tmp_path / "project"
    project_root.mkdir()

    result = run_main(
        project_root,
        ai_dir,
        "Make the login button work.",
    )

    assert isinstance(result, PlannerResult)
    assert result.proposed_steps == []
    assert result.required_capabilities == []
    assert result.verification_requirements == []
    assert result.blockers == []


def test_main_plans_with_the_same_agent_request_and_context_package(
    tmp_path: Path,
) -> None:
    ai_dir = tmp_path / ".ai"
    ai_dir.mkdir()

    project_root = tmp_path / "project"
    project_root.mkdir()

    captured_request: AgentRequest | None = None
    captured_context: ContextPackage | None = None

    class CapturingAdapter:
        def plan(
            self,
            request: AgentRequest,
            context: ContextPackage,
        ) -> PlannerResult:
            nonlocal captured_request, captured_context
            captured_request = request
            captured_context = context

            return PlannerResult(
                proposed_steps=[],
                required_capabilities=[],
                verification_requirements=["Run the relevant tests."],
                blockers=[],
            )

    with patch(
        "automation.orchestrator.main.FakePlannerAdapter",
        return_value=CapturingAdapter(),
    ):
        result = run_main(
            project_root,
            ai_dir,
            "Verify the authentication flow.",
        )

    assert isinstance(result, PlannerResult)
    assert result.verification_requirements == [
        "Run the relevant tests."
    ]

    state = StateManager(ai_dir)
    persisted_context = ContextPackage.model_validate(
        state.load_context_package()
    )

    assert captured_request is not None
    assert captured_context is not None

    assert captured_request.task == "Verify the authentication flow."
    assert captured_context.objective.primary == "Verify the authentication flow."
    assert captured_context == persisted_context


def test_main_collects_research_for_the_task(
    tmp_path: Path,
) -> None:
    ai_dir = tmp_path / ".ai"
    ai_dir.mkdir()

    project_root = tmp_path / "project"
    project_root.mkdir()

    captured_request: ResearchRequest | None = None
    captured_result: ResearchResult | None = None

    class CapturingCollector:
        def collect(
            self,
            request: ResearchRequest,
        ) -> ResearchResult:
            nonlocal captured_request, captured_result

            captured_request = request
            captured_result = ResearchResult(
                objective=request.objective,
                observations=[
                    ResearchObservation(
                        observation_id="obs-1",
                        subject="login",
                        aspect="route",
                        statement="The login route exists.",
                    )
                ],
                findings=[],
                sources_considered=["repo://src/login.py"],
                unanswered_questions=[
                    "Browser behavior still needs verification."
                ],
                evidence_quality="good",
            )
            return captured_result

    with patch(
        "automation.orchestrator.main.FakeResearchCollector",
        return_value=CapturingCollector(),
    ):
        run_main(
            project_root,
            ai_dir,
            "Make the login button work.",
        )

    assert captured_request is not None
    assert captured_result is not None

    assert captured_request.objective == (
        "Make the login button work."
    )

    context = ContextPackage.model_validate(
        StateManager(ai_dir).load_context_package()
    )

    assert context.research is not None
    assert context.research.objective == (
        "Make the login button work."
    )
    assert context.research.observations == [
        "The login route exists."
    ]
    assert context.research.sources_considered == [
        "repo://src/login.py"
    ]
    assert context.research.unanswered_questions == [
        "Browser behavior still needs verification."
    ]
    assert context.research.evidence_quality == "good"


def test_main_persists_research_state_for_current_task(
    tmp_path: Path,
) -> None:
    ai_dir = tmp_path / ".ai"
    ai_dir.mkdir()

    project_root = tmp_path / "project"
    project_root.mkdir()

    class CapturingCollector:
        def collect(
            self,
            request: ResearchRequest,
        ) -> ResearchResult:
            return ResearchResult(
                objective=request.objective,
                observations=[
                    ResearchObservation(
                        observation_id="obs-1",
                        subject="login",
                        aspect="route",
                        statement="The login route exists.",
                    )
                ],
                findings=[],
                sources_considered=["repo://src/login.py"],
                unanswered_questions=[
                    "Browser behavior still needs verification."
                ],
                evidence_quality="good",
            )

    with patch(
        "automation.orchestrator.main.FakeResearchCollector",
        return_value=CapturingCollector(),
    ):
        run_main(
            project_root,
            ai_dir,
            "Make the login button work.",
        )

    state = StateManager(ai_dir)
    task = state.load_current_task()
    research = ResearchState.model_validate(
        state.load_research_state()
    )

    assert research.task_id == task["task_id"]
    assert research.observations[0].statement == (
        "The login route exists."
    )
    assert research.sources_considered == [
        "repo://src/login.py"
    ]
    assert research.unanswered_questions == [
        "Browser behavior still needs verification."
    ]
    assert research.evidence_quality == "good"
