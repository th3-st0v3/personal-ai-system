from scripts.sync_pasi_project_metadata import (
    FRONTEND_PHASE_ISSUES,
    STATUS_DONE,
    STATUS_TODO,
    parse_roadmap_form,
    synchronize_frontend_roadmap_checkboxes,
    verify_frontend_roadmap_checkboxes,
)


def roadmap_body(checkmark: str = "[ ]") -> str:
    lines = []
    for index in range(23):
        issue = 319 + index
        lines.append(
            f"- {checkmark} [FE-P{index} — Example frontend phase]"
            f"(https://github.com/th3-st0v3/personal-ai-system/issues/{issue})"
        )
    return "\n".join(lines)


def project_items_with_status(status: str) -> dict[int, dict[str, dict[str, str]]]:
    return {
        issue: {"status": {"name": status}}
        for issue in FRONTEND_PHASE_ISSUES.values()
    }


def test_frontend_phase_mapping_is_complete_and_contiguous() -> None:
    assert len(FRONTEND_PHASE_ISSUES) == 23
    assert [FRONTEND_PHASE_ISSUES[f"P{i}"] for i in range(23)] == list(range(319, 342))


def test_checkbox_mirrors_done_status() -> None:
    body = roadmap_body()
    updated = synchronize_frontend_roadmap_checkboxes(
        body, project_items_with_status(STATUS_DONE)
    )
    assert updated.count("[x]") == 23
    assert updated.count("[ ]") == 0
    verify_frontend_roadmap_checkboxes(
        updated, project_items_with_status(STATUS_DONE)
    )


def test_checkbox_remains_unchecked_for_todo_and_in_progress() -> None:
    body = roadmap_body("[x]")
    for status in (STATUS_TODO, "In Progress"):
        updated = synchronize_frontend_roadmap_checkboxes(
            body, project_items_with_status(status)
        )
        assert updated.count("[x]") == 0
        assert updated.count("[ ]") == 23


def test_checkbox_verifier_detects_drift() -> None:
    body = roadmap_body()
    try:
        verify_frontend_roadmap_checkboxes(
            body, project_items_with_status(STATUS_DONE)
        )
    except RuntimeError as exc:
        assert "out of sync" in str(exc)
    else:
        raise AssertionError("Expected roadmap checkbox drift to be rejected")


def test_roadmap_form_parses_structured_fields() -> None:
    body = """
### Description
Build the next control-plane surface.

### Start Date
2026-10-04

### End Date
2026-10-12

### Relationship
depends on #273; related to #319

### Development Milestone
M1

### Status
In Progress
"""
    form = parse_roadmap_form(body)
    assert form is not None
    assert form.description == "Build the next control-plane surface."
    assert form.start_date == "2026-10-04"
    assert form.end_date == "2026-10-12"
    assert form.relationship == "depends on #273; related to #319"
    assert form.development_milestone == "M1"
    assert form.status == "In Progress"


def test_roadmap_form_rejects_invalid_status() -> None:
    body = """
### Description
Example

### Start Date
2026-10-04

### End Date
2026-10-12

### Relationship
None

### Development Milestone
M0

### Status
Blocked
"""
    try:
        parse_roadmap_form(body)
    except ValueError as exc:
        assert "Status" in str(exc)
    else:
        raise AssertionError("Expected invalid roadmap form status to be rejected")


def test_roadmap_form_rejects_reversed_dates() -> None:
    body = """
### Description
Example

### Start Date
2026-10-12

### End Date
2026-10-04

### Relationship
None

### Development Milestone
M0

### Status
Todo
"""
    try:
        parse_roadmap_form(body)
    except ValueError as exc:
        assert "precedes" in str(exc)
    else:
        raise AssertionError("Expected reversed roadmap dates to be rejected")
