from __future__ import annotations

from typing import Protocol

from .execution_schema import ExecutionRequest, ExecutionResult


class ExecutionAdapter(Protocol):
    """Provider-specific execution surface behind the PASI authorization gate."""

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        """Execute one already-authorized request."""
        ...
