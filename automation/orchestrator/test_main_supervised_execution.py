from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

from automation.orchestrator.context_schema import ContextPackage
from automation.orchestrator.execution_schema import ExecutionRequest, ExecutionResult
from automation.orchestrator.fake_planner_adapter import FakePlannerAdapter
from automation.orchestrator.main import main
from automation.orchestrator.planner_schema import PlannerResult, ProposedStep
from automation.orchestrator.state import StateManager
from src import policy


class RecordingExecutionAdapter:
    def __init__(self) -> None:
        self.requests: list[ExecutionRequest] = []

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        self.requests.append(request)
        return ExecutionResult(
            request_id=request.request_id,
            task_id=request.task_id,
            step_id=request.step_id,
            action=request.action,
            status="executed",
            output={"ok": True},
        )


class FakeTests:
    def detect_commands(self):
        return []

    def run_project_tests(self):
        return []


def make_project(tmp_path: Path) -> tuple[Path, Path]:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / ".git").mkdir()

    ai_dir = tmp_path / ".ai"
    ai_dir.mkdir()
    return project_root, ai_dir


def test_main_invokes_supervised_execution_when_dependencies_are_supplied(
    tmp_path: Path,
) -> None:
    project_root, ai_dir = make_project(tmp_path)
    connection = sqlite3.connect(":memory:")
    policy.initialize(connection)
    adapter = RecordingExecutionAdapter()

    planner_adapter = FakePlannerAdapter(
        proposed_steps=[
            ProposedStep(
                step_id="step-1",
                description="Run simulation.",
                required_capabilities=["run_simulation"],
            )
        ],
        required_capabilities=["run_simulation"],
    )

    fake_config = type(
        "Config",
        (),
        {
            "project_root": project_root,
            "ai_dir": ai_dir,
        },
    )()

    with patch(
        "automation.orchestrator.main.CONFIG",
        fake_config,
    ), patch(
        "automation.orchestrator.main.TestRunner",
        return_value=FakeTests(),
    ), patch(
        "automation.orchestrator.main.ensure_runtime_directories",
    ), patch(
        "automation.orchestrator.main.FakePlannerAdapter",
        return_value=planner_adapter,
    ):
        result = main(
            "Run a simulation.",
            connection=connection,
            execution_adapter=adapter,
            actor_id="user-1",
        )

    assert isinstance(result, PlannerResult)
    assert len(adapter.requests) == 1
    assert adapter.requests[0].action == "run_simulation"

    state = StateManager(ai_dir)
    task = state.load_current_task()
    project_state = state.load_project_state()
    execution = state.load_execution_result()
    context = ContextPackage.model_validate(state.load_context_package())

    assert task["phase"] == "completed"
    assert project_state["current_phase"] == "completed"
    assert execution["status"] == "executed"
    assert execution["task_id"] == task["task_id"]
    assert context.objective.primary == "Run a simulation."


def test_main_requires_actor_id_when_supervised_execution_is_enabled(
    tmp_path: Path,
) -> None:
    project_root, ai_dir = make_project(tmp_path)
    connection = sqlite3.connect(":memory:")
    policy.initialize(connection)

    fake_config = type(
        "Config",
        (),
        {
            "project_root": project_root,
            "ai_dir": ai_dir,
        },
    )()

    with patch("automation.orchestrator.main.CONFIG", fake_config):
        try:
            main(
                "Run a simulation.",
                connection=connection,
                execution_adapter=RecordingExecutionAdapter(),
            )
        except ValueError as exc:
            assert "actor_id is required" in str(exc)
        else:
            raise AssertionError("Expected ValueError for missing actor_id")
