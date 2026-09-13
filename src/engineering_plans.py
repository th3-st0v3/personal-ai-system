"""Deterministic engineering test-plan and status-report helpers."""
from __future__ import annotations


def verification_method(text: str) -> str:
    value = str(text).casefold()
    if any(word in value for word in ("measure", "temperature", "pressure", "voltage", "current", "flow")):
        return "measurement"
    if any(word in value for word in ("inspect", "dimension", "material", "assembly")):
        return "inspection"
    if any(word in value for word in ("calculate", "equation", "analytical", "stress", "torque")):
        return "analysis/calculation"
    if any(word in value for word in ("simulate", "model", "dynamic", "thermal", "fluid")):
        return "simulation"
    return "demonstration"


def build_test_plan(requirements: list[dict[str, object]]) -> list[dict[str, object]]:
    plan = []
    for requirement in requirements:
        description = str(requirement.get("description") or requirement.get("title") or "")
        method = verification_method(description)
        plan.append({
            "requirement_id": requirement.get("id"),
            "identifier": requirement.get("identifier"),
            "title": requirement.get("title") or description,
            "verification_method": method,
            "acceptance_criteria": requirement.get("acceptance_criteria") or "Define explicit acceptance criteria before verification.",
            "evidence_types": [
                {"measurement": "test_result", "inspection": "test_result", "analysis/calculation": "calculation", "simulation": "simulation_run", "demonstration": "test_result"}[method]
            ],
        })
    return plan


def build_weekly_report(requirements: list[dict[str, object]], sources: list[dict[str, object]], decisions: list[dict[str, object]], evidence_by_requirement: dict[int, list[dict[str, object]]]) -> dict[str, object]:
    counts = {"Verified": 0, "Failed": 0, "Unverified": 0, "At risk": 0}
    unclear = []
    for requirement in requirements:
        status = requirement.get("status") or "Unverified"
        if status in counts:
            counts[status] += 1
        evidence = [item for item in evidence_by_requirement.get(int(requirement["id"]), []) if item.get("lifecycle_status", "Active") == "Active"]
        if not evidence and status not in {"Failed", "At risk"}:
            unclear.append({"requirement_id": requirement["id"], "reason": "No active evidence found; status should be reviewed."})
    return {
        "requirements": {"total": len(requirements), "by_status": counts},
        "sources": len(sources),
        "decisions": len(decisions),
        "unclear_statuses": unclear,
        "summary": f"{counts['Verified']} verified, {counts['Failed']} failed, {counts['At risk']} at risk, {counts['Unverified']} unverified.",
        "generated_from_live_records": True,
    }
