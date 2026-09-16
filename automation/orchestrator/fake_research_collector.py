from __future__ import annotations

from .research_collector_schema import (
    ResearchEvidenceQuality,
    ResearchRequest,
    ResearchResult,
)
from .research_schema import ResearchFinding, ResearchObservation


class FakeResearchCollector:
    """Deterministic in-process implementation of the research collector contract."""

    def __init__(
        self,
        *,
        observations: list[ResearchObservation] | None = None,
        findings: list[ResearchFinding] | None = None,
        sources_considered: list[str] | None = None,
        unanswered_questions: list[str] | None = None,
        evidence_quality: ResearchEvidenceQuality = "unknown",
    ) -> None:
        self._observations = list(observations or [])
        self._findings = list(findings or [])
        self._sources_considered = list(sources_considered or [])
        self._unanswered_questions = list(unanswered_questions or [])
        self._evidence_quality: ResearchEvidenceQuality = evidence_quality
        self.requests: list[ResearchRequest] = []

    def collect(self, request: ResearchRequest) -> ResearchResult:
        """Return deterministic canned research data for the supplied request."""
        self.requests.append(request)

        return ResearchResult(
            objective=request.objective,
            observations=list(self._observations),
            findings=list(self._findings),
            sources_considered=list(self._sources_considered),
            unanswered_questions=list(self._unanswered_questions),
            evidence_quality=self._evidence_quality,
        )


__all__ = ["FakeResearchCollector"]
