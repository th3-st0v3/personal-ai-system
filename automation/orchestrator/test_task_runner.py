from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import pytest

from automation.computer_use.contracts import ActionProposal, Observation, Session
from automation.computer_use.controller import ControlPlane
from automation.orchestrator.background_worker import BackgroundWorker
from automation.orchestrator.state import StateManager
from automation.orchestrator.task_runner import BoundedTaskRunner, CompletionDecision


class RecordingExecutor:
    def __init__(self) -> None:
        self.actions: list[str] = []
        self.observations: list[Observation] = []

    def execute(self, action: ActionProposal) -> Observation:
        self.actions.append(action.action_id)
        observation = Observation(
            observation_id=f"obs-{len(self.actions)}",
            session_id=action.session_id,
            source="test-executor",
            kind="result",
            data={"action_id": action.action_id},
        )
        self.observations.append(observation)
        return observation


@dataclass
class SequencePlanner:
    actions: list[ActionProposal]

    def plan(self, observations: Sequence[Observation]) -> ActionProposal | None:
        if not self.actions:
            return None
        return self.actions.pop(0)


class CountChecker:
    def __init__(self, required: int) -> None:
        self.required = required

    def check(self, observations: Sequence[Observation]) -> CompletionDecision:
        if len(observations) >= self.required:
            return CompletionDecision("complete", "required evidence observed")
        return CompletionDecision("incomplete", "more evidence required")


def make_worker(tmp_path):
    session = Session(
        session_id="session-1",
        task_id="task-1",
        project="test-project",
        workspace_root=str(tmp_path),
        background=True,
    )
    control = ControlPlane(session)
    state_manager = StateManager(tmp_path / ".ai")
    return BackgroundWorker(state_manager, "worker-1", control), state_manager


def action(action_id: str = "a1") -> ActionProposal:
    return ActionProposal(action_id, "session-1", "test", "github_read")


def test_runner_executes_until_deterministic_completion(tmp_path) -> None:
    worker, state_manager = make_worker(tmp_path)
    executor = RecordingExecutor()
    runner = BoundedTaskRunner(
        state_manager,
        "runner-1",
        worker,
        SequencePlanner([action("a1"), action("a2")]),
        executor,
        CountChecker(2),
        max_steps=4,
    )

    result = runner.run()

    assert result.phase == "completed"
    assert result.steps == 2
    assert result.step_limit_reached is False
    assert executor.actions == ["a1", "a2"]
    assert worker.status().phase == "completed"


def test_runner_never_treats_planner_exhaustion_as_completion(tmp_path) -> None:
    worker, state_manager = make_worker(tmp_path)
    runner = BoundedTaskRunner(
        state_manager,
        "runner-1",
        worker,
        SequencePlanner([]),
        RecordingExecutor(),
        CountChecker(1),
    )

    result = runner.run()

    assert result.phase == "failed"
    assert "completion was not proven" in result.reason
    assert worker.status().phase == "stopped"


def test_runner_stops_at_step_budget_without_claiming_completion(tmp_path) -> None:
    worker, state_manager = make_worker(tmp_path)
    runner = BoundedTaskRunner(
        state_manager,
        "runner-1",
        worker,
        SequencePlanner([action("a1"), action("a2")]),
        RecordingExecutor(),
        CountChecker(3),
        max_steps=2,
    )

    result = runner.run()

    assert result.phase == "running"
    assert result.step_limit_reached is True
    assert result.steps == 2
    assert worker.status().phase == "running"


def test_runner_halts_for_human_approval(tmp_path) -> None:
    worker, state_manager = make_worker(tmp_path)
    executor = RecordingExecutor()
    approval_action = ActionProposal("a2", "session-1", "test", "desktop_ui")
    runner = BoundedTaskRunner(
        state_manager,
        "runner-1",
        worker,
        SequencePlanner([approval_action]),
        executor,
        CountChecker(1),
    )

    result = runner.run()

    assert result.phase == "waiting_human"
    assert result.waiting_for_human is True
    assert executor.actions == []
    assert worker.status().phase == "waiting_human"


def test_runner_approval_resume_is_bound_to_pending_action(tmp_path) -> None:
    worker, state_manager = make_worker(tmp_path)
    executor = RecordingExecutor()
    approval_action = ActionProposal("a2", "session-1", "test", "desktop_ui")
    runner = BoundedTaskRunner(
        state_manager,
        "runner-1",
        worker,
        SequencePlanner([approval_action]),
        executor,
        CountChecker(1),
    )

    result = runner.run()
    assert result.phase == "waiting_human"

    resumed = runner.approve_pending_action()
    assert resumed.phase == "running"
    assert worker.status().approved_action_id == "a2"

    completed = runner.run()
    assert completed.phase == "completed"
    assert executor.actions == ["a2"]


def test_runner_restart_with_running_state_requires_rehydration(tmp_path) -> None:
    worker, state_manager = make_worker(tmp_path)
    executor = RecordingExecutor()
    runner = BoundedTaskRunner(
        state_manager,
        "runner-1",
        worker,
        SequencePlanner([action("a1"), action("a2")]),
        executor,
        CountChecker(3),
        max_steps=1,
    )
    result = runner.run()
    assert result.step_limit_reached is True
    assert len(executor.observations) == 1

    restarted = BoundedTaskRunner(
        state_manager,
        "runner-1",
        worker,
        SequencePlanner([action("a2")]),
        RecordingExecutor(),
        CountChecker(2),
        max_steps=2,
    )
    assert restarted.state.recovery_required is True
    blocked = restarted.run()
    assert blocked.phase == "paused"
    assert "rehydration" in blocked.reason

    restarted.mark_rehydrated(executor.observations)
    assert restarted.state.recovery_required is False

    resumed = restarted.run()
    assert resumed.phase == "completed"
    assert resumed.steps == 2


def test_runner_persists_completed_state_and_rejects_corrupt_state(tmp_path) -> None:
    worker, state_manager = make_worker(tmp_path)
    runner = BoundedTaskRunner(
        state_manager,
        "runner-1",
        worker,
        SequencePlanner([action("a1")]),
        RecordingExecutor(),
        CountChecker(1),
    )
    runner.run()

    restarted = BoundedTaskRunner(
        state_manager,
        "runner-1",
        worker,
        SequencePlanner([]),
        RecordingExecutor(),
        CountChecker(1),
    )
    assert restarted.state.phase == "completed"

    runner.state_path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Corrupt state file"):
        BoundedTaskRunner(
            state_manager,
            "runner-1",
            worker,
            SequencePlanner([]),
            RecordingExecutor(),
            CountChecker(1),
        )
