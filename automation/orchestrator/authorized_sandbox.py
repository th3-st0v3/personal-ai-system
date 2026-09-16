from __future__ import annotations

import sqlite3

from src import policy

from .sandbox_adapter import SandboxAdapter
from .sandbox_schema import SandboxRequest, SandboxResult


class AuthorizedSandboxExecutor:
    """Single policy boundary for sandbox workloads."""

    def __init__(self, connection: sqlite3.Connection, adapter: SandboxAdapter) -> None:
        self.connection = connection
        self.adapter = adapter

    def execute(self, request: SandboxRequest, *, human_approval_granted: bool = False) -> SandboxResult:
        if not human_approval_granted:
            return self._rejected(
                request,
                "Human approval is required before consequential execution.",
            )

        try:
            policy.require(self.connection, request.actor_id, "execute_code")
        except (PermissionError, ValueError) as exc:
            return self._rejected(request, str(exc))

        result = self.adapter.execute(request)
        if result.request_id != request.request_id:
            raise ValueError("Sandbox adapter returned the wrong request_id.")
        if result.task_id != request.task_id:
            raise ValueError("Sandbox adapter returned the wrong task_id.")
        if result.step_id != request.step_id:
            raise ValueError("Sandbox adapter returned the wrong step_id.")
        return result

    @staticmethod
    def _rejected(request: SandboxRequest, error: str) -> SandboxResult:
        return SandboxResult(
            request_id=request.request_id,
            task_id=request.task_id,
            step_id=request.step_id,
            status="rejected",
            error=error,
        )
