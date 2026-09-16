from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from src import policy

from .planner_schema import HumanApprovalStatus, PlannerResult


CAPABILITY_TO_ACTION: dict[str, str] = {
    "read_project": "read_project",
    "ingest_source": "ingest_source",
    "run_calculation": "run_calculation",
    "run_simulation": "run_simulation",
    "modify_project_data": "modify_project_data",
    "execute_code": "execute_code",
    "remote_execution": "remote_execution",
    "external_api_cost": "external_api_cost",
}


@dataclass(frozen=True)
class AuthorizationDecision:
    allowed: bool
    required_actions: tuple[str, ...]
    denied_actions: tuple[str, ...]
    unknown_capabilities: tuple[str, ...]
    human_approval_status: HumanApprovalStatus
    human_approval_required: bool
    reason: str


def authorize_plan(
    connection: sqlite3.Connection,
    *,
    actor_id: str,
    plan: PlannerResult,
    human_approval_granted: bool = False,
) -> AuthorizationDecision:
    """Evaluate a plan without executing actions or trusting model approval claims.

    Human approval is an external control-plane input. The planner's
    ``human_approval_status`` is retained as metadata but cannot authorize
    execution by itself.
    """
    capabilities = list(plan.required_capabilities)
    for step in plan.proposed_steps:
        capabilities.extend(step.required_capabilities)

    required_actions: list[str] = []
    denied_actions: list[str] = []
    unknown_capabilities: list[str] = []

    for capability in dict.fromkeys(capabilities):
        action = CAPABILITY_TO_ACTION.get(capability)
        if action is None:
            unknown_capabilities.append(capability)
            continue
        if action not in required_actions:
            required_actions.append(action)
        if not policy.allowed(connection, actor_id, action):
            denied_actions.append(action)

    human_approval_required = any(
        action not in policy.DEFAULT_SAFE_ACTIONS
        for action in required_actions
    )

    if unknown_capabilities:
        reason = (
            "Plan contains capabilities with no defined policy mapping: "
            + ", ".join(unknown_capabilities)
        )
        return AuthorizationDecision(
            allowed=False,
            required_actions=tuple(required_actions),
            denied_actions=tuple(dict.fromkeys(denied_actions)),
            unknown_capabilities=tuple(unknown_capabilities),
            human_approval_status=plan.human_approval_status,
            human_approval_required=human_approval_required,
            reason=reason,
        )

    if denied_actions:
        return AuthorizationDecision(
            allowed=False,
            required_actions=tuple(required_actions),
            denied_actions=tuple(dict.fromkeys(denied_actions)),
            unknown_capabilities=(),
            human_approval_status=plan.human_approval_status,
            human_approval_required=human_approval_required,
            reason="One or more required actions are not authorized.",
        )

    if human_approval_required and not human_approval_granted:
        return AuthorizationDecision(
            allowed=False,
            required_actions=tuple(required_actions),
            denied_actions=(),
            unknown_capabilities=(),
            human_approval_status=plan.human_approval_status,
            human_approval_required=True,
            reason="Human approval is required before consequential execution.",
        )

    return AuthorizationDecision(
        allowed=True,
        required_actions=tuple(required_actions),
        denied_actions=(),
        unknown_capabilities=(),
        human_approval_status=plan.human_approval_status,
        human_approval_required=human_approval_required,
        reason="All required actions are authorized and required human approval is granted.",
    )
