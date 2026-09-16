from __future__ import annotations

from typing import Literal, TypeAlias

from pydantic import Field

from .context_schema import PASIModel
from .research_schema import ResearchFinding, ResearchObservation


ResearchSourceType: TypeAlias = Literal[
    "web",
    "browser",
    "documentation",
    "github",
    "database",
    "file",
    "other",
]

EvidenceRequirement: TypeAlias = Literal[
    "any",
    "documented",
    "direct",
    "multiple_sources",
]


class ResearchQuestion(PASIModel):
    question_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    required: bool = True


class ResearchRequest(PASIModel):
    objective: str = Field(min_length=1)
    questions: list[ResearchQuestion] = Field(default_factory=list)

    preferred_source_types: list[ResearchSourceType] = Field(
        default_factory=list
    )

    evidence_requirement: EvidenceRequirement = "any"

    max_sources: int = Field(default=10, ge=1, le=100)
    constraints: list[str] = Field(default_factory=list)


ResearchEvidenceQuality: TypeAlias = Literal[
    "poor",
    "fair",
    "good",
    "strong",
    "unknown",
]


class ResearchResult(PASIModel):
    objective: str
    observations: list[ResearchObservation] = Field(default_factory=list)
    findings: list[ResearchFinding] = Field(default_factory=list)
    sources_considered: list[str] = Field(default_factory=list)
    unanswered_questions: list[str] = Field(default_factory=list)
    evidence_quality: ResearchEvidenceQuality = "unknown"