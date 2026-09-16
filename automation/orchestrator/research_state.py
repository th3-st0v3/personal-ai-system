from __future__ import annotations

from datetime import datetime, timezone

from pydantic import Field

from .context_schema import PASIModel
from .research_collector_schema import ResearchEvidenceQuality
from .research_schema import ResearchFinding, ResearchObservation


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ResearchState(PASIModel):
    task_id: str = Field(min_length=1)
    observations: list[ResearchObservation] = Field(default_factory=list)
    findings: list[ResearchFinding] = Field(default_factory=list)
    sources_considered: list[str] = Field(default_factory=list)
    unanswered_questions: list[str] = Field(default_factory=list)
    evidence_quality: ResearchEvidenceQuality = "unknown"
    updated_at: datetime = Field(default_factory=utc_now)

    def add_observation(
        self,
        observation: ResearchObservation,
    ) -> None:
        self.observations.append(observation)
        self.updated_at = utc_now()

    def add_finding(
        self,
        finding: ResearchFinding,
    ) -> None:
        self.findings.append(finding)
        self.updated_at = utc_now()
