from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Protocol

from automation.computer_use.controller import AuthorizationGateway, ControlPlane
from automation.computer_use.contracts import ActionProposal, Observation, Session
from .state import StateCorruptionError, StateManager


WorkerPhase = Literal[
    "stopped",
    "running",
    "paused",
    "waiting_human",
    "completed",
    "failed",
]


class WorkerExecutionError(RuntimeError):
    """Raised when the persistent worker cannot safely continue."""


class WorkerExecutor(Protocol):
    """Provider-neutral execution seam for one already-authorized action."""

    def execute(self, action: ActionProposal) -> Observation: ...


@dataclass(frozen=True)
class WorkerState:
    worker_id: str
    session: Session
    phase: WorkerPhase = "stopped"
    current_action: dict[str, Any] | None = None
    approved_action_id: str | None = None
    started_at: str | None = None
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    deadline_at: str | None = None
    pause_reason: str | None = None
    last_error: str | None = None
    last_observation_fingerprint: str | None = None
    recovery_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkerState":
        worker_id = data.get("worker_id")
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise StateCorruptionError("Invalid worker state shape: worker_id is required")

        session_data = data.get("session")
        if not isinstance(session_data, dict):
            raise StateCorruptionError("Invalid worker state shape: session is missing")
        allowed_applications = session_data.get("allowed_applications", ())
        if isinstance(allowed_applications, list):
            session_data = dict(session_data)
            session_data["allowed_applications"] = tuple(allowed_applications)
        try:
            session = Session(**session_data)
        except (TypeError, ValueError) as exc:
            raise StateCorruptionError("Invalid worker state shape: invalid session") from exc

        phase = data.get("phase", "stopped")
        if phase not in {"stopped", "running", "paused", "waiting_human", "completed", "failed"}:
            raise StateCorruptionError("Invalid worker state shape: unknown phase")

        recovery_required = data.get("recovery_required", False)
        if not isinstance(recovery_required, bool):
            raise StateCorruptionError("Invalid worker state shape: recovery_required must be boolean")

        current_action = data.get("current_action")
        if current_action is not None and not isinstance(current_action, dict):
            raise StateCorruptionError("Invalid worker state shape: current_action must be an object")

        approved_action_id = data.get("approved_action_id")
        if approved_action_id is not None and not isinstance(approved_action_id, str):
            raise StateCorruptionError("Invalid worker state shape: approved_action_id must be a string")

        return cls(
            worker_id=worker_id,
            session=session,
            phase=phase,
            current_action=current_action,
            approved_action_id=approved_action_id,
            started_at=data.get("started_at") if isinstance(data.get("started_at"), str) else None,
            updated_at=str(data.get("updated_at", datetime.now(timezone.utc).isoformat())),
            deadline_at=data.get("deadline_at") if isinstance(data.get("deadline_at"), str) else None,
            pause_reason=data.get("pause_reason") if isinstance(data.get("pause_reason"), str) else None,
            last_error=data.get("last_error") if isinstance(data.get("last_error"), str) else None,
            last_observation_fingerprint=(
                data.get("last_observation_fingerprint")
                if isinstance(data.get("last_observation_fingerprint"), str)
                else None
            ),
            recovery_required=recovery_required,
        )


class BackgroundWorker:
    """Persistent, pauseable, provider-neutral execution coordinator.

    The worker never chooses tools or bypasses authorization. A caller supplies
    an executor and the existing ControlPlane authorization boundary. Process
    restart while work is active always requires an explicit resume.
    """

    def __init__(
        self,
        state_manager: StateManager,
        worker_id: str,
        control_plane: ControlPlane,
    ) -> None:
        if not worker_id.strip() or any(char in worker_id for char in "/\\"):
            raise ValueError("worker_id must be a non-empty path-safe identifier")
        if control_plane.session.background is not True:
            raise ValueError("background worker requires Session(background=True)")
        self.state_manager = state_manager
        self.worker_id = worker_id
        self.control_plane = control_plane
        self.state_path = state_manager.ai_dir / f"worker-{worker_id}.json"
        self.lock = threading.RLock()
        self.state = self._load_or_initialize()

    def start(self) -> WorkerState:
        with self.lock:
            if self.state.phase not in {"stopped"}:
                raise WorkerExecutionError(f"worker cannot start from phase {self.state.phase!r}")
            now = datetime.now(timezone.utc)
            self.state = WorkerState(
                worker_id=self.worker_id,
                session=self.control_plane.session,
                phase="running",
                started_at=now.isoformat(),
                updated_at=now.isoformat(),
                deadline_at=(now + timedelta(seconds=self.control_plane.session.max_duration_seconds)).isoformat(),
            )
            self._persist()
            return self.state

    def pause(self, reason: str = "paused by operator") -> WorkerState:
        with self.lock:
            if self.state.phase not in {"running", "waiting_human"}:
                raise WorkerExecutionError(f"worker cannot pause from phase {self.state.phase!r}")
            self.state = self._replace(phase="paused", pause_reason=reason, recovery_required=False)
            self._persist()
            return self.state

    def resume(self, *, human_approval: bool = False) -> WorkerState:
        with self.lock:
            if self.state.phase == "waiting_human":
                if not human_approval:
                    raise WorkerExecutionError("human approval is required before resuming")
                action_id = self.state.current_action.get("action_id") if self.state.current_action else None
                if not isinstance(action_id, str) or not action_id:
                    raise WorkerExecutionError("waiting-human state has no resumable action")
                if self.state.approved_action_id not in {None, action_id}:
                    raise WorkerExecutionError("approval is bound to a different action")
                self.state = self._replace(approved_action_id=action_id)
            elif self.state.phase != "paused":
                raise WorkerExecutionError(f"worker cannot resume from phase {self.state.phase!r}")
            self._ensure_not_expired()
            self.state = self._replace(phase="running", pause_reason=None, recovery_required=False)
            self._persist()
            return self.state

    def stop(self, reason: str = "stopped by operator") -> WorkerState:
        with self.lock:
            if self.state.phase in {"completed", "failed", "stopped"}:
                return self.state
            self.state = self._replace(
                phase="stopped",
                pause_reason=reason,
                current_action=None,
                approved_action_id=None,
            )
            self._persist()
            return self.state

    def complete(self) -> WorkerState:
        with self.lock:
            if self.state.phase != "running":
                raise WorkerExecutionError(f"worker cannot complete from phase {self.state.phase!r}")
            self.state = self._replace(
                phase="completed",
                current_action=None,
                approved_action_id=None,
                pause_reason=None,
            )
            self._persist()
            return self.state

    def step(
        self,
        action: ActionProposal,
        executor: WorkerExecutor,
        gateway: AuthorizationGateway | None = None,
        *,
        external_human_approval: bool = False,
    ) -> Observation | None:
        with self.lock:
            if self.state.phase != "running":
                raise WorkerExecutionError(f"worker cannot execute from phase {self.state.phase!r}")
            self._ensure_not_expired()
            if action.session_id != self.control_plane.session.session_id:
                raise ValueError("action belongs to a different control session")

            if self.state.approved_action_id is not None:
                if action.action_id != self.state.approved_action_id:
                    raise WorkerExecutionError("approved action does not match the requested action")
                external_human_approval = True

            self.state = self._replace(
                current_action=asdict(action),
                pause_reason=None,
            )
            self._persist()

            try:
                authorization = self.control_plane.authorize(
                    action,
                    gateway,
                    external_human_approval=external_human_approval,
                )
                if not authorization.allowed:
                    if authorization.requires_human_approval:
                        self.state = self._replace(
                            phase="waiting_human",
                            pause_reason=authorization.reason,
                            recovery_required=False,
                        )
                    else:
                        self.state = self._replace(
                            phase="failed",
                            current_action=None,
                            approved_action_id=None,
                            last_error=authorization.reason,
                        )
                    self._persist()
                    return None

                observation = executor.execute(action)
                self.state = self._replace(
                    phase="running",
                    current_action=None,
                    approved_action_id=None,
                    last_error=None,
                    last_observation_fingerprint=observation.fingerprint(),
                )
                self._persist()
                return observation
            except Exception as exc:
                self.state = self._replace(
                    phase="failed",
                    current_action=None,
                    approved_action_id=None,
                    last_error=str(exc),
                )
                self._persist()
                raise

    def recover(self) -> WorkerState:
        """Load persisted state and require explicit resume after an interruption."""
        with self.lock:
            state = self._read_persisted()
            if state.phase == "running":
                state = WorkerState(
                    worker_id=state.worker_id,
                    session=state.session,
                    phase="paused",
                    current_action=state.current_action,
                    approved_action_id=None,
                    started_at=state.started_at,
                    updated_at=datetime.now(timezone.utc).isoformat(),
                    deadline_at=state.deadline_at,
                    pause_reason="worker restarted; explicit resume required",
                    last_error=state.last_error,
                    last_observation_fingerprint=state.last_observation_fingerprint,
                    recovery_required=True,
                )
                self.state = state
                self._persist()
            else:
                self.state = state
            return self.state

    def status(self) -> WorkerState:
        with self.lock:
            if self.state.phase == "running" and self._expired():
                self.state = self._replace(
                    phase="failed",
                    current_action=None,
                    approved_action_id=None,
                    last_error="session duration expired",
                )
                self._persist()
            return self.state

    def _load_or_initialize(self) -> WorkerState:
        if not self.state_path.exists():
            return WorkerState(worker_id=self.worker_id, session=self.control_plane.session)
        return self._read_persisted()

    def _read_persisted(self) -> WorkerState:
        data = self.state_manager.read_json(self.state_path, None)
        if not isinstance(data, dict):
            raise StateCorruptionError("Invalid worker state shape")
        state = WorkerState.from_dict(data)
        if state.worker_id != self.worker_id:
            raise StateCorruptionError("Worker state belongs to a different worker")
        if state.session.session_id != self.control_plane.session.session_id:
            raise StateCorruptionError("Worker state belongs to a different session")
        return state

    def _persist(self) -> None:
        self.state_manager.write_json(self.state_path, self.state.to_dict())

    def _replace(self, **changes: Any) -> WorkerState:
        data = self.state.to_dict()
        data.update(changes)
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        return WorkerState.from_dict(data)

    def _expired(self) -> bool:
        if self.state.deadline_at is None:
            return False
        try:
            deadline = datetime.fromisoformat(self.state.deadline_at)
        except ValueError as exc:
            raise StateCorruptionError("Invalid worker state shape: deadline_at is invalid") from exc
        if deadline.tzinfo is None:
            raise StateCorruptionError("Invalid worker state shape: deadline_at must include timezone")
        return datetime.now(timezone.utc) >= deadline

    def _ensure_not_expired(self) -> None:
        if self._expired():
            self.state = self._replace(
                phase="failed",
                current_action=None,
                approved_action_id=None,
                last_error="session duration expired",
            )
            self._persist()
            raise WorkerExecutionError("session duration expired")


__all__ = [
    "BackgroundWorker",
    "WorkerExecutionError",
    "WorkerExecutor",
    "WorkerPhase",
    "WorkerState",
]
