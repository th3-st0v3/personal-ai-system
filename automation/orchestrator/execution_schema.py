from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator

from .context_schema import PASIModel


ExecutionStatus = Literal[
    "executed",
    "rejected",
    "failed",
]


class ExecutionRequest(PASIModel):
    request_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    step_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1, max_length=128)
    action: str = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)
    human_approval_granted: bool = False
    approval_reference: str | None = None

    @field_validator("actor_id")
    @classmethod
    def reject_multiline_actor_id(cls, value: str) -> str:
        if any(character in value for character in "\r\n"):
            raise ValueError("actor_id must not contain newlines")
        return value


class ExecutionResult(PASIModel):
    request_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    step_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    status: ExecutionStatus
    output: Any | None = None
    error: str | None = None


__all__ = ["ExecutionRequest", "ExecutionResult", "ExecutionStatus"]
