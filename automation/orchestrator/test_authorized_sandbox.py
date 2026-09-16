from __future__ import annotations

import sqlite3
from pathlib import Path

from automation.orchestrator.authorized_sandbox import AuthorizedSandboxExecutor
from automation.orchestrator.sandbox_schema import SandboxRequest, SandboxResult
from src import policy


class RecordingSandbox:
    def __init__(self) -> None:
        self.requests: list[SandboxRequest] = []

    def execute(self, request: SandboxRequest) -> SandboxResult:
        self.requests.append(request)
        return SandboxResult(
            request_id=request.request_id,
            task_id=request.task_id,
            step_id=request.step_id,
            status="executed",
            return_code=0,
        )


def make_executor() -> tuple[sqlite3.Connection, RecordingSandbox, AuthorizedSandboxExecutor]:
    connection = sqlite3.connect(":memory:")
    policy.initialize(connection)
    adapter = RecordingSandbox()
    return connection, adapter, AuthorizedSandboxExecutor(connection, adapter)


def make_request() -> SandboxRequest:
    return SandboxRequest(
        request_id="req-1",
        task_id="task-1",
        step_id="step-1",
        actor_id="user-1",
        argv=("python", "-c", "print('ok')"),
    )


def test_sandbox_requires_external_human_approval() -> None:
    _, adapter, executor = make_executor()

    result = executor.execute(make_request())

    assert result.status == "rejected"
    assert "Human approval is required" in (result.error or "")
    assert adapter.requests == []


def test_sandbox_requires_explicit_execute_code_permission() -> None:
    _, adapter, executor = make_executor()

    result = executor.execute(make_request(), human_approval_granted=True)

    assert result.status == "rejected"
    assert "Permission denied" in (result.error or "")
    assert adapter.requests == []


def test_approved_sandbox_request_reaches_adapter() -> None:
    connection, adapter, executor = make_executor()
    policy.grant(connection, "user-1", "execute_code")

    result = executor.execute(make_request(), human_approval_granted=True)

    assert result.status == "executed"
    assert len(adapter.requests) == 1


def test_authorized_boundary_preserves_adapter_identity(tmp_path: Path) -> None:
    connection, adapter, executor = make_executor()
    policy.grant(connection, "user-1", "execute_code")
    request = make_request()

    result = executor.execute(request, human_approval_granted=True)

    assert result.request_id == request.request_id
    assert result.task_id == request.task_id
    assert result.step_id == request.step_id
    assert tmp_path.is_dir()
