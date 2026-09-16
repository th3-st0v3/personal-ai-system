from __future__ import annotations

import sqlite3

from src import policy

from .execution_adapter import ExecutionAdapter
from .execution_schema import ExecutionRequest, ExecutionResult


class AuthorizedExecutor:
    """Single execution boundary that checks policy before delegating."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        adapter: ExecutionAdapter,
    ) -> None:
        self.connection = connection
        self.adapter = adapter

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        """Authorize and execute one request, never bypassing policy.require()."""
        if request.action not in policy.DEFAULT_SAFE_ACTIONS and not request.human_approval_granted:
            return ExecutionResult(
                request_id=request.request_id,
                task_id=request.task_id,
                step_id=request.step_id,
                action=request.action,
                status="rejected",
                error="Human approval is required before consequential execution.",
            )

        try:
            policy.require(
                self.connection,
                request.actor_id,
                request.action,
            )
        except (PermissionError, ValueError) as exc:
            return ExecutionResult(
                request_id=request.request_id,
                task_id=request.task_id,
                step_id=request.step_id,
                action=request.action,
                status="rejected",
                error=str(exc),
            )

        try:
            result = self.adapter.execute(request)
        except Exception as exc:
            return ExecutionResult(
                request_id=request.request_id,
                task_id=request.task_id,
                step_id=request.step_id,
                action=request.action,
                status="failed",
                error=str(exc),
            )

        if result.request_id != request.request_id:
            raise ValueError("Execution adapter returned the wrong request_id.")
        if result.task_id != request.task_id:
            raise ValueError("Execution adapter returned the wrong task_id.")
        if result.step_id != request.step_id:
            raise ValueError("Execution adapter returned the wrong step_id.")
        if result.action != request.action:
            raise ValueError("Execution adapter returned the wrong action.")

        return result
