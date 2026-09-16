from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


SandboxStatus = Literal["executed", "rejected", "failed"]


@dataclass(frozen=True)
class SandboxRequest:
    """Bounded workload description for a future isolated execution runtime."""

    request_id: str
    task_id: str
    step_id: str
    actor_id: str
    argv: tuple[str, ...]
    cwd: str = "."
    timeout_seconds: float = 30.0
    max_output_bytes: int = 64 * 1024

    def __post_init__(self) -> None:
        if not self.request_id or "\n" in self.request_id or "\r" in self.request_id:
            raise ValueError("request_id must be a short non-empty identifier")
        if not self.task_id or not self.step_id:
            raise ValueError("task_id and step_id must be non-empty")
        if not self.actor_id or "\n" in self.actor_id or "\r" in self.actor_id:
            raise ValueError("actor_id must be a short non-empty identifier")
        if not self.argv or any(not isinstance(arg, str) for arg in self.argv):
            raise ValueError("argv must contain at least one string")
        if any("\x00" in arg for arg in self.argv):
            raise ValueError("argv cannot contain NUL bytes")
        if "\x00" in self.cwd or self.cwd.startswith("/"):
            raise ValueError("cwd must be a relative path inside the sandbox root")
        if self.timeout_seconds <= 0 or self.timeout_seconds > 300:
            raise ValueError("timeout_seconds must be between 0 and 300")
        if self.max_output_bytes <= 0 or self.max_output_bytes > 1024 * 1024:
            raise ValueError("max_output_bytes must be between 1 and 1048576")


@dataclass(frozen=True)
class SandboxResult:
    """Structured outcome returned by a sandbox runtime."""

    request_id: str
    task_id: str
    step_id: str
    status: SandboxStatus
    return_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    error: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)
