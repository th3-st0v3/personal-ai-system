from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from automation.orchestrator.research_schema import (
    ResearchFinding,
    ResearchObservation,
)


def test_observation_captures_direct_external_behavior() -> None:
    observation = ResearchObservation(
        observation_id="obs-chatgpt-settings-theme",
        subject="ChatGPT settings",
        aspect="theme selection",
        statement="Changing the theme option changes the visible application theme.",
        source_ref="source:chatgpt-settings",
        source_locator="settings/general/theme",
        kind="direct_observation",
        confidence="high",
    )

    assert observation.subject == "ChatGPT settings"
    assert observation.aspect == "theme selection"
    assert observation.kind == "direct_observation"
    assert observation.confidence == "high"


def test_observation_can_represent_documented_behavior() -> None:
    observation = ResearchObservation(
        observation_id="obs-simulator-save",
        subject="Engineering simulator",
        aspect="run persistence",
        statement="Documentation states that simulation runs can be saved for later review.",
        source_ref="source:simulator-documentation",
        kind="documented_behavior",
        confidence="high",
    )

    assert observation.kind == "documented_behavior"


def test_observation_can_mark_inference() -> None:
    observation = ResearchObservation(
        observation_id="obs-settings-backend-inference",
        subject="Settings system",
        aspect="persistence",
        statement="The setting is likely persisted server-side because it remains after reload.",
        kind="inferred_behavior",
        confidence="low",
    )

    assert observation.kind == "inferred_behavior"
    assert observation.confidence == "low"


def test_finding_connects_observations_to_design_implications() -> None:
    finding = ResearchFinding(
        finding_id="finding-settings-architecture",
        statement="Settings should separate global preferences from simulation configuration.",
        supporting_observations=[
            "obs-chatgpt-settings-theme",
            "obs-simulator-save",
        ],
        design_implications=[
            "Keep application preferences independent from simulation-run state.",
            "Persist simulation configuration with the simulation workflow.",
        ],
        confidence="high",
        requires_verification=True,
    )

    assert len(finding.supporting_observations) == 2
    assert len(finding.design_implications) == 2
    assert finding.requires_verification is True


def test_observation_requires_core_identity_fields() -> None:
    with pytest.raises(ValidationError):
        ResearchObservation(
            observation_id="",
            subject="Settings",
            aspect="theme",
            statement="Theme changes.",
        )

    with pytest.raises(ValidationError):
        ResearchObservation(
            observation_id="obs-1",
            subject="",
            aspect="theme",
            statement="Theme changes.",
        )


def test_finding_requires_a_statement() -> None:
    with pytest.raises(ValidationError):
        ResearchFinding(
            finding_id="finding-1",
            statement="",
        )


def test_research_schema_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ResearchFinding(
            finding_id="finding-1",
            statement="A finding.",
            unexpected_field="not allowed",
        )


@pytest.mark.parametrize(
    "kind",
    [
        "direct_observation",
        "documented_behavior",
        "inferred_behavior",
    ],
)
def test_observation_kind_is_constrained(kind: str) -> None:
    observation = ResearchObservation(
        observation_id="obs-kind",
        subject="Test subject",
        aspect="test aspect",
        statement="Test statement.",
        kind=kind,
    )

    assert observation.kind == kind


@pytest.mark.parametrize(
    "confidence",
    ["low", "medium", "high"],
)
def test_confidence_is_constrained(confidence: str) -> None:
    observation = ResearchObservation(
        observation_id="obs-confidence",
        subject="Test subject",
        aspect="test aspect",
        statement="Test statement.",
        confidence=confidence,
    )

    finding = ResearchFinding(
        finding_id="finding-confidence",
        statement="Test finding.",
        confidence=confidence,
    )

    assert observation.confidence == confidence
    assert finding.confidence == confidence


def test_invalid_research_values_are_rejected() -> None:
    with pytest.raises(ValidationError):
        ResearchObservation(
            observation_id="obs-invalid",
            subject="Test",
            aspect="Behavior",
            statement="Something happened.",
            kind="guess",
        )

    with pytest.raises(ValidationError):
        ResearchFinding(
            finding_id="finding-invalid",
            statement="Something was found.",
            confidence="certain",
        )


def test_research_models_serialize_to_json() -> None:
    observation = ResearchObservation(
        observation_id="obs-1",
        subject="Educational platform",
        aspect="feedback",
        statement="The platform provides immediate feedback.",
        source_ref="source:education-platform",
    )

    finding = ResearchFinding(
        finding_id="finding-1",
        statement="Immediate feedback may be useful for simulation learning.",
        supporting_observations=["obs-1"],
        design_implications=["Show simulation verification results immediately."],
    )

    json.dumps(observation.model_dump())
    json.dumps(finding.model_dump())

    assert observation.model_dump()["source_ref"] == "source:education-platform"
    assert finding.model_dump()["supporting_observations"] == ["obs-1"]


def test_research_json_schemas_are_generated() -> None:
    observation_schema = ResearchObservation.model_json_schema()
    finding_schema = ResearchFinding.model_json_schema()

    assert observation_schema["title"] == "ResearchObservation"
    assert finding_schema["title"] == "ResearchFinding"

    assert observation_schema.get("additionalProperties") is False
    assert finding_schema.get("additionalProperties") is False

    assert "statement" in observation_schema["properties"]
    assert "supporting_observations" in finding_schema["properties"]
    assert "design_implications" in finding_schema["properties"]


def test_checked_in_research_json_schemas_match_models() -> None:
    from pathlib import Path

    base = Path(__file__).parent

    observation_schema = json.loads(
        (base / "research_observation.schema.json").read_text(
            encoding="utf-8"
        )
    )
    finding_schema = json.loads(
        (base / "research_finding.schema.json").read_text(
            encoding="utf-8"
        )
    )

    assert observation_schema == ResearchObservation.model_json_schema()
    assert finding_schema == ResearchFinding.model_json_schema()
