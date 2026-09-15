from __future__ import annotations

from .context_schema import AgentRequest, ExecutionPolicy
from .models import CurrentTask


class Planner:
    """Prepare a provider-independent planning request without executing it."""

    def build_request(
        self,
        *,
        task: CurrentTask,
        execution_policy: ExecutionPolicy,
    ) -> AgentRequest:
        restrictions = [
            "Do not execute actions.",
            "Use the supplied ContextPackage as the source of project state.",
        ]

        if execution_policy.allowed_actions:
            restrictions.append(
                "Any action proposed must be checked against the execution policy."
            )
        else:
            restrictions.append(
                "No execution actions are currently authorized."
            )

        return AgentRequest(
            task=task.objective,
            expected_output=[
                "proposed plan",
                "required verification",
                "identified blockers",
            ],
            restrictions=restrictions,
        )
