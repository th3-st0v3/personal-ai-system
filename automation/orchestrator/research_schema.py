from __future__ import annotations

from typing import Literal

from pydantic import Field

from .context_schema import PASIModel


ObservationKind = Literal[
    "direct_observation",
    "documented_behavior",
    "inferred_behavior",
]

Confidence = Literal[
    "low",
    "medium",
    "high",
]


class ResearchObservation(PASIModel):
    observation_id: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    aspect: str = Field(min_length=1)
    statement: str = Field(min_length=1)

    source_ref: str | None = None
    source_locator: str | None = None

    kind: ObservationKind = "direct_observation"
    confidence: Confidence = "medium"


class ResearchFinding(PASIModel):
    finding_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)

    supporting_observations: list[str] = Field(default_factory=list)
    design_implications: list[str] = Field(default_factory=list)

    confidence: Confidence = "medium"
    requires_verification: bool = False
