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
    reason: str


def authorize_plan(
    connection: sqlite3.Connection,
    *,
    actor_id: str,
    plan: PlannerResult,
) -> AuthorizationDecision:
    """Evaluate a plan against explicit policy without executing any action."""
    required_actions: list[str] = []
    denied_actions: list[str] = []
    unknown_capabilities: list[str] = []

    for capability in dict.fromkeys(plan.required_capabilities):
        action = CAPABILITY_TO_ACTION.get(capability)
        if action is None:
            unknown_capabilities.append(capability)
            continue
        required_actions.append(action)
        if not policy.allowed(connection, actor_id, action):
            denied_actions.append(action)

    if unknown_capabilities:
        reason = (
            "Plan contains capabilities with no defined policy mapping: "
            + ", ".join(unknown_capabilities)
        )
        return AuthorizationDecision(
            allowed=False,
            required_actions=tuple(required_actions),
            denied_actions=tuple(denied_actions),
            unknown_capabilities=tuple(unknown_capabilities),
            human_approval_status=plan.human_approval_status,
            reason=reason,
        )

    if denied_actions:
        return AuthorizationDecision(
            allowed=False,
            required_actions=tuple(required_actions),
            denied_actions=tuple(denied_actions),
            unknown_capabilities=(),
            human_approval_status=plan.human_approval_status,
            reason="One or more required actions are not authorized.",
        )

    return AuthorizationDecision(
        allowed=True,
        required_actions=tuple(required_actions),
        denied_actions=(),
        unknown_capabilities=(),
        human_approval_status=plan.human_approval_status,
        reason="All required capabilities map to currently authorized actions.",
    )
