from __future__ import annotations

import pytest

from automation.orchestrator.models import CurrentTask, ProjectState
from automation.orchestrator.orchestration_state import (
    InvalidPhaseTransition,
    allowed_transitions,
    can_transition,
    transition,
    validate_transition,
)


def make_state() -> tuple[CurrentTask, ProjectState]:
    task = CurrentTask(
        task_id="task-1",
        feature="login",
        objective="Make the login button work.",
        phase="selection",
    )
    project = ProjectState(
        current_task_id=task.task_id,
        current_phase=task.phase,
    )
    return task, project


def test_selection_can_enter_precheck() -> None:
    assert can_transition("selection", "precheck") is True
    assert "precheck" in allowed_transitions("selection")


def test_illegal_transition_is_rejected() -> None:
    with pytest.raises(InvalidPhaseTransition):
        validate_transition("selection", "executing")


def test_terminal_phase_cannot_transition() -> None:
    with pytest.raises(InvalidPhaseTransition):
        validate_transition("completed", "planning")


def test_same_phase_is_rejected() -> None:
    with pytest.raises(InvalidPhaseTransition):
        validate_transition("testing", "testing")


def test_transition_updates_task_and_project_state() -> None:
    task, project = make_state()

    transition(task, project, "precheck")

    assert task.phase == "precheck"
    assert task.status == "running"
    assert project.current_phase == "precheck"
    assert project.current_task_id == task.task_id
    assert project.status == "running"
    assert task.updated_at == project.updated_at


def test_approval_transition_marks_waiting_state() -> None:
    task, project = make_state()
    transition(task, project, "precheck")
    transition(task, project, "context_ready")
    transition(task, project, "planning")
    transition(task, project, "awaiting_approval")

    assert task.phase == "awaiting_approval"
    assert task.status == "waiting_approval"
    assert project.current_phase == "awaiting_approval"
    assert project.status == "waiting_approval"


def test_completed_transition_is_terminal() -> None:
    task, project = make_state()
    transition(task, project, "precheck")
    transition(task, project, "context_ready")
    transition(task, project, "planning")
    transition(task, project, "executing")
    transition(task, project, "testing")
    transition(task, project, "completed")

    assert task.phase == "completed"
    assert task.status == "completed"
    assert project.current_phase == "completed"
    assert project.status == "idle"

    with pytest.raises(InvalidPhaseTransition):
        transition(task, project, "planning")


def test_failure_transition_is_terminal() -> None:
    task, project = make_state()
    transition(task, project, "precheck")
    transition(task, project, "failed")

    assert task.phase == "failed"
    assert task.status == "failed"
    assert project.current_phase == "failed"
    assert project.status == "idle"


def test_handoff_transition_is_terminal() -> None:
    task, project = make_state()
    transition(task, project, "precheck")
    transition(task, project, "handoff")

    assert task.phase == "handoff"
    assert task.status == "handoff"
    assert project.current_phase == "handoff"
    assert project.status == "idle"
