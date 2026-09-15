from __future__ import annotations

from automation.orchestrator.context_schema import ExecutionPolicy
from automation.orchestrator.models import CurrentTask
from automation.orchestrator.planner import Planner


def make_task() -> CurrentTask:
    return CurrentTask(
        task_id="task_test_001",
        feature="orchestrator",
        objective="Make the login button work.",
    )


def test_planner_builds_provider_independent_request() -> None:
    request = Planner().build_request(
        task=make_task(),
        execution_policy=ExecutionPolicy(),
    )

    assert request.task == "Make the login button work."
    assert request.expected_output == [
        "proposed plan",
        "required verification",
        "identified blockers",
    ]
    assert "Do not execute actions." in request.restrictions
    assert "No execution actions are currently authorized." in request.restrictions


def test_planner_reflects_authorized_action_boundary() -> None:
    request = Planner().build_request(
        task=make_task(),
        execution_policy=ExecutionPolicy(
            allowed_actions=["repo_read", "test_run"],
        ),
    )

    assert (
        "Any action proposed must be checked against the execution policy."
        in request.restrictions
    )
    assert "No execution actions are currently authorized." not in request.restrictions
