from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from .orchestration_types import ProjectPhase, TaskPhase


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ProjectState:
    project: str = "personal-ai-system"
    status: str = "idle"
    current_feature: str | None = None
    current_phase: ProjectPhase = "idle"
    current_task_id: str | None = None
    current_branch: str | None = None
    last_successful_commit: str | None = None
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CurrentTask:
    task_id: str
    feature: str
    objective: str
    status: str = "queued"
    phase: TaskPhase = "selection"
    attempt: int = 0

    implementation_attempts: int = 0
    test_repair_attempts: int = 0
    browser_repair_attempts: int = 0
    ux_repair_attempts: int = 0
    security_repair_attempts: int = 0

    chat_operation_id: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FeatureStatus:
    feature: str

    implementation: str = "not_run"
    unit_tests: str = "not_run"
    integration_tests: str = "not_run"
    browser_tests: str = "not_run"
    ux_review: str = "not_run"
    security_review: str = "not_run"

    status: str = "not_started"
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ChatOperation:
    operation_id: str
    operation_type: str
    prompt: str

    status: str = "queued"

    chat_url: str | None = None
    error: str | None = None

    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
