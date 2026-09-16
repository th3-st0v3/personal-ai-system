from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from automation.orchestrator.planner_schema import (
    HumanApprovalStatus,
    PlannerResult,
    ProposedStep,
)


def test_planner_result_covers_required_contract() -> None:
    result = PlannerResult(
        proposed_steps=[
            ProposedStep(
                step_id="inspect-login",
                description="Inspect the login implementation and current tests.",
            ),
            ProposedStep(
                step_id="repair-login",
                description="Implement the smallest compatible fix.",
            ),
        ],
        required_capabilities=[
            "repo.read",
            "repo.edit",
            "test.run",
        ],
        verification_requirements=[
            "Run the relevant automated tests.",
            "Verify the login flow succeeds.",
        ],
        blockers=[
            "Production credentials are unavailable.",
        ],
        human_approval_status="pending",
    )

    assert len(result.proposed_steps) == 2
    assert result.proposed_steps[0].step_id == "inspect-login"
    assert result.proposed_steps[1].description == (
        "Implement the smallest compatible fix."
    )
    assert result.required_capabilities == [
        "repo.read",
        "repo.edit",
        "test.run",
    ]
    assert result.verification_requirements == [
        "Run the relevant automated tests.",
        "Verify the login flow succeeds.",
    ]
    assert result.blockers == [
        "Production credentials are unavailable.",
    ]
    assert result.human_approval_status == "pending"


def test_proposed_step_supports_per_step_intent() -> None:
    step = ProposedStep(
        step_id="simulate-login",
        description="Run the login simulation.",
        required_capabilities=["run_simulation"],
        verification_requirements=["Inspect the simulation trace."],
    )

    assert step.required_capabilities == ["run_simulation"]
    assert step.verification_requirements == [
        "Inspect the simulation trace."
    ]


def test_planner_result_defaults_are_safe() -> None:
    result = PlannerResult()

    assert result.proposed_steps == []
    assert result.required_capabilities == []
    assert result.verification_requirements == []
    assert result.blockers == []
    assert result.human_approval_status == "not_required"


@pytest.mark.parametrize(
    "status",
    [
        "not_required",
        "pending",
        "approved",
        "rejected",
    ],
)
def test_human_approval_status_accepts_supported_values(
    status: HumanApprovalStatus,
) -> None:
    result = PlannerResult(
        human_approval_status=status,
    )

    assert result.human_approval_status == status


def test_human_approval_status_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        PlannerResult.model_validate(
            {
                "human_approval_status": "maybe",
            }
        )


def test_proposed_step_requires_nonempty_identity_and_description() -> None:
    with pytest.raises(ValidationError):
        ProposedStep(
            step_id="",
            description="Inspect the project.",
        )

    with pytest.raises(ValidationError):
        ProposedStep(
            step_id="inspect",
            description="",
        )


def test_planner_result_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        PlannerResult.model_validate(
            {
                "proposed_steps": [],
                "unexpected_field": "not allowed",
            }
        )


def test_planner_result_serializes_to_json() -> None:
    result = PlannerResult(
        proposed_steps=[
            ProposedStep(
                step_id="inspect",
                description="Inspect the repository.",
            )
        ],
        required_capabilities=["repo.read"],
        verification_requirements=["Repository state is understood."],
        blockers=[],
        human_approval_status="not_required",
    )

    payload = result.model_dump()

    assert payload["proposed_steps"][0]["step_id"] == "inspect"
    assert payload["required_capabilities"] == ["repo.read"]
    assert payload["verification_requirements"] == [
        "Repository state is understood."
    ]
    assert payload["blockers"] == []
    assert payload["human_approval_status"] == "not_required"

    json.dumps(payload)


def test_planner_result_json_schema_is_generated() -> None:
    schema = PlannerResult.model_json_schema()

    assert schema["title"] == "PlannerResult"
    assert "proposed_steps" in schema["properties"]
    assert "required_capabilities" in schema["properties"]
    assert "verification_requirements" in schema["properties"]
    assert "blockers" in schema["properties"]
    assert "human_approval_status" in schema["properties"]
    assert schema.get("additionalProperties") is False


def test_checked_in_planner_json_schema_matches_model() -> None:
    from pathlib import Path

    schema_path = Path(__file__).with_name(
        "planner_result.schema.json"
    )

    checked_in = json.loads(
        schema_path.read_text(encoding="utf-8")
    )

    generated = PlannerResult.model_json_schema()

    assert checked_in == generated
