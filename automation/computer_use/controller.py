from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .contracts import ActionProposal, ActionRisk, ControlEvent, ControlPhase, Session


_ALLOWED_TRANSITIONS: dict[ControlPhase, frozenset[ControlPhase]] = {
    "idle": frozenset({"observing", "planning", "paused", "failed"}),
    "observing": frozenset({"planning", "executing", "verifying", "failed", "paused"}),
    "planning": frozenset({"awaiting_authorization", "executing", "failed", "paused"}),
    "awaiting_authorization": frozenset({"executing", "paused", "failed"}),
    "executing": frozenset({"observing", "verifying", "completed", "failed", "paused"}),
    "verifying": frozenset({"observing", "planning", "completed", "failed", "paused"}),
    "paused": frozenset({"observing", "planning", "failed"}),
    "completed": frozenset(),
    "failed": frozenset(),
}


class InvalidControlTransition(ValueError):
    """Raised when the control plane attempts an unsupported phase change."""


class AuthorizationGateway(Protocol):
    """Existing PASI policy/human-approval boundary adapted to computer actions."""

    def authorize(
        self,
        action: ActionProposal,
        *,
        external_human_approval: bool = False,
    ) -> ActionRisk: ...


@dataclass(frozen=True)
class AuthorizationResult:
    action_id: str
    risk: ActionRisk
    allowed: bool
    requires_human_approval: bool
    reason: str


class DefaultAuthorizationGateway:
    """Fail-closed scaffold; production integration should delegate to PASI policy."""

    def authorize(
        self,
        action: ActionProposal,
        *,
        external_human_approval: bool = False,
    ) -> ActionRisk:
        risk = action.effective_risk()
        if risk == "safe":
            return risk
        if risk == "approval_required" and external_human_approval:
            return risk
        if risk == "denied":
            return risk
        return risk


class ControlPlane:
    """Small deterministic state machine for the computer-use control loop.

    It deliberately does not perform UI automation. Concrete adapters are invoked by
    a later execution layer after this controller has produced an authorization result.
    """

    def __init__(self, session: Session):
        self.session = session
        self.phase: ControlPhase = session.phase
        self.events: list[ControlEvent] = []

    def transition(self, target: ControlPhase) -> None:
        if target not in _ALLOWED_TRANSITIONS[self.phase]:
            raise InvalidControlTransition(
                f"Unsupported control transition: {self.phase!r} -> {target!r}"
            )
        self.phase = target

    def authorize(
        self,
        action: ActionProposal,
        gateway: AuthorizationGateway | None = None,
        *,
        external_human_approval: bool = False,
    ) -> AuthorizationResult:
        if action.session_id != self.session.session_id:
            raise ValueError("action belongs to a different control session")

        selected_gateway = gateway or DefaultAuthorizationGateway()
        risk = action.effective_risk()

        if risk == "approval_required" and not external_human_approval:
            if self.phase != "awaiting_authorization":
                self.transition("awaiting_authorization")
            selected_gateway.authorize(action, external_human_approval=False)
            result = AuthorizationResult(
                action_id=action.action_id,
                risk=risk,
                allowed=False,
                requires_human_approval=True,
                reason="external human approval is required",
            )
        elif risk == "denied":
            result = AuthorizationResult(
                action_id=action.action_id,
                risk=risk,
                allowed=False,
                requires_human_approval=False,
                reason="action is outside the computer-use capability boundary",
            )
        else:
            selected_gateway.authorize(
                action,
                external_human_approval=external_human_approval,
            )
            result = AuthorizationResult(
                action_id=action.action_id,
                risk=risk,
                allowed=True,
                requires_human_approval=False,
                reason="action is permitted by the computer-use capability boundary",
            )

        return result

    def record_event(self, event: ControlEvent) -> None:
        if event.session_id != self.session.session_id:
            raise ValueError("event belongs to a different control session")
        self.events.append(event)
