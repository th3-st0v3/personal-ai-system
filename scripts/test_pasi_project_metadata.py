import scripts.sync_pasi_project_metadata as sync_module
from scripts.sync_pasi_project_metadata import (
    FRONTEND_PHASE_ISSUES,
    resolve_frontend_phase_map,
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
        body,
        project_items_with_status(STATUS_DONE),
        FRONTEND_PHASE_ISSUES,
        set(),
    )
    assert updated.count("[x]") == 23
    assert updated.count("[ ]") == 0
    verify_frontend_roadmap_checkboxes(
        updated,
        project_items_with_status(STATUS_DONE),
        FRONTEND_PHASE_ISSUES,
        set(),
    )


def test_checkbox_remains_unchecked_for_todo_and_in_progress() -> None:
    body = roadmap_body("[x]")
    for status in (STATUS_TODO, "In Progress"):
        updated = synchronize_frontend_roadmap_checkboxes(
            body,
            project_items_with_status(status),
            FRONTEND_PHASE_ISSUES,
            set(),
        )
        assert updated.count("[x]") == 0
        assert updated.count("[ ]") == 23


def test_checkbox_verifier_detects_drift() -> None:
    body = roadmap_body()
    try:
        verify_frontend_roadmap_checkboxes(
            body,
            project_items_with_status(STATUS_DONE),
            FRONTEND_PHASE_ISSUES,
            set(),
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


def test_closed_frontend_phase_sets_done_status(monkeypatch) -> None:
    project = {
        "id": "project-1",
        "fields": {
            "nodes": [
                {
                    "__typename": "ProjectV2SingleSelectField",
                    "id": "status-field",
                    "name": "Status",
                    "options": [
                        {"id": "todo", "name": "Todo"},
                        {"id": "progress", "name": "In Progress"},
                        {"id": "done", "name": "Done"},
                    ],
                }
            ]
        },
    }
    items = {
        319: {"id": "item-319", "status": {"name": "Todo"}},
    }
    calls = []

    monkeypatch.setattr(
        sync_module,
        "update_item_field",
        lambda project_id, item_id, field_id, value: calls.append(
            (project_id, item_id, field_id, value)
        ),
    )

    sync_module.sync_frontend_statuses(
        project,
        items,
        {319: "CLOSED"},
        {"P0": 319},
    )

    assert calls == [
        (
            "project-1",
            "item-319",
            "status-field",
            {"singleSelectOptionId": "done"},
        )
    ]


def test_reopened_frontend_phase_returns_to_todo(monkeypatch) -> None:
    project = {
        "id": "project-1",
        "fields": {
            "nodes": [
                {
                    "__typename": "ProjectV2SingleSelectField",
                    "id": "status-field",
                    "name": "Status",
                    "options": [
                        {"id": "todo", "name": "Todo"},
                        {"id": "progress", "name": "In Progress"},
                        {"id": "done", "name": "Done"},
                    ],
                }
            ]
        },
    }
    items = {
        319: {"id": "item-319", "status": {"name": "Done"}},
    }
    calls = []

    monkeypatch.setattr(
        sync_module,
        "update_item_field",
        lambda project_id, item_id, field_id, value: calls.append(
            (project_id, item_id, field_id, value)
        ),
    )
    old_action = sync_module.PROJECT_EVENT_ACTION
    old_issue = sync_module.PROJECT_EVENT_ISSUE_NUMBER_RAW
    sync_module.PROJECT_EVENT_ACTION = "reopened"
    sync_module.PROJECT_EVENT_ISSUE_NUMBER_RAW = "319"
    try:
        sync_module.sync_frontend_statuses(
            project,
            items,
            {319: "OPEN"},
            {"P0": 319},
        )
    finally:
        sync_module.PROJECT_EVENT_ACTION = old_action
        sync_module.PROJECT_EVENT_ISSUE_NUMBER_RAW = old_issue

    assert calls == [
        (
            "project-1",
            "item-319",
            "status-field",
            {"singleSelectOptionId": "todo"},
        )
    ]


def fake_frontend_issues() -> list[dict]:
    return [
        {
            "number": issue,
            "title": f"FE-P{index} — Example frontend phase",
            "state": "open",
            "labels": ["frontend", "roadmap", "vertical-slice"],
            "body": (
                "<!-- PASI_PROJECT_METADATA\n"
                "TYPE: frontend\n"
                f"PHASE: P{index}\n"
                f"ITERATION: {sync_module.PHASES[f'P{index}']['iteration']}\n"
                f"START_DATE: {sync_module.PHASES[f'P{index}']['start']}\n"
                f"END_DATE: {sync_module.PHASES[f'P{index}']['end']}\n"
                "TEAM: Frontend\n"
                f"QUARTER: {sync_module.PHASES[f'P{index}']['quarter']}\n"
                "PASI_PROJECT_METADATA\n-->"
            ),
        }
        for index, issue in enumerate(range(319, 342))
    ]


def test_frontend_phase_resolver_accepts_canonical_map(monkeypatch) -> None:
    monkeypatch.setattr(sync_module, "all_frontend_phase_issues", fake_frontend_issues)
    resolved, invalid = resolve_frontend_phase_map()
    assert invalid == set()
    assert resolved == FRONTEND_PHASE_ISSUES


def test_frontend_phase_resolver_rejects_renamed_issue(monkeypatch) -> None:
    issues = fake_frontend_issues()
    issues[0]["title"] = "Renamed runtime proof UI"
    monkeypatch.setattr(sync_module, "all_frontend_phase_issues", lambda: issues)
    resolved, invalid = resolve_frontend_phase_map()
    assert "P0" in invalid
    assert "P0" not in resolved


def test_frontend_phase_resolver_rejects_missing_issue(monkeypatch) -> None:
    issues = [issue for issue in fake_frontend_issues() if issue["number"] != 319]
    monkeypatch.setattr(sync_module, "all_frontend_phase_issues", lambda: issues)
    resolved, invalid = resolve_frontend_phase_map()
    assert "P0" in invalid
    assert "P0" not in resolved


def test_frontend_phase_resolver_rejects_duplicate_issue(monkeypatch) -> None:
    issues = fake_frontend_issues()
    duplicate = dict(issues[0])
    duplicate["number"] = 350
    issues.append(duplicate)
    monkeypatch.setattr(sync_module, "all_frontend_phase_issues", lambda: issues)
    resolved, invalid = resolve_frontend_phase_map()
    assert "P0" in invalid
    assert "P0" not in resolved


def test_invalid_phase_checkbox_is_left_unchanged() -> None:
    body = roadmap_body()
    changed = synchronize_frontend_roadmap_checkboxes(
        body,
        project_items_with_status(STATUS_DONE),
        {phase: issue for phase, issue in FRONTEND_PHASE_ISSUES.items() if phase != "P0"},
        {"P0"},
    )
    p0_line = next(line for line in changed.splitlines() if "[FE-P0" in line)
    assert p0_line.startswith("- [ ]")


def test_wrong_roadmap_link_fails_closed() -> None:
    body = roadmap_body().replace(
        "https://github.com/th3-st0v3/personal-ai-system/issues/319",
        "https://github.com/th3-st0v3/personal-ai-system/issues/999",
        1,
    )
    try:
        verify_frontend_roadmap_checkboxes(
            body,
            project_items_with_status(STATUS_DONE),
            FRONTEND_PHASE_ISSUES,
            set(),
        )
    except RuntimeError as exc:
        assert "mapping drifted" in str(exc)
    else:
        raise AssertionError("Expected wrong FE-P0 roadmap link to fail closed")
