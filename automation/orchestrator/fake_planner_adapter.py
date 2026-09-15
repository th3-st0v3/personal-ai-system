from __future__ import annotations

from .context_schema import AgentRequest, ContextPackage
from .planner_adapter import PlannerAdapter
from .planner_schema import PlannerResult, ProposedStep


class FakePlannerAdapter:
    """Deterministic in-process implementation of the planner contract."""

    def __init__(
        self,
        *,
        proposed_steps: list[ProposedStep] | None = None,
        required_capabilities: list[str] | None = None,
        verification_requirements: list[str] | None = None,
        blockers: list[str] | None = None,
    ) -> None:
        self._proposed_steps = list(proposed_steps or [])
        self._required_capabilities = list(required_capabilities or [])
        self._verification_requirements = list(
            verification_requirements or []
        )
        self._blockers = list(blockers or [])
        self.requests: list[tuple[AgentRequest, ContextPackage]] = []

    def plan(
        self,
        request: AgentRequest,
        context: ContextPackage,
    ) -> PlannerResult:
        """Return deterministic canned planning data for the supplied request."""
        self.requests.append((request, context))

        return PlannerResult(
            proposed_steps=list(self._proposed_steps),
            required_capabilities=list(self._required_capabilities),
            verification_requirements=list(
                self._verification_requirements
            ),
            blockers=list(self._blockers),
        )


__all__ = ["FakePlannerAdapter"]
