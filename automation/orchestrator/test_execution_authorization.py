from __future__ import annotations

import sqlite3

from automation.orchestrator.execution_authorization import authorize_plan
from automation.orchestrator.planner_schema import PlannerResult, ProposedStep
from src import policy


def make_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    policy.initialize(connection)
    return connection


def test_empty_plan_is_authorized() -> None:
    connection = make_connection()

    decision = authorize_plan(
        connection,
        actor_id="user-1",
        plan=PlannerResult(),
    )

    assert decision.allowed is True
    assert decision.required_actions == ()
    assert decision.denied_actions == ()
    assert decision.unknown_capabilities == ()
    assert decision.human_approval_required is False


def test_default_safe_capability_is_authorized() -> None:
    connection = make_connection()

    decision = authorize_plan(
        connection,
        actor_id="user-1",
        plan=PlannerResult(
            required_capabilities=["run_simulation"],
        ),
    )

    assert decision.allowed is True
    assert decision.required_actions == ("run_simulation",)
    assert decision.human_approval_required is False
    assert decision.human_approval_status == "not_required"


def test_consequential_capability_requires_external_approval() -> None:
    connection = make_connection()
    policy.grant(connection, "user-1", "execute_code")

    decision = authorize_plan(
        connection,
        actor_id="user-1",
        plan=PlannerResult(
            proposed_steps=[
                ProposedStep(
                    step_id="step-1",
                    description="Run the approved local test command.",
                )
            ],
            required_capabilities=["execute_code"],
            human_approval_status="approved",
        ),
    )

    assert decision.allowed is False
    assert decision.required_actions == ("execute_code",)
    assert decision.denied_actions == ()
    assert decision.human_approval_required is True
    assert decision.human_approval_status == "approved"
    assert "Human approval is required" in decision.reason


def test_external_approval_allows_consequential_capability() -> None:
    connection = make_connection()
    policy.grant(connection, "user-1", "execute_code")

    decision = authorize_plan(
        connection,
        actor_id="user-1",
        plan=PlannerResult(
            required_capabilities=["execute_code"],
            human_approval_status="pending",
        ),
        human_approval_granted=True,
    )

    assert decision.allowed is True
    assert decision.required_actions == ("execute_code",)
    assert decision.human_approval_required is True
    assert decision.human_approval_status == "pending"


def test_unauthorized_capability_is_denied() -> None:
    connection = make_connection()

    decision = authorize_plan(
        connection,
        actor_id="user-1",
        plan=PlannerResult(
            required_capabilities=["execute_code"],
        ),
        human_approval_granted=True,
    )

    assert decision.allowed is False
    assert decision.required_actions == ("execute_code",)
    assert decision.denied_actions == ("execute_code",)
    assert decision.human_approval_required is True


def test_unknown_capability_fails_closed() -> None:
    connection = make_connection()

    decision = authorize_plan(
        connection,
        actor_id="user-1",
        plan=PlannerResult(
            required_capabilities=["filesystem.write.unrestricted"],
        ),
        human_approval_granted=True,
    )

    assert decision.allowed is False
    assert decision.unknown_capabilities == (
        "filesystem.write.unrestricted",
    )
    assert "no defined policy mapping" in decision.reason


def test_duplicate_capabilities_are_evaluated_once() -> None:
    connection = make_connection()

    decision = authorize_plan(
        connection,
        actor_id="user-1",
        plan=PlannerResult(
            required_capabilities=[
                "run_simulation",
                "run_simulation",
            ],
        ),
    )

    assert decision.allowed is True
    assert decision.required_actions == ("run_simulation",)


def test_per_step_capability_is_authorized() -> None:
    connection = make_connection()

    decision = authorize_plan(
        connection,
        actor_id="user-1",
        plan=PlannerResult(
            proposed_steps=[
                ProposedStep(
                    step_id="simulate",
                    description="Run the simulation.",
                    required_capabilities=["run_simulation"],
                    verification_requirements=["Inspect the simulation trace."],
                )
            ],
        ),
    )

    assert decision.allowed is True
    assert decision.required_actions == ("run_simulation",)
