from __future__ import annotations

from typing import Final


TERMINAL_OPERATION_STATUSES: Final[frozenset[str]] = frozenset({"completed", "failed", "cancelled"})

_ALLOWED_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "queued": frozenset({"claimed", "failed", "cancelled"}),
    "claimed": frozenset({"generating", "completed", "failed", "queued", "cancelled"}),
    "generating": frozenset({"generating", "completed", "failed", "queued", "cancelled"}),
    "completed": frozenset(),
    "failed": frozenset(),
}


class InvalidOperationTransition(ValueError):
    """Raised when an operation attempts an illegal status transition."""


def validate_transition(current: str, target: str) -> None:
    allowed = _ALLOWED_TRANSITIONS.get(current)
    if allowed is None:
        raise InvalidOperationTransition(f"Unknown operation status: {current!r}")
    if target not in allowed:
        raise InvalidOperationTransition(
            f"Unsupported operation transition: {current!r} -> {target!r}"
        )


def validate_status(status: str) -> None:
    if status not in _ALLOWED_TRANSITIONS:
        raise InvalidOperationTransition(f"Unknown operation status: {status!r}")


