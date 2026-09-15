from __future__ import annotations

from automation.orchestrator.fake_research_collector import (
    FakeResearchCollector,
)
from automation.orchestrator.research_collector import ResearchCollector
from automation.orchestrator.research_collector_schema import (
    ResearchRequest,
    ResearchResult,
)
from automation.orchestrator.research_schema import (
    ResearchFinding,
    ResearchObservation,
)


def test_fake_research_collector_implements_research_collector_contract() -> None:
    collector: ResearchCollector = FakeResearchCollector()

    request = ResearchRequest(
        objective="Study simulator configuration workflows."
    )

    result = collector.collect(request)

    assert isinstance(result, ResearchResult)
    assert result.objective == request.objective


def test_fake_research_collector_is_deterministic() -> None:
    request = ResearchRequest(
        objective="Study settings workflows."
    )

    collector = FakeResearchCollector(
        sources_considered=["fake:settings"],
        evidence_quality="good",
    )

    first = collector.collect(request)
    second = collector.collect(request)

    assert first == second
    assert len(collector.requests) == 2
    assert collector.requests[0] == request
    assert collector.requests[1] == request


def test_fake_research_collector_preserves_request_objective() -> None:
    collector = FakeResearchCollector()

    request = ResearchRequest(
        objective="Evaluate educational engineering products."
    )

    result = collector.collect(request)

    assert result.objective == request.objective


def test_fake_research_collector_returns_configured_observations_and_findings() -> None:
    observation = ResearchObservation(
        observation_id="obs-1",
        subject="Simulator",
        aspect="workflow",
        statement="Inputs are configured before execution.",
        source_ref="source:simulator",
    )
    finding = ResearchFinding(
        finding_id="finding-1",
        statement="Configuration should remain distinct from execution.",
        supporting_observations=["obs-1"],
        design_implications=["Keep run configuration separate from run results."],
    )

    collector = FakeResearchCollector(
        observations=[observation],
        findings=[finding],
        sources_considered=["source:simulator"],
        unanswered_questions=["Whether runs persist server-side."],
        evidence_quality="strong",
    )

    request = ResearchRequest(
        objective="Study simulator workflows."
    )

    result = collector.collect(request)

    assert result.observations == [observation]
    assert result.findings == [finding]
    assert result.sources_considered == ["source:simulator"]
    assert result.unanswered_questions == [
        "Whether runs persist server-side."
    ]
    assert result.evidence_quality == "strong"


def test_fake_research_collector_defaults_to_empty_research_payload() -> None:
    collector = FakeResearchCollector()

    result = collector.collect(
        ResearchRequest(objective="Research observable behavior.")
    )

    assert result.observations == []
    assert result.findings == []
    assert result.sources_considered == []
    assert result.unanswered_questions == []
    assert result.evidence_quality == "unknown"


def test_fake_research_collector_copies_configured_lists() -> None:
    observations = [
        ResearchObservation(
            observation_id="obs-1",
            subject="Product",
            aspect="settings",
            statement="The setting is visible.",
        )
    ]
    sources = ["source:product"]

    collector = FakeResearchCollector(
        observations=observations,
        sources_considered=sources,
    )

    observations.append(
        ResearchObservation(
            observation_id="obs-2",
            subject="Product",
            aspect="workflow",
            statement="The workflow is visible.",
        )
    )
    sources.append("source:other")

    result = collector.collect(
        ResearchRequest(objective="Research the product.")
    )

    assert result.observations == [
        ResearchObservation(
            observation_id="obs-1",
            subject="Product",
            aspect="settings",
            statement="The setting is visible.",
        )
    ]
    assert result.sources_considered == ["source:product"]
