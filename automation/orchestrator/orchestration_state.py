from __future__ import annotations

from collections.abc import Mapping

from .models import CurrentTask, ProjectState, utc_now
from .orchestration_types import TERMINAL_PHASES, TaskPhase


class InvalidPhaseTransition(ValueError):
    """Raised when a task attempts an unsupported lifecycle transition."""


_ALLOWED_TRANSITIONS: Mapping[TaskPhase, frozenset[TaskPhase]] = {
    "selection": frozenset({"precheck", "handoff", "failed"}),
    "precheck": frozenset({"research", "context_ready", "handoff", "failed"}),
    "research": frozenset({"context_ready", "diagnosis", "handoff", "failed"}),
    "context_ready": frozenset({"planning", "handoff", "failed"}),
    "planning": frozenset({"awaiting_approval", "executing", "testing", "handoff", "failed"}),
    "awaiting_approval": frozenset({"executing", "handoff", "failed"}),
    "executing": frozenset({"testing", "diagnosis", "handoff", "failed"}),
    "testing": frozenset({
        "browser_verification",
        "diagnosis",
        "completed",
        "handoff",
        "failed",
    }),
    "browser_verification": frozenset({
        "completed",
        "diagnosis",
        "handoff",
        "failed",
    }),
    "diagnosis": frozenset({"replanning", "handoff", "failed"}),
    "replanning": frozenset({"planning", "executing", "handoff", "failed"}),
    "completed": frozenset(),
    "failed": frozenset(),
    "handoff": frozenset(),
}


def allowed_transitions(phase: TaskPhase) -> frozenset[TaskPhase]:
    """Return the immutable set of phases reachable from ``phase``."""
    return _ALLOWED_TRANSITIONS[phase]


def can_transition(current: TaskPhase, target: TaskPhase) -> bool:
    """Return whether the lifecycle permits ``current`` -> ``target``."""
    return target in allowed_transitions(current)


def validate_transition(current: TaskPhase, target: TaskPhase) -> None:
    """Raise ``InvalidPhaseTransition`` when a transition is not permitted."""
    if current == target:
        raise InvalidPhaseTransition(
            f"Phase is already '{current}'."
        )

    if current in TERMINAL_PHASES:
        raise InvalidPhaseTransition(
            f"Terminal phase '{current}' cannot transition to '{target}'."
        )

    if not can_transition(current, target):
        raise InvalidPhaseTransition(
            f"Unsupported phase transition: '{current}' -> '{target}'."
        )


def transition(
    task: CurrentTask,
    project_state: ProjectState,
    target: TaskPhase,
) -> None:
    """Apply one validated lifecycle transition to task and project state."""
    current = task.phase
    validate_transition(current, target)

    timestamp = utc_now()
    task.phase = target
    task.updated_at = timestamp
    project_state.current_phase = target
    project_state.current_task_id = task.task_id
    project_state.updated_at = timestamp

    if target == "completed":
        task.status = "completed"
        project_state.status = "idle"
    elif target == "failed":
        task.status = "failed"
        project_state.status = "idle"
    elif target == "handoff":
        task.status = "handoff"
        project_state.status = "idle"
    elif target == "awaiting_approval":
        task.status = "waiting_approval"
        project_state.status = "waiting_approval"
    else:
        task.status = "running"
        project_state.status = "running"
