from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Literal, Mapping, TypeAlias


ActionKind: TypeAlias = Literal[
    "observe",
    "ai_new_session",
    "ai_select_reasoning",
    "ai_submit_prompt",
    "ai_read_response",
    "ide_read",
    "ide_diagnostics",
    "ide_search",
    "ide_command",
    "github_read",
    "github_ui",
    "web_search",
    "web_read",
    "desktop_ui",
]
ActionRisk: TypeAlias = Literal["safe", "approval_required", "denied"]
CompletionState: TypeAlias = Literal[
    "generating",
    "quiet",
    "complete",
    "interrupted",
    "error",
    "timeout",
    "unknown",
]
ControlPhase: TypeAlias = Literal[
    "idle",
    "observing",
    "planning",
    "awaiting_authorization",
    "executing",
    "verifying",
    "paused",
    "completed",
    "failed",
]

SAFE_ACTIONS: frozenset[ActionKind] = frozenset(
    {
        "observe",
        "ai_new_session",
        "ai_select_reasoning",
        "ai_submit_prompt",
        "ai_read_response",
        "ide_read",
        "ide_diagnostics",
        "ide_search",
        "github_read",
        "web_search",
        "web_read",
    }
)
APPROVAL_ACTIONS: frozenset[ActionKind] = frozenset(
    {"ide_command", "github_ui", "desktop_ui"}
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Session:
    session_id: str
    task_id: str
    project: str
    allowed_applications: tuple[str, ...] = ()
    workspace_root: str | None = None
    max_duration_seconds: int = 3600
    background: bool = False
    phase: ControlPhase = "idle"

    def __post_init__(self) -> None:
        if not self.session_id.strip() or not self.task_id.strip():
            raise ValueError("session_id and task_id are required")
        if self.max_duration_seconds <= 0:
            raise ValueError("max_duration_seconds must be positive")


@dataclass(frozen=True)
class ActionProposal:
    action_id: str
    session_id: str
    target: str
    action: ActionKind
    parameters: Mapping[str, Any] = field(default_factory=dict)
    reason: str = ""
    risk: ActionRisk | None = None

    def classify_risk(self) -> ActionRisk:
        if self.action in SAFE_ACTIONS:
            return "safe"
        if self.action in APPROVAL_ACTIONS:
            return "approval_required"
        return "denied"

    def effective_risk(self) -> ActionRisk:
        classified = self.classify_risk()
        if self.risk is not None and self.risk != classified:
            raise ValueError(
                f"declared risk {self.risk!r} does not match action policy {classified!r}"
            )
        return classified


@dataclass(frozen=True)
class Observation:
    observation_id: str
    session_id: str
    source: str
    kind: str
    data: Mapping[str, Any] = field(default_factory=dict)
    captured_at: str = field(default_factory=utc_now)

    def fingerprint(self) -> str:
        payload = {
            "observation_id": self.observation_id,
            "session_id": self.session_id,
            "source": self.source,
            "kind": self.kind,
            "data": dict(self.data),
            "captured_at": self.captured_at,
        }
        return sha256(repr(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AIResponse:
    response_id: str
    session_id: str
    provider: str
    operation_id: str | None
    text: str
    completion: CompletionState
    response_available: bool = False
    chat_url: str | None = None
    model: str | None = None
    reasoning_mode: str | None = None

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise ValueError("provider is required")
        if self.completion == "complete" and not (
            self.response_available or self.text.strip()
        ):
            raise ValueError(
                "a complete AI response must either contain text or explicitly mark response availability"
            )


@dataclass(frozen=True)
class ContextPackage:
    context_id: str
    session_id: str
    objective: str
    evidence: tuple[Mapping[str, Any], ...] = ()
    source_fingerprints: tuple[str, ...] = ()

    def fingerprint(self) -> str:
        payload = {
            "context_id": self.context_id,
            "session_id": self.session_id,
            "objective": self.objective,
            "evidence": [dict(item) for item in self.evidence],
            "source_fingerprints": list(self.source_fingerprints),
        }
        return sha256(repr(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ControlEvent:
    event_id: str
    session_id: str
    event_type: str
    timestamp: str = field(default_factory=utc_now)
    action_id: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
