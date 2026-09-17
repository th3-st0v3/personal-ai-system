from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from automation.computer_use.controller import ControlPlane
from automation.computer_use.contracts import ActionProposal, Observation, Session
from automation.orchestrator.background_worker import BackgroundWorker, WorkerExecutionError
from automation.orchestrator.state import StateManager
from automation.orchestrator.verification_telemetry import VerificationTelemetry
from automation.orchestrator.worker_verification import WorkerVerification


class RecordingExecutor:
    def __init__(self) -> None:
        self.actions: list[ActionProposal] = []

    def execute(self, action: ActionProposal) -> Observation:
        self.actions.append(action)
        return Observation(
            observation_id=f"obs-{len(self.actions)}",
            session_id=action.session_id,
            source="test-executor",
            kind="result",
            data={"action_id": action.action_id},
        )


class MismatchedObservationExecutor(RecordingExecutor):
    def execute(self, action: ActionProposal) -> Observation:
        self.actions.append(action)
        return Observation(
            observation_id=f"obs-{len(self.actions)}",
            session_id="other-session",
            source="test-executor",
            kind="result",
            data={"action_id": action.action_id},
        )


class RejectingVerifier:
    def verify(self, action: ActionProposal, observation: Observation) -> WorkerVerification:
        return WorkerVerification(
            status="failed",
            checks=("custom check",),
            failures=("custom verifier rejected observation",),
        )


def make_worker(
    tmp_path,
    *,
    background: bool = True,
    max_duration_seconds: int = 60,
    telemetry: bool = False,
    verifier=None,
):
    session = Session(
        session_id="session-1",
        task_id="task-1",
        project="test-project",
        workspace_root=str(tmp_path),
        max_duration_seconds=max_duration_seconds,
        background=background,
    )
    control = ControlPlane(session)
    state_manager = StateManager(tmp_path / ".ai")
    worker_telemetry = VerificationTelemetry(state_manager) if telemetry else None
    return BackgroundWorker(state_manager, "worker-1", control, worker_telemetry, verifier), control


def safe_action() -> ActionProposal:
    return ActionProposal("a1", "session-1", "test", "github_read")


def approval_action() -> ActionProposal:
    return ActionProposal("a2", "session-1", "test", "desktop_ui")


def test_background_worker_requires_background_session(tmp_path) -> None:
    with pytest.raises(ValueError, match="background worker"):
        make_worker(tmp_path, background=False)


def test_start_persists_running_state(tmp_path) -> None:
    worker, _ = make_worker(tmp_path)
    state = worker.start()
    assert state.phase == "running"
    assert state.deadline_at is not None
    assert worker.status().phase == "running"


def test_pause_and_resume_are_persisted(tmp_path) -> None:
    worker, _ = make_worker(tmp_path)
    worker.start()
    paused = worker.pause("operator requested pause")
    assert paused.phase == "paused"
    assert paused.pause_reason == "operator requested pause"
    resumed = worker.resume()
    assert resumed.phase == "running"
    assert resumed.pause_reason is None


def test_approval_required_action_waits_for_human_and_is_not_executed(tmp_path) -> None:
    worker, _ = make_worker(tmp_path)
    executor = RecordingExecutor()
    worker.start()
    result = worker.step(approval_action(), executor)
    assert result is None
    assert worker.status().phase == "waiting_human"
    assert executor.actions == []
    assert worker.status().current_action is not None


def test_waiting_human_requires_explicit_approval_to_resume(tmp_path) -> None:
    worker, _ = make_worker(tmp_path)
    executor = RecordingExecutor()
    worker.start()
    worker.step(approval_action(), executor)

    with pytest.raises(WorkerExecutionError, match="human approval"):
        worker.resume()

    resumed = worker.resume(human_approval=True)
    assert resumed.phase == "running"
    assert resumed.approved_action_id == "a2"

    result = worker.step(approval_action(), executor)
    assert result is not None
    assert len(executor.actions) == 1


def test_approved_action_cannot_be_retargeted(tmp_path) -> None:
    worker, _ = make_worker(tmp_path)
    executor = RecordingExecutor()
    worker.start()
    worker.step(approval_action(), executor)
    worker.resume(human_approval=True)

    different = ActionProposal("different", "session-1", "test", "desktop_ui")
    with pytest.raises(WorkerExecutionError, match="does not match"):
        worker.step(different, executor)
    assert executor.actions == []


def test_approved_action_executes_and_clears_current_action(tmp_path) -> None:
    worker, _ = make_worker(tmp_path)
    executor = RecordingExecutor()
    worker.start()
    result = worker.step(approval_action(), executor, external_human_approval=True)
    assert result is not None
    assert result.kind == "result"
    assert len(executor.actions) == 1
    assert executor.actions[0].action_id == "a2"
    assert worker.status().phase == "running"
    assert worker.status().current_action is None


def test_safe_action_executes_without_external_approval(tmp_path) -> None:
    worker, _ = make_worker(tmp_path)
    executor = RecordingExecutor()
    worker.start()
    assert worker.step(safe_action(), executor) is not None
    assert len(executor.actions) == 1
    assert executor.actions[0].action_id == "a1"


def test_worker_records_execution_observation_when_telemetry_enabled(tmp_path) -> None:
    worker, _ = make_worker(tmp_path, telemetry=True)
    executor = RecordingExecutor()
    worker.start()

    observation = worker.step(safe_action(), executor)

    assert observation is not None
    records = worker.telemetry.load() if worker.telemetry is not None else []
    assert len(records) == 1
    assert records[0].event_type == "worker_verification"
    assert records[0].status == "verified"
    assert records[0].action_id == "a1"
    assert records[0].task_id == "task-1"
    assert records[0].session_id == "session-1"
    assert records[0].evidence_fingerprint == observation.fingerprint()


def test_approval_wait_does_not_emit_execution_telemetry(tmp_path) -> None:
    worker, _ = make_worker(tmp_path, telemetry=True)
    executor = RecordingExecutor()
    worker.start()

    assert worker.step(approval_action(), executor) is None

    records = worker.telemetry.load() if worker.telemetry is not None else []
    assert records == []
    assert executor.actions == []


def test_post_execution_verification_failure_stops_worker_and_records_failure(tmp_path) -> None:
    worker, _ = make_worker(tmp_path, telemetry=True)
    executor = MismatchedObservationExecutor()
    worker.start()

    with pytest.raises(WorkerExecutionError, match="post-execution verification failed"):
        worker.step(safe_action(), executor)

    state = worker.status()
    assert len(executor.actions) == 1
    assert state.phase == "failed"
    assert state.current_action is None
    assert state.last_error is not None
    assert "observation session does not match action session" in state.last_error
    records = worker.telemetry.load() if worker.telemetry is not None else []
    assert len(records) == 1
    assert records[0].event_type == "worker_verification"
    assert records[0].status == "failed"
    assert records[0].action_id == "a1"


def test_worker_accepts_replaceable_verifier(tmp_path) -> None:
    worker, _ = make_worker(tmp_path, telemetry=True, verifier=RejectingVerifier())
    executor = RecordingExecutor()
    worker.start()

    with pytest.raises(WorkerExecutionError, match="post-execution verification failed"):
        worker.step(safe_action(), executor)

    assert len(executor.actions) == 1
    assert worker.status().phase == "failed"
    records = worker.telemetry.load() if worker.telemetry is not None else []
    assert records[0].status == "failed"
    verification = records[0].details.get("verification") if isinstance(records[0].details, dict) else None
    assert isinstance(verification, dict)
    assert verification.get("failures") == ["custom verifier rejected observation"]


def test_action_from_different_session_is_rejected(tmp_path) -> None:
    worker, _ = make_worker(tmp_path)
    executor = RecordingExecutor()
    worker.start()
    action = ActionProposal("a3", "other-session", "test", "github_read")
    with pytest.raises(ValueError, match="different control session"):
        worker.step(action, executor)
    assert executor.actions == []


def test_worker_restart_requires_explicit_resume(tmp_path) -> None:
    worker, _ = make_worker(tmp_path)
    worker.start()
    worker.step(safe_action(), RecordingExecutor())

    restarted, _ = make_worker(tmp_path)
    recovered = restarted.recover()
    assert recovered.phase == "paused"
    assert recovered.recovery_required is True
    assert recovered.pause_reason == "worker restarted; explicit resume required"

    with pytest.raises(WorkerExecutionError, match="cannot execute"):
        restarted.step(safe_action(), RecordingExecutor())

    resumed = restarted.resume()
    assert resumed.phase == "running"


def test_expired_session_fails_closed(tmp_path) -> None:
    worker, _ = make_worker(tmp_path, max_duration_seconds=1)
    worker.start()
    expired = worker.state.to_dict()
    expired["deadline_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    worker.state_manager.write_json(worker.state_path, expired)

    worker = BackgroundWorker(StateManager(tmp_path / ".ai"), "worker-1", worker.control_plane)
    with pytest.raises(WorkerExecutionError, match="session duration expired"):
        worker.step(safe_action(), RecordingExecutor())
    assert worker.status().phase == "failed"
    assert worker.status().last_error == "session duration expired"


def test_corrupted_worker_state_fails_closed(tmp_path) -> None:
    worker, _ = make_worker(tmp_path)
    worker.start()
    worker.state_path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Corrupt state file"):
        BackgroundWorker(StateManager(tmp_path / ".ai"), "worker-1", worker.control_plane)


def test_stop_is_idempotent_and_terminal(tmp_path) -> None:
    worker, _ = make_worker(tmp_path)
    worker.start()
    first = worker.stop("operator stop")
    second = worker.stop("repeat stop")
    assert first.phase == "stopped"
    assert second.phase == "stopped"
    with pytest.raises(WorkerExecutionError, match="cannot resume"):
        worker.resume()


def test_complete_requires_running_phase(tmp_path) -> None:
    worker, _ = make_worker(tmp_path)
    with pytest.raises(WorkerExecutionError, match="cannot complete"):
        worker.complete()
