from __future__ import annotations

from automation.computer_use.controller import ControlPlane
from automation.computer_use.contracts import ActionProposal, Observation, Session
from automation.orchestrator.background_worker import BackgroundWorker
from automation.orchestrator.state import StateManager
from automation.orchestrator.verification_telemetry import VerificationTelemetry


class RecordingExecutor:
    def __init__(self) -> None:
        self.actions: list[ActionProposal] = []

    def execute(self, action: ActionProposal) -> Observation:
        self.actions.append(action)
        return Observation(
            observation_id=f"obs-{len(self.actions)}",
            session_id=action.session_id,
            source="telemetry-test-executor",
            kind="result",
            data={"action_id": action.action_id},
        )


def make_worker(tmp_path):
    state_manager = StateManager(tmp_path / ".ai")
    session = Session(
        session_id="session-telemetry",
        task_id="task-telemetry",
        project="test-project",
        workspace_root=str(tmp_path),
        max_duration_seconds=60,
        background=True,
    )
    telemetry = VerificationTelemetry(state_manager, max_records=32)
    return BackgroundWorker(
        state_manager,
        "worker-telemetry",
        ControlPlane(session),
        telemetry,
    ), telemetry


def test_worker_records_execution_evidence(tmp_path):
    worker, telemetry = make_worker(tmp_path)
    executor = RecordingExecutor()
    worker.start()
    observation = worker.step(
        ActionProposal("action-1", "session-telemetry", "test", "github_read"),
        executor,
    )

    assert observation is not None
    records = telemetry.load()
    assert [record.event_type for record in records] == [
        "worker_started",
        "action_execution",
    ]
    assert records[-1].status == "executed"
    assert records[-1].action_id == "action-1"
    assert records[-1].evidence_fingerprint == observation.fingerprint()
    assert records[-1].details["worker_id"] == "worker-telemetry"


def test_worker_records_human_approval_boundary(tmp_path):
    worker, telemetry = make_worker(tmp_path)
    executor = RecordingExecutor()
    worker.start()
    result = worker.step(
        ActionProposal("action-2", "session-telemetry", "test", "desktop_ui"),
        executor,
    )

    assert result is None
    records = telemetry.load()
    assert records[-1].event_type == "action_authorization"
    assert records[-1].status == "waiting_human"
    assert records[-1].action_id == "action-2"
    assert executor.actions == []
