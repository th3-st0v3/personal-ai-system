"""Deterministic engineering test-plan and status-report helpers."""
from __future__ import annotations

from typing import Required, TypedDict


class RequirementRecord(TypedDict, total=False):
    id: Required[int]
    project_id: int
    identifier: str | None
    title: str | None
    description: str
    acceptance_criteria: str | None
    priority: str | None
    status: str
    created_at: str
    updated_at: str


class TestPlanItem(TypedDict):
    requirement_id: int
    identifier: str | None
    title: str
    verification_method: str
    acceptance_criteria: str
    evidence_types: list[str]


def verification_method(text: str) -> str:
    value = text.casefold()
    if any(word in value for word in ("measure", "temperature", "pressure", "voltage", "current", "flow")):
        return "measurement"
    if any(word in value for word in ("inspect", "dimension", "material", "assembly")):
        return "inspection"
    if any(word in value for word in ("calculate", "equation", "analytical", "stress", "torque")):
        return "analysis/calculation"
    if any(word in value for word in ("simulate", "model", "dynamic", "thermal", "fluid")):
        return "simulation"
    return "demonstration"


def build_test_plan(requirements: list[RequirementRecord]) -> list[TestPlanItem]:
    evidence_map = {
        "measurement": "test_result",
        "inspection": "test_result",
        "analysis/calculation": "calculation",
        "simulation": "simulation_run",
        "demonstration": "test_result",
    }
    plan: list[TestPlanItem] = []
    for requirement in requirements:
        description = str(requirement.get("description") or requirement.get("title") or "")
        method = verification_method(description)
        requirement_id = requirement.get("id")
        if requirement_id is None:
            raise ValueError("Requirement ID is required to build a test plan.")
        title_value = requirement.get("title") or description
        acceptance = requirement.get("acceptance_criteria") or "Define explicit acceptance criteria before verification."
        plan.append({
            "requirement_id": requirement_id,
            "identifier": requirement.get("identifier"),
            "title": str(title_value),
            "verification_method": method,
            "acceptance_criteria": str(acceptance),
            "evidence_types": [evidence_map[method]],
        })
    return plan


def build_weekly_report(
    requirements: list[RequirementRecord],
    sources: list[dict[str, object]],
    decisions: list[dict[str, object]],
    evidence_by_requirement: dict[int, list[dict[str, object]]],
) -> dict[str, object]:
    counts = {"Verified": 0, "Failed": 0, "Unverified": 0, "At risk": 0}
    unclear: list[dict[str, object]] = []
    for requirement in requirements:
        requirement_id = requirement.get("id")
        if requirement_id is None:
            raise ValueError("Requirement ID is required to build a weekly report.")
        status = str(requirement.get("status") or "Unverified")
        if status in counts:
            counts[status] += 1
        evidence = [
            item for item in evidence_by_requirement.get(requirement_id, [])
            if item.get("lifecycle_status", "Active") == "Active"
        ]
        if not evidence and status not in {"Failed", "At risk"}:
            unclear.append({
                "requirement_id": requirement_id,
                "reason": "No active evidence found; status should be reviewed.",
            })
    return {
        "requirements": {"total": len(requirements), "by_status": counts},
        "sources": len(sources),
        "decisions": len(decisions),
        "unclear_statuses": unclear,
        "summary": f"{counts['Verified']} verified, {counts['Failed']} failed, {counts['At risk']} at risk, {counts['Unverified']} unverified.",
        "generated_from_live_records": True,
    }
