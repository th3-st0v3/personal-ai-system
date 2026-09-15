from __future__ import annotations

from automation.orchestrator.research_collector import ResearchCollector
from automation.orchestrator.research_collector_schema import (
    ResearchRequest,
    ResearchResult,
)


class StubResearchCollector:
    """Deterministic implementation used only to test the interface contract."""

    def collect(self, request: ResearchRequest) -> ResearchResult:
        return ResearchResult(
            objective=request.objective,
            sources_considered=["stub:source"],
            unanswered_questions=[],
            evidence_quality="good",
        )


def test_research_collector_accepts_research_request() -> None:
    collector: ResearchCollector = StubResearchCollector()
    request = ResearchRequest(
        objective="Study simulator configuration workflows."
    )

    result = collector.collect(request)

    assert isinstance(result, ResearchResult)
    assert result.objective == request.objective


def test_research_collector_returns_research_result() -> None:
    collector: ResearchCollector = StubResearchCollector()
    request = ResearchRequest(
        objective="Study settings workflows.",
    )

    result = collector.collect(request)

    assert isinstance(result, ResearchResult)


def test_research_collector_preserves_request_objective() -> None:
    collector: ResearchCollector = StubResearchCollector()
    request = ResearchRequest(
        objective="Evaluate educational engineering products.",
    )

    result = collector.collect(request)

    assert result.objective == "Evaluate educational engineering products."


def test_research_collector_contract_does_not_require_provider_details() -> None:
    collector: ResearchCollector = StubResearchCollector()
    request = ResearchRequest(
        objective="Research observable product behavior.",
        questions=[],
        preferred_source_types=[],
        constraints=[],
    )

    result = collector.collect(request)

    assert result.evidence_quality == "good"
    assert result.sources_considered == ["stub:source"]
