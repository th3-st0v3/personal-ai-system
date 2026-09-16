from __future__ import annotations

import sqlite3

import pytest

from automation.orchestrator.authorized_executor import AuthorizedExecutor
from automation.orchestrator.execution_schema import ExecutionRequest, ExecutionResult
from src import policy


class RecordingAdapter:
    def __init__(self) -> None:
        self.requests: list[ExecutionRequest] = []

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        self.requests.append(request)
        return ExecutionResult(
            request_id=request.request_id,
            task_id=request.task_id,
            step_id=request.step_id,
            action=request.action,
            status="executed",
            output={"ok": True},
        )


def make_executor() -> tuple[sqlite3.Connection, RecordingAdapter, AuthorizedExecutor]:
    connection = sqlite3.connect(":memory:")
    policy.initialize(connection)
    adapter = RecordingAdapter()
    return connection, adapter, AuthorizedExecutor(connection, adapter)


def make_request(
    *,
    action: str,
    human_approval_granted: bool = False,
) -> ExecutionRequest:
    return ExecutionRequest(
        request_id="req-1",
        task_id="task-1",
        step_id="step-1",
        actor_id="user-1",
        action=action,
        human_approval_granted=human_approval_granted,
    )


def test_safe_action_reaches_adapter() -> None:
    _, adapter, executor = make_executor()

    result = executor.execute(make_request(action="run_simulation"))

    assert result.status == "executed"
    assert result.output == {"ok": True}
    assert len(adapter.requests) == 1


def test_consequential_action_is_rejected_without_external_approval() -> None:
    _, adapter, executor = make_executor()

    result = executor.execute(make_request(action="execute_code"))

    assert result.status == "rejected"
    assert "Human approval is required" in (result.error or "")
    assert adapter.requests == []


def test_consequential_action_still_requires_policy_permission() -> None:
    _, adapter, executor = make_executor()

    result = executor.execute(
        make_request(
            action="execute_code",
            human_approval_granted=True,
        )
    )

    assert result.status == "rejected"
    assert "Permission denied" in (result.error or "")
    assert adapter.requests == []


def test_granted_permission_and_external_approval_reach_adapter() -> None:
    connection, adapter, executor = make_executor()
    policy.grant(connection, "user-1", "execute_code")

    result = executor.execute(
        make_request(
            action="execute_code",
            human_approval_granted=True,
        )
    )

    assert result.status == "executed"
    assert len(adapter.requests) == 1


def test_unknown_action_is_rejected() -> None:
    _, adapter, executor = make_executor()

    result = executor.execute(make_request(action="not_a_real_action"))

    assert result.status == "rejected"
    assert "Unknown action" in (result.error or "")
    assert adapter.requests == []


def test_adapter_failure_becomes_structured_failed_result() -> None:
    class FailingAdapter:
        def execute(self, request: ExecutionRequest) -> ExecutionResult:
            raise RuntimeError("adapter failed")

    connection = sqlite3.connect(":memory:")
    policy.initialize(connection)
    executor = AuthorizedExecutor(connection, FailingAdapter())

    result = executor.execute(
        make_request(action="run_simulation")
    )

    assert result.status == "failed"
    assert result.error == "adapter failed"


def test_adapter_cannot_return_a_different_request_identity() -> None:
    class WrongAdapter:
        def execute(self, request: ExecutionRequest) -> ExecutionResult:
            return ExecutionResult(
                request_id="wrong",
                task_id=request.task_id,
                step_id=request.step_id,
                action=request.action,
                status="executed",
            )

    connection = sqlite3.connect(":memory:")
    policy.initialize(connection)
    executor = AuthorizedExecutor(connection, WrongAdapter())

    with pytest.raises(ValueError, match="wrong request_id"):
        executor.execute(make_request(action="run_simulation"))
