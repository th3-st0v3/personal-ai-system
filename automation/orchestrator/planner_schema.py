from __future__ import annotations

from typing import Literal

from pydantic import Field

from .context_schema import PASIModel


HumanApprovalStatus = Literal[
    "not_required",
    "pending",
    "approved",
    "rejected",
]


class ProposedStep(PASIModel):
    step_id: str = Field(min_length=1)
    description: str = Field(min_length=1)


class PlannerResult(PASIModel):
    proposed_steps: list[ProposedStep] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)
    verification_requirements: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    human_approval_status: HumanApprovalStatus = "not_required"
