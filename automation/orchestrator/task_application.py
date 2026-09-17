from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from automation.computer_use.adapters import (
    AIAdapter,
    ComputerAdapter,
    GitHubAdapter,
    IDEAdapter,
    ResearchAdapter,
)
from automation.computer_use.browser_use_adapter import BrowserUseTaskAdapter
from automation.computer_use.contracts import Session
from automation.computer_use.controller import ControlPlane

from .background_worker import BackgroundWorker, WorkerExecutor
from .semantic_executor import CommandAdapter, SemanticExecutor
from .state import StateManager
from .task_goal import EvidenceGoalChecker, TaskGoal
from .task_planner import AIAdapterModelClient, StructuredTaskPlanner
from .task_runner import BoundedTaskRunner, CompletionChecker, TaskPlanner
from .task_service import TaskRunFactory
from .verification_telemetry import VerificationTelemetry
from .worker_verification import WorkerVerifier

GoalFactory = Callable[[str, Session], TaskGoal]


@dataclass(frozen=True)
class TaskRuntimeConfig:
    """Stable bounds and task metadata used by the application composition root."""

    project: str
    allowed_applications: tuple[str, ...] = ()
    workspace_root: str | None = None
    max_duration_seconds: int = 3600
    max_steps: int = 32
    max_observations: int = 64
    max_repeated_observation: int = 2
    planner_poll_interval_seconds: float = 0.5
    planner_max_wait_seconds: float = 300.0

    def __post_init__(self) -> None:
        if not self.project.strip():
            raise ValueError("project is required")
        if self.max_duration_seconds <= 0:
            raise ValueError("max_duration_seconds must be positive")
        if self.max_steps <= 0 or self.max_observations <= 0 or self.max_repeated_observation <= 0:
            raise ValueError("task runner bounds must be positive")
        if self.planner_poll_interval_seconds <= 0 or self.planner_max_wait_seconds <= 0:
            raise ValueError("planner polling bounds must be positive")


@dataclass(frozen=True)
class TaskRuntimeDependencies:
    """Provider implementations supplied by the application, not selected by the model."""

    ai: AIAdapter
    ide: IDEAdapter | None = None
    github: GitHubAdapter | None = None
    research: ResearchAdapter | None = None
    browser: BrowserUseTaskAdapter | None = None
    desktop: ComputerAdapter | None = None
    command: CommandAdapter | None = None
    telemetry: VerificationTelemetry | None = None
    verifier: WorkerVerifier | None = None


class ConfiguredTaskRunFactory(TaskRunFactory):
    """Build fully wired bounded task runners from explicit application dependencies."""

    def __init__(
        self,
        state_manager: StateManager,
        dependencies: TaskRuntimeDependencies,
        config: TaskRuntimeConfig,
        goal_factory: GoalFactory,
    ) -> None:
        self.state_manager = state_manager
        self.dependencies = dependencies
        self.config = config
        self.goal_factory = goal_factory

    def create(self, *, runner_id: str, prompt: str) -> BoundedTaskRunner:
        prompt = prompt.strip()
        if not prompt:
            raise ValueError("prompt must be non-empty")
        session = Session(
            session_id=f"session-{runner_id}",
            task_id=runner_id,
            project=self.config.project,
            allowed_applications=self.config.allowed_applications,
            workspace_root=self.config.workspace_root,
            max_duration_seconds=self.config.max_duration_seconds,
            background=True,
        )
        goal = self.goal_factory(prompt, session)
        if not isinstance(goal, TaskGoal):
            raise TypeError("goal_factory must return TaskGoal")
        planner_model = AIAdapterModelClient(
            self.dependencies.ai,
            poll_interval_seconds=self.config.planner_poll_interval_seconds,
            max_wait_seconds=self.config.planner_max_wait_seconds,
        )
        planner: TaskPlanner = StructuredTaskPlanner(session, planner_model)
        executor: WorkerExecutor = SemanticExecutor(
            ai=self.dependencies.ai,
            ide=self.dependencies.ide,
            github=self.dependencies.github,
            research=self.dependencies.research,
            browser=self.dependencies.browser,
            desktop=self.dependencies.desktop,
            command=self.dependencies.command,
        )
        control_plane = ControlPlane(session)
        worker = BackgroundWorker(
            self.state_manager,
            runner_id,
            control_plane,
            telemetry=self.dependencies.telemetry,
            verifier=self.dependencies.verifier,
        )
        completion_checker: CompletionChecker = EvidenceGoalChecker(goal)
        return BoundedTaskRunner(
            self.state_manager,
            runner_id,
            worker,
            planner,
            executor,
            completion_checker,
            max_steps=self.config.max_steps,
            max_observations=self.config.max_observations,
            max_repeated_observation=self.config.max_repeated_observation,
        )


__all__ = ["ConfiguredTaskRunFactory", "GoalFactory", "TaskRuntimeConfig", "TaskRuntimeDependencies"]
