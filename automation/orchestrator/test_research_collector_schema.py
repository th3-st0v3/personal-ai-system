import json
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from automation.orchestrator.research_collector_schema import (
    EvidenceRequirement,
    ResearchQuestion,
    ResearchRequest,
    ResearchResult,
    ResearchSourceType,
)
from automation.orchestrator.research_schema import ResearchObservation

def test_research_question_captures_required_question() -> None:
    question = ResearchQuestion(
        question_id="settings-persistence",
        question="How does the settings choice persist after reload?",
        required=True,
    )

    assert question.question_id == "settings-persistence"
    assert question.required is True


def test_research_request_captures_research_scope() -> None:
    request = ResearchRequest(
        objective=(
            "Evaluate settings patterns across AI, engineering, "
            "and educational products."
        ),
        questions=[
            ResearchQuestion(
                question_id="ai-settings",
                question="How do AI products organize settings?",
            ),
            ResearchQuestion(
                question_id="simulation-settings",
                question="How do simulators separate configuration from runs?",
            ),
        ],
        preferred_source_types=[
            "web",
            "browser",
            "documentation",
        ],
        evidence_requirement="multiple_sources",
        max_sources=20,
        constraints=[
            "Prefer current observable behavior.",
            "Do not treat inferred backend behavior as confirmed fact.",
        ],
    )

    assert len(request.questions) == 2
    assert request.preferred_source_types == [
        "web",
        "browser",
        "documentation",
    ]
    assert request.evidence_requirement == "multiple_sources"
    assert request.max_sources == 20
    assert len(request.constraints) == 2


def test_research_request_has_safe_defaults() -> None:
    request = ResearchRequest(
        objective="Study simulation workflows."
    )

    assert request.questions == []
    assert request.preferred_source_types == []
    assert request.evidence_requirement == "any"
    assert request.max_sources == 10
    assert request.constraints == []


def test_research_result_captures_findings_and_gaps() -> None:
    result = ResearchResult(
        objective="Study simulation workflows.",
        sources_considered=[
            "source:simulator-docs",
            "source:simulator-ui",
        ],
        unanswered_questions=[
            "Whether runs are persisted server-side.",
        ],
        evidence_quality="good",
    )

    assert result.objective == "Study simulation workflows."
    assert len(result.sources_considered) == 2
    assert len(result.unanswered_questions) == 1
    assert result.evidence_quality == "good"


def test_research_result_can_carry_observations() -> None:
    observation = ResearchObservation(
        observation_id="obs-1",
        subject="Simulator",
        aspect="workflow",
        statement="Inputs are configured before execution.",
        source_ref="source:simulator-ui",
    )

    result = ResearchResult(
        objective="Study simulation workflows.",
        observations=[observation],
    )

    assert result.observations[0].observation_id == "obs-1"


@pytest.mark.parametrize(
    "source_type",
    [
        "web",
        "browser",
        "documentation",
        "github",
        "database",
        "file",
        "other",
    ],
)
def test_research_source_type_is_constrained(
    source_type: ResearchSourceType,
) -> None:
    request = ResearchRequest(
        objective="Research source types.",
        preferred_source_types=[source_type],
    )

    assert request.preferred_source_types == [source_type]


@pytest.mark.parametrize(
    "requirement",
    [
        "any",
        "documented",
        "direct",
        "multiple_sources",
    ],
)
def test_evidence_requirement_is_constrained(
    requirement: EvidenceRequirement,
) -> None:
    request = ResearchRequest(
        objective="Research evidence.",
        evidence_requirement=requirement,
    )

    assert request.evidence_requirement == requirement


def test_invalid_research_source_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ResearchRequest(
            objective="Research.",
            preferred_source_types=[
                cast(Any, "search_engine")
            ]
        )


def test_invalid_evidence_requirement_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ResearchRequest(
            objective="Research.",
            evidence_requirement=cast(Any, "certain")
        )


def test_max_sources_is_bounded() -> None:
    with pytest.raises(ValidationError):
        ResearchRequest(
            objective="Research.",
            max_sources=0,
        )

    with pytest.raises(ValidationError):
        ResearchRequest(
            objective="Research.",
            max_sources=101,
        )


def test_research_question_requires_nonempty_fields() -> None:
    with pytest.raises(ValidationError):
        ResearchQuestion(
            question_id="",
            question="Valid question.",
        )

    with pytest.raises(ValidationError):
        ResearchQuestion(
            question_id="q-1",
            question="",
        )


def test_research_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ResearchResult(
            **cast(
                Any,
                {
                    "objective": "Research.",
                    "unexpected_field": "not allowed",
                },
            )
        )

    with pytest.raises(ValidationError):
        ResearchResult(
            **cast(
            Any,
                {
                    "objective": "Research.",
                    "unexpected_field": "not allowed",
                },
            )
        )


def test_research_result_defaults_to_unknown_evidence_quality() -> None:
    result = ResearchResult(
        objective="Research."
    )

    assert result.evidence_quality == "unknown"
    assert result.sources_considered == []
    assert result.unanswered_questions == []


def test_research_result_serializes_to_json() -> None:
    request = ResearchRequest(
        objective="Research settings.",
        questions=[
            ResearchQuestion(
                question_id="q1",
                question="What settings are available?",
            )
        ],
    )

    result = ResearchResult(
        objective=request.objective,
        sources_considered=["source:settings"],
    )

    json.dumps(request.model_dump())
    json.dumps(result.model_dump())

    assert request.model_dump()["questions"][0]["question_id"] == "q1"
    assert result.model_dump()["sources_considered"] == [
        "source:settings"
    ]


def test_research_collector_json_schemas_are_generated() -> None:
    request_schema = ResearchRequest.model_json_schema()
    result_schema = ResearchResult.model_json_schema()

    assert request_schema["title"] == "ResearchRequest"
    assert result_schema["title"] == "ResearchResult"

    assert request_schema.get("additionalProperties") is False
    assert result_schema.get("additionalProperties") is False

    assert "questions" in request_schema["properties"]
    assert "preferred_source_types" in request_schema["properties"]
    assert "evidence_requirement" in request_schema["properties"]
    assert "unanswered_questions" in result_schema["properties"]
    assert "evidence_quality" in result_schema["properties"]


def test_checked_in_research_collector_schemas_match_models() -> None:
    base = Path(__file__).parent

    request_schema_path = base / "research_request.schema.json"
    result_schema_path = base / "research_result.schema.json"

    checked_in_request = json.loads(
        request_schema_path.read_text(encoding="utf-8")
    )
    checked_in_result = json.loads(
        result_schema_path.read_text(encoding="utf-8")
    )

    assert checked_in_request == ResearchRequest.model_json_schema()
    assert checked_in_result == ResearchResult.model_json_schema()
