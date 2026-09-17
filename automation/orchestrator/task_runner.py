from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Literal, Protocol, Sequence

from automation.computer_use.contracts import ActionProposal, Observation

from .background_worker import BackgroundWorker, WorkerExecutionError, WorkerExecutor, WorkerPhase
from .state import StateCorruptionError, StateManager


RunnerPhase = Literal[
    "stopped",
    "running",
    "waiting_human",
    "paused",
    "completed",
    "failed",
]
CompletionStatus = Literal["complete", "incomplete", "failed"]


@dataclass(frozen=True)
class CompletionDecision:
    """Deterministic completion decision; this seam never grants execution authority."""

    status: CompletionStatus
    reason: str

    @property
    def complete(self) -> bool:
        return self.status == "complete"


class TaskPlanner(Protocol):
    """Provider-neutral planner that proposes one semantic action at a time."""

    def plan(self, observations: Sequence[Observation]) -> ActionProposal | None: ...


class CompletionChecker(Protocol):
    """Deterministic goal checker required before a run may be marked complete."""

    def check(self, observations: Sequence[Observation]) -> CompletionDecision: ...


@dataclass(frozen=True)
class TaskRunnerState:
    runner_id: str
    phase: RunnerPhase = "stopped"
    steps: int = 0
    observations: tuple[str, ...] = ()
    last_action_id: str | None = None
    last_error: str | None = None
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "TaskRunnerState":
        runner_id = data.get("runner_id")
        if not isinstance(runner_id, str) or not runner_id.strip():
            raise StateCorruptionError("Invalid task runner state: runner_id is required")

        phase = data.get("phase", "stopped")
        valid_phases = {"stopped", "running", "waiting_human", "paused", "completed", "failed"}
        if phase not in valid_phases:
            raise StateCorruptionError("Invalid task runner state: unknown phase")

        steps = data.get("steps", 0)
        if not isinstance(steps, int) or steps < 0:
            raise StateCorruptionError("Invalid task runner state: steps must be a non-negative integer")

        observations = data.get("observations", ())
        if isinstance(observations, list):
            observations = tuple(observations)
        if not isinstance(observations, tuple) or any(not isinstance(item, str) for item in observations):
            raise StateCorruptionError("Invalid task runner state: observations must be string fingerprints")

        last_action_id = data.get("last_action_id")
        if last_action_id is not None and not isinstance(last_action_id, str):
            raise StateCorruptionError("Invalid task runner state: last_action_id must be a string or null")

        last_error = data.get("last_error")
        if last_error is not None and not isinstance(last_error, str):
            raise StateCorruptionError("Invalid task runner state: last_error must be a string or null")

        updated_at = data.get("updated_at", "")
        if not isinstance(updated_at, str):
            raise StateCorruptionError("Invalid task runner state: updated_at must be a string")

        return cls(
            runner_id=runner_id,
            phase=phase,
            steps=steps,
            observations=observations,
            last_action_id=last_action_id,
            last_error=last_error,
            updated_at=updated_at,
        )


@dataclass(frozen=True)
class TaskRunResult:
    phase: RunnerPhase
    steps: int
    reason: str
    step_limit_reached: bool = False
    waiting_for_human: bool = False


class BoundedTaskRunner:
    """Run a task to a deterministic completion condition within a finite step budget.

    The runner supplies orchestration only. The planner proposes actions, the worker
    enforces authorization and verification, the executor performs one authorized
    action, and the completion checker decides whether the objective is proven.
    """

    def __init__(
        self,
        state_manager: StateManager,
        runner_id: str,
        worker: BackgroundWorker,
        planner: TaskPlanner,
        executor: WorkerExecutor,
        completion_checker: CompletionChecker,
        *,
        max_steps: int = 32,
        max_observations: int = 64,
        max_repeated_observation: int = 2,
    ) -> None:
        if not runner_id.strip() or any(char in runner_id for char in "/\\"):
            raise ValueError("runner_id must be a non-empty path-safe identifier")
        if max_steps <= 0:
            raise ValueError("max_steps must be positive")
        if max_observations <= 0:
            raise ValueError("max_observations must be positive")
        if max_repeated_observation <= 0:
            raise ValueError("max_repeated_observation must be positive")

        self.state_manager = state_manager
        self.runner_id = runner_id
        self.worker = worker
        self.planner = planner
        self.executor = executor
        self.completion_checker = completion_checker
        self.max_steps = max_steps
        self.max_observations = max_observations
        self.max_repeated_observation = max_repeated_observation
        self.state_path = state_manager.ai_dir / f"task-runner-{runner_id}.json"
        self.lock = threading.RLock()
        self.state = self._load_or_initialize()
        self._observation_objects: list[Observation] = []

    def run(self) -> TaskRunResult:
        with self.lock:
            if self.state.phase == "completed":
                return self._result("task already completed")
            if self.state.phase in {"failed", "waiting_human", "paused"}:
                return self._result(self.state.last_error or f"runner is {self.state.phase}")

            worker_phase = self.worker.status().phase
            if worker_phase == "stopped":
                self.worker.start()
            elif worker_phase != "running":
                return self._sync_worker_state()

            self.state = self._replace(phase="running", last_error=None)
            self._persist()

            while self.state.steps < self.max_steps:
                worker_state = self.worker.status()
                if worker_state.phase != "running":
                    return self._sync_worker_state()

                try:
                    action = self.planner.plan(tuple(self._observation_objects))
                except Exception as exc:
                    return self._fail(f"planner failed: {exc}")

                if action is None:
                    return self._fail("planner did not provide a next action and completion was not proven")

                self.state = self._replace(last_action_id=action.action_id)
                self._persist()

                try:
                    observation = self.worker.step(action, self.executor, external_human_approval=False)
                except WorkerExecutionError as exc:
                    if self.worker.status().phase == "waiting_human":
                        self.state = self._replace(phase="waiting_human", last_error=str(exc))
                        self._persist()
                        return self._result("human approval required", waiting_for_human=True)
                    return self._fail(f"worker execution failed: {exc}")
                except Exception as exc:
                    return self._fail(f"worker step failed: {exc}")

                if observation is None:
                    return self._sync_worker_state()

                try:
                    self._record_observation(observation)
                except WorkerExecutionError as exc:
                    return self._fail(str(exc))

                self.state = self._replace(steps=self.state.steps + 1)
                self._persist()

                try:
                    decision = self.completion_checker.check(tuple(self._observation_objects))
                except Exception as exc:
                    return self._fail(f"completion checker failed: {exc}")

                if decision.status == "complete":
                    try:
                        self.worker.complete()
                    except WorkerExecutionError as exc:
                        return self._fail(f"worker could not enter completed state: {exc}")
                    self.state = self._replace(phase="completed", last_error=None)
                    self._persist()
                    return self._result(decision.reason)

                if decision.status == "failed":
                    return self._fail(decision.reason)

            self.state = self._replace(phase="running", last_error="maximum task-runner step budget reached")
            self._persist()
            return self._result("maximum task-runner step budget reached", step_limit_reached=True)

    def reset(self) -> TaskRunnerState:
        with self.lock:
            if self.worker.status().phase == "running":
                self.worker.stop("task runner reset")
            self._observation_objects.clear()
            self.state = TaskRunnerState(runner_id=self.runner_id)
            self._persist()
            return self.state

    def _record_observation(self, observation: Observation) -> None:
        fingerprint = observation.fingerprint()
        if self.state.observations and self.state.observations[-1] == fingerprint:
            repetitions = 1
            for previous in reversed(self.state.observations):
                if previous != fingerprint:
                    break
                repetitions += 1
            if repetitions >= self.max_repeated_observation:
                raise WorkerExecutionError("task runner detected repeated identical observations")

        self._observation_objects.append(observation)
        if len(self._observation_objects) > self.max_observations:
            del self._observation_objects[:-self.max_observations]
        fingerprints = tuple(item.fingerprint() for item in self._observation_objects)
        self.state = self._replace(observations=fingerprints)

    def _sync_worker_state(self) -> TaskRunResult:
        phase = self.worker.status().phase
        mapping: dict[WorkerPhase, RunnerPhase] = {
            "stopped": "stopped",
            "running": "running",
            "paused": "paused",
            "waiting_human": "waiting_human",
            "completed": "completed",
            "failed": "failed",
        }
        runner_phase = mapping[phase]
        self.state = self._replace(phase=runner_phase, last_error=self.worker.status().last_error)
        self._persist()
        return self._result(
            self.state.last_error or f"worker is {phase}",
            waiting_for_human=phase == "waiting_human",
        )

    def _fail(self, reason: str) -> TaskRunResult:
        if self.worker.status().phase == "running":
            self.worker.stop(reason)
        self.state = self._replace(phase="failed", last_error=reason)
        self._persist()
        return self._result(reason)

    def _result(
        self,
        reason: str,
        *,
        step_limit_reached: bool = False,
        waiting_for_human: bool = False,
    ) -> TaskRunResult:
        return TaskRunResult(
            phase=self.state.phase,
            steps=self.state.steps,
            reason=reason,
            step_limit_reached=step_limit_reached,
            waiting_for_human=waiting_for_human or self.state.phase == "waiting_human",
        )

    def _load_or_initialize(self) -> TaskRunnerState:
        if not self.state_path.exists():
            return TaskRunnerState(runner_id=self.runner_id)
        data = self.state_manager.read_json(self.state_path, None)
        if not isinstance(data, dict):
            raise StateCorruptionError("Invalid task runner state")
        return TaskRunnerState.from_dict(data)

    def _persist(self) -> None:
        self.state_manager.write_json(self.state_path, self.state.to_dict())

    def _replace(self, **changes: object) -> TaskRunnerState:
        data = self.state.to_dict()
        data.update(changes)
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        return TaskRunnerState.from_dict(data)


__all__ = [
    "BoundedTaskRunner",
    "CompletionChecker",
    "CompletionDecision",
    "CompletionStatus",
    "RunnerPhase",
    "TaskPlanner",
    "TaskRunResult",
    "TaskRunnerState",
]
