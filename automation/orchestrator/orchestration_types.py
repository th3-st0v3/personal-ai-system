from __future__ import annotations

from typing import Literal, TypeAlias


TaskPhase: TypeAlias = Literal[
    "selection",
    "precheck",
    "research",
    "context_ready",
    "planning",
    "awaiting_approval",
    "executing",
    "testing",
    "browser_verification",
    "diagnosis",
    "replanning",
    "completed",
    "failed",
    "handoff",
]

ProjectPhase: TypeAlias = Literal["idle"] | TaskPhase


TERMINAL_PHASES: frozenset[TaskPhase] = frozenset(
    {
        "completed",
        "failed",
        "handoff",
    }
)
