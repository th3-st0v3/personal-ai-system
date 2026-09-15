from __future__ import annotations

from typing import Protocol

from .context_schema import AgentRequest, ContextPackage
from .planner_schema import PlannerResult


class PlannerAdapter(Protocol):
    """Provider-independent boundary for turning context into a plan."""

    def plan(
        self,
        request: AgentRequest,
        context: ContextPackage,
    ) -> PlannerResult:
        """Produce a validated provider-independent planning result."""
        ...
