from __future__ import annotations

import sqlite3
from pathlib import Path

from automation.orchestrator.authorized_executor import AuthorizedExecutor
from automation.orchestrator.context_schema import (
    AgentRequest,
    BrowserContext,
    ContextPackage,
    EvidenceQuality,
    ExecutionPolicy,
    FilesContext,
    GitWslContext,
    MemoryContext,
    ObjectiveContext,
    ProjectContext,
    RepositoryContext,
    TestContext as PASITestContext,
    TestSummary as PASITestSummary,
    WorkingTreeContext,
)
from automation.orchestrator.execution_adapter import ExecutionAdapter
from automation.orchestrator.execution_schema import ExecutionRequest, ExecutionResult
from automation.orchestrator.models import CurrentTask, ProjectState
from automation.orchestrator.orchestration_loop import (
    BrowserVerificationResult,
    Diagnosis,
    run_supervised_execution,
)
from automation.orchestrator.planner_schema import PlannerResult, ProposedStep
from automation.orchestrator.state import StateManager
from src import policy


class RecordingAdapter:
    def __init__(self, *, should_fail: bool = False) -> None:
        self.requests: list[ExecutionRequest] = []
        self.should_fail = should_fail

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        self.requests.append(request)
        if self.should_fail:
            raise RuntimeError("simulated execution failure")
        return ExecutionResult(
            request_id=request.request_id,
            task_id=request.task_id,
            step_id=request.step_id,
            action=request.action,
            status="executed",
            output={"ok": True},
        )


class FakeTests:
    def __init__(self, results) -> None:
        self.results = list(results)

    def run_project_tests(self):
        return list(self.results)


class FakeBrowser:
    def __init__(self, result: BrowserVerificationResult) -> None:
        self.result = result

    def verify(self) -> BrowserVerificationResult:
        return self.result


class OneRetryPlanner:
    def __init__(self, replacement: PlannerResult) -> None:
        self.replacement = replacement
        self.calls: list[Diagnosis] = []

    def replan(
        self,
        plan: PlannerResult,
        context: ContextPackage,
        diagnosis: Diagnosis,
    ) -> PlannerResult:
        self.calls.append(diagnosis)
        return self.replacement


def make_task() -> tuple[CurrentTask, ProjectState]:
    task = CurrentTask(
        task_id="task-1",
        feature="orchestrator",
        objective="Run a simulation.",
        phase="planning",
        status="running",
    )
    project_state = ProjectState(
        current_task_id=task.task_id,
        current_feature=task.feature,
        current_phase="planning",
        status="running",
    )
    return task, project_state


def make_context() -> ContextPackage:
    return ContextPackage.create(
        context_id="ctx-1",
        objective=ObjectiveContext(
            primary="Run a simulation.",
        ),
        project=ProjectContext(
            project_id="project-1",
            name="Simulation Project",
            repository=RepositoryContext(
                provider="local",
                repository="project",
                branch="main",
            ),
        ),
        memory=MemoryContext(
            query="Run a simulation.",
        ),
        git_wsl=GitWslContext(
            branch="main",
            head="abc123",
            sync_state="SYNCED",
            working_tree=WorkingTreeContext(
                clean=True,
            ),
            ahead=0,
            behind=0,
        ),
        tests=PASITestContext(
            status="passed",
            summary=PASITestSummary(
                passed=0,
                failed=0,
                skipped=0,
                errors=0,
            ),
        ),
        browser=BrowserContext(
            available=False,
        ),
        files=FilesContext(),
        execution_policy=ExecutionPolicy(),
        evidence_quality=EvidenceQuality(
            overall="good",
        ),
        agent_request=AgentRequest(
            task="Run a simulation.",
            expected_output=[],
        ),
    )


def make_executor(adapter: ExecutionAdapter) -> tuple[sqlite3.Connection, AuthorizedExecutor]:
    connection = sqlite3.connect(":memory:")
    policy.initialize(connection)
    return connection, AuthorizedExecutor(connection, adapter)


def make_plan(*, browser: bool = False) -> PlannerResult:
    step_requirements = ["browser"] if browser else []
    return PlannerResult(
        proposed_steps=[
            ProposedStep(
                step_id="step-1",
                description="Run the simulation.",
                required_capabilities=["run_simulation"],
                verification_requirements=step_requirements,
            )
        ],
        required_capabilities=["run_simulation"],
        verification_requirements=["browser"] if browser else [],
    )


def test_safe_execution_runs_tests_and_completes(tmp_path: Path) -> None:
    task, project_state = make_task()
    adapter = RecordingAdapter()
    connection, executor = make_executor(adapter)
    state = StateManager(tmp_path / ".ai")

    result = run_supervised_execution(
        connection,
        actor_id="user-1",
        task=task,
        project_state=project_state,
        plan=make_plan(),
        context=make_context(),
        state=state,
        executor=executor,
        test_runner=FakeTests([]),
    )

    assert result.status == "completed"
    assert task.phase == "completed"
    assert len(adapter.requests) == 1
    assert state.load_execution_result()["status"] == "executed"
    assert state.load_retry_state()["replans"] == 0


def test_consequential_plan_waits_for_external_approval(tmp_path: Path) -> None:
    task, project_state = make_task()
    adapter = RecordingAdapter()
    connection, executor = make_executor(adapter)
    state = StateManager(tmp_path / ".ai")
    plan = PlannerResult(
        proposed_steps=[
            ProposedStep(
                step_id="step-1",
                description="Execute code.",
                required_capabilities=["execute_code"],
            )
        ],
        required_capabilities=["execute_code"],
    )

    result = run_supervised_execution(
        connection,
        actor_id="user-1",
        task=task,
        project_state=project_state,
        plan=plan,
        context=make_context(),
        state=state,
        executor=executor,
        test_runner=FakeTests([]),
    )

    assert result.status == "awaiting_approval"
    assert task.phase == "awaiting_approval"
    assert adapter.requests == []
    assert state.load_retry_state()["source"] == "authorization"


def test_execution_failure_routes_to_diagnosis_and_replan(tmp_path: Path) -> None:
    task, project_state = make_task()
    adapter = RecordingAdapter(should_fail=True)
    connection, executor = make_executor(adapter)
    state = StateManager(tmp_path / ".ai")
    replacement = PlannerResult()
    replanner = OneRetryPlanner(replacement)

    result = run_supervised_execution(
        connection,
        actor_id="user-1",
        task=task,
        project_state=project_state,
        plan=make_plan(),
        context=make_context(),
        state=state,
        executor=executor,
        test_runner=FakeTests([]),
        replanner=replanner,
        max_replans=1,
    )

    assert result.status == "completed"
    assert result.replans == 1
    assert result.diagnosis is None
    assert len(replanner.calls) == 1
    assert replanner.calls[0].source == "execution"
    assert task.phase == "completed"
    assert state.load_retry_state()["replans"] == 1
    assert len(result.execution_results) == 1


def test_failed_tests_route_to_diagnosis_and_handoff_when_retry_budget_is_exhausted(tmp_path: Path) -> None:
    task, project_state = make_task()
    adapter = RecordingAdapter()
    connection, executor = make_executor(adapter)
    state = StateManager(tmp_path / ".ai")
    failing_test = type(
        "Result",
        (),
        {
            "command": ["pytest", "-q"],
            "return_code": 1,
            "stdout": "",
            "stderr": "failure",
            "duration_seconds": 0.1,
            "success": False,
        },
    )()

    result = run_supervised_execution(
        connection,
        actor_id="user-1",
        task=task,
        project_state=project_state,
        plan=make_plan(),
        context=make_context(),
        state=state,
        executor=executor,
        test_runner=FakeTests([failing_test]),
        max_replans=0,
    )

    assert result.status == "handoff"
    assert result.diagnosis is not None
    assert result.diagnosis.source == "testing"
    assert task.phase == "handoff"
    assert state.load_retry_state()["source"] == "testing"


def test_browser_failure_routes_to_diagnosis(tmp_path: Path) -> None:
    task, project_state = make_task()
    adapter = RecordingAdapter()
    connection, executor = make_executor(adapter)
    state = StateManager(tmp_path / ".ai")
    browser = FakeBrowser(
        BrowserVerificationResult(
            success=False,
            details="Login button remains disabled.",
        )
    )

    result = run_supervised_execution(
        connection,
        actor_id="user-1",
        task=task,
        project_state=project_state,
        plan=make_plan(browser=True),
        context=make_context(),
        state=state,
        executor=executor,
        test_runner=FakeTests([]),
        browser_verifier=browser,
        max_replans=0,
    )

    assert result.status == "handoff"
    assert result.diagnosis is not None
    assert result.diagnosis.source == "browser_verification"
    assert task.phase == "handoff"
    assert state.load_browser_results()["success"] is False
    assert state.load_retry_state()["source"] == "browser_verification"


def test_missing_browser_verifier_is_not_treated_as_success(tmp_path: Path) -> None:
    task, project_state = make_task()
    adapter = RecordingAdapter()
    connection, executor = make_executor(adapter)
    state = StateManager(tmp_path / ".ai")

    result = run_supervised_execution(
        connection,
        actor_id="user-1",
        task=task,
        project_state=project_state,
        plan=make_plan(browser=True),
        context=make_context(),
        state=state,
        executor=executor,
        test_runner=FakeTests([]),
        max_replans=0,
    )

    assert result.status == "handoff"
    assert result.diagnosis is not None
    assert result.diagnosis.source == "browser_verification"
