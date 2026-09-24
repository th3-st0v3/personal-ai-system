#!/usr/bin/env python3
"""Synchronize PASI phase metadata into a GitHub Project v2.

The issue metadata block is validated against the canonical P0-P22 phase
schedule in this file. The synchronizer then:
- identifies one exact user-owned Project by owner + number,
- ensures controlled Project fields exist,
- reconciles Iteration 1..23,
- adds/updates roadmap issues in the Project,
- verifies every expected field value after synchronization.

Requires GitHub CLI authentication with Project write access.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import date
from typing import Any

REPO = "th3-st0v3/personal-ai-system"
PROJECT_OWNER = os.environ.get("PASI_PROJECT_OWNER", "th3-st0v3")
PROJECT_NUMBER_RAW = os.environ.get("PASI_PROJECT_NUMBER", "")
PROJECT_TITLE = os.environ.get("PASI_PROJECT_TITLE", "").strip()
MAX_RETRIES = max(1, int(os.environ.get("PASI_PROJECT_RETRIES", "4")))

# GitHub Projects creates these as native date fields on user-owned Projects.
# Reuse them instead of creating duplicate custom fields.
START_FIELD = "Start date"
END_FIELD = "Target date"
TEAM_FIELD = "Team"

# Project #1 already has a native "Quarter" iteration field. PASI's canonical
# quarter values (Q3-2026, Q4-2026, ...) are single-select metadata, so keep
# them in a dedicated field rather than colliding with the native iteration field.
QUARTER_FIELD = "PASI Quarter"
ITERATION_FIELD = "Iteration"
STATUS_FIELD = "Status"
DESCRIPTION_FIELD = "Description"
RELATIONSHIP_FIELD = "Relationship"
DEVELOPMENT_MILESTONE_FIELD = "Development Milestone"
STATUS_DONE = "Done"
STATUS_TODO = "Todo"
FRONTEND_ROADMAP_ISSUE = 318
FRONTEND_PHASE_ISSUES = {f"P{index}": 319 + index for index in range(23)}
FRONTEND_PHASE_TITLE_RE = re.compile(r"^FE-(?P<phase>P\d+)\s+—\s+")
PROJECT_EVENT_ACTION = os.environ.get("PASI_PROJECT_EVENT_ACTION", "").strip().lower()
PROJECT_EVENT_ISSUE_NUMBER_RAW = os.environ.get("PASI_PROJECT_EVENT_ISSUE_NUMBER", "").strip()


META_RE = re.compile(
    r"<!--\s*PASI_PROJECT_METADATA\s*\n(?P<body>.*?)\nPASI_PROJECT_METADATA\s*-->",
    re.DOTALL,
)

PLACEHOLDER_VALUES = {
    "P#",
    "FE-P#",
    "Iteration #",
    "YYYY-MM-DD",
    "Q#-YYYY",
    "#000",
}

PHASE_SCHEDULE = [
    ("P0", "Iteration 1", "2026-09-22", "2026-10-04", "Q3-2026"),
    ("P1", "Iteration 2", "2026-10-04", "2026-10-12", "Q4-2026"),
    ("P2", "Iteration 3", "2026-10-13", "2026-10-24", "Q4-2026"),
    ("P3", "Iteration 4", "2026-10-25", "2026-11-07", "Q4-2026"),
    ("P4", "Iteration 5", "2026-11-08", "2026-11-21", "Q4-2026"),
    ("P5", "Iteration 6", "2026-11-22", "2026-12-05", "Q4-2026"),
    ("P6", "Iteration 7", "2026-12-06", "2026-12-19", "Q4-2026"),
    ("P7", "Iteration 8", "2026-12-20", "2027-01-09", "Q4-2026"),
    ("P8", "Iteration 9", "2027-01-10", "2027-01-30", "Q1-2027"),
    ("P9", "Iteration 10", "2027-01-31", "2027-02-20", "Q1-2027"),
    ("P10", "Iteration 11", "2027-02-21", "2027-03-20", "Q1-2027"),
    ("P11", "Iteration 12", "2027-03-21", "2027-04-10", "Q1-2027"),
    ("P12", "Iteration 13", "2027-04-11", "2027-05-08", "Q2-2027"),
    ("P13", "Iteration 14", "2027-05-09", "2027-05-29", "Q2-2027"),
    ("P14", "Iteration 15", "2027-05-30", "2027-06-19", "Q2-2027"),
    ("P15", "Iteration 16", "2027-06-20", "2027-07-10", "Q2-2027"),
    ("P16", "Iteration 17", "2027-07-11", "2027-08-07", "Q3-2027"),
    ("P17", "Iteration 18", "2027-08-08", "2027-08-28", "Q3-2027"),
    ("P18", "Iteration 19", "2027-08-29", "2027-09-25", "Q3-2027"),
    ("P19", "Iteration 20", "2027-09-26", "2027-10-16", "Q3-2027"),
    ("P20", "Iteration 21", "2027-10-17", "2027-11-13", "Q4-2027"),
    ("P21", "Iteration 22", "2027-11-14", "2027-12-11", "Q4-2027"),
    ("P22", "Iteration 23", "2027-12-12", "2028-01-15", "Q4-2027"),
]

PHASES = {
    phase: {
        "iteration": iteration,
        "start": start,
        "end": end,
        "quarter": quarter,
    }
    for phase, iteration, start, end, quarter in PHASE_SCHEDULE
}


@dataclass(frozen=True)
class Metadata:
    phase: str
    issue_type: str
    iteration: str
    start_date: str
    end_date: str
    team: str
    quarter: str


@dataclass(frozen=True)
class RoadmapForm:
    description: str
    start_date: str
    end_date: str
    relationship: str
    development_milestone: str
    status: str


ISSUE_FORM_RE = re.compile(
    r"^### (?P<label>Description|Start Date|End Date|Relationship|Development Milestone|Status)\s*$\n"
    r"(?P<value>.*?)(?=^### (?:Description|Start Date|End Date|Relationship|Development Milestone|Status)\s*$|\Z)",
    re.MULTILINE | re.DOTALL,
)


def parse_roadmap_form(body: str) -> RoadmapForm | None:
    matches = {
        match.group("label"): match.group("value").strip()
        for match in ISSUE_FORM_RE.finditer(body or "")
    }
    if not matches:
        return None

    required = [
        "Description",
        "Start Date",
        "End Date",
        "Relationship",
        "Development Milestone",
        "Status",
    ]
    missing = [label for label in required if not matches.get(label)]
    if missing:
        raise ValueError(
            "Incomplete PASI Roadmap Item form; missing: " + ", ".join(missing)
        )

    start_date = matches["Start Date"]
    end_date = matches["End Date"]
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError as exc:
        raise ValueError("Roadmap Item Start Date and End Date must be YYYY-MM-DD.") from exc
    if end < start:
        raise ValueError("Roadmap Item End Date precedes Start Date.")

    status = matches["Status"]
    if status not in {STATUS_TODO, "In Progress", STATUS_DONE}:
        raise ValueError(
            "Roadmap Item Status must be Todo, In Progress, or Done."
        )

    return RoadmapForm(
        description=matches["Description"],
        start_date=start_date,
        end_date=end_date,
        relationship=matches["Relationship"],
        development_milestone=matches["Development Milestone"],
        status=status,
    )


def validate_project_number() -> int:
    if not PROJECT_NUMBER_RAW.isdigit():
        raise RuntimeError("PASI_PROJECT_NUMBER must be a positive integer.")
    number = int(PROJECT_NUMBER_RAW)
    if number <= 0:
        raise RuntimeError("PASI_PROJECT_NUMBER must be greater than zero.")
    return number


def run_gh(args: list[str], *, input_text: str | None = None) -> str:
    proc = subprocess.run(
        ["gh", *args],
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"gh {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}"
        )
    return proc.stdout


def update_issue_body(issue_number: int, body: str) -> None:
    endpoint = f"repos/{REPO}/issues/{issue_number}"
    run_gh(
        ["api", endpoint, "--method", "PATCH", "--input", "-"],
        input_text=json.dumps({"body": body}),
    )


def retry_delay(attempt: int) -> float:
    return min(30.0, float(2 ** (attempt - 1)))


def is_retryable_graphql_error(errors: list[dict[str, Any]]) -> bool:
    retry_types = {"RATE_LIMITED", "INTERNAL", "TIMEOUT", "SERVICE_UNAVAILABLE"}
    retry_words = (
        "rate limit",
        "secondary rate",
        "temporarily unavailable",
        "timeout",
        "timed out",
        "internal server",
        "service unavailable",
        "try again",
    )
    for error in errors:
        if str(error.get("type", "")).upper() in retry_types:
            return True
        message = str(error.get("message", "")).lower()
        if any(word in message for word in retry_words):
            return True
    return False


def graphql(
    query: str,
    variables: dict[str, object] | None = None,
    *,
    retryable: bool = True,
) -> dict[str, Any]:
    payload = {"query": query, "variables": variables or {}}
    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            raw = run_gh(
                ["api", "graphql", "--input", "-"],
                input_text=json.dumps(payload),
            )
            response = json.loads(raw)
            errors = response.get("errors")
            if errors:
                if retryable and is_retryable_graphql_error(errors) and attempt < MAX_RETRIES:
                    time.sleep(retry_delay(attempt))
                    continue
                raise RuntimeError(json.dumps(errors, indent=2))
            return response["data"]
        except (RuntimeError, json.JSONDecodeError, KeyError) as exc:
            last_error = exc
            text = str(exc).lower()
            transportish = any(
                marker in text
                for marker in (
                    "timeout",
                    "timed out",
                    "connection",
                    "temporarily",
                    "rate limit",
                    "502",
                    "503",
                    "504",
                )
            )
            if retryable and transportish and attempt < MAX_RETRIES:
                time.sleep(retry_delay(attempt))
                continue
            raise

    raise RuntimeError(f"GraphQL operation failed after {MAX_RETRIES} attempts: {last_error}")


def parse_metadata(body: str) -> Metadata:
    match = META_RE.search(body or "")
    if not match:
        raise ValueError("Issue body is missing the PASI_PROJECT_METADATA marker.")

    values: dict[str, str] = {}
    for line in match.group("body").splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            values[key.strip()] = value.strip()

    required = [
        "PHASE",
        "TYPE",
        "ITERATION",
        "START_DATE",
        "END_DATE",
        "TEAM",
        "QUARTER",
    ]
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise ValueError(f"Missing planning metadata: {', '.join(missing)}")

    placeholders = [
        key for key in required
        if values.get(key, "") in PLACEHOLDER_VALUES
        or any(token in values.get(key, "") for token in ("YYYY", "Q#-", "#000"))
    ]
    if placeholders:
        raise ValueError(
            f"Unreplaced placeholder metadata in {', '.join(placeholders)}"
        )

    phase = values["PHASE"]
    if phase not in PHASES:
        raise ValueError(f"Unsupported phase {phase}; expected one of {', '.join(PHASES)}.")

    expected = PHASES[phase]
    if values["TYPE"] not in {"backend", "frontend"}:
        raise ValueError(f"Unsupported TYPE: {values['TYPE']}")
    expected_team = "Backend" if values["TYPE"] == "backend" else "Frontend"
    if values["TEAM"] != expected_team:
        raise ValueError(
            f"{phase} metadata TEAM must be {expected_team}, got {values['TEAM']}."
        )
    if values["ITERATION"] != expected["iteration"]:
        raise ValueError(
            f"{phase} metadata ITERATION must be {expected['iteration']}, got {values['ITERATION']}."
        )
    if values["START_DATE"] != expected["start"]:
        raise ValueError(
            f"{phase} metadata START_DATE must be {expected['start']}, got {values['START_DATE']}."
        )
    if values["END_DATE"] != expected["end"]:
        raise ValueError(
            f"{phase} metadata END_DATE must be {expected['end']}, got {values['END_DATE']}."
        )
    if values["QUARTER"] != expected["quarter"]:
        raise ValueError(
            f"{phase} metadata QUARTER must be {expected['quarter']}, got {values['QUARTER']}."
        )

    start = date.fromisoformat(values["START_DATE"])
    end = date.fromisoformat(values["END_DATE"])
    if end < start:
        raise ValueError(f"END_DATE precedes START_DATE for {phase}.")

    return Metadata(
        phase=phase,
        issue_type=values["TYPE"],
        iteration=values["ITERATION"],
        start_date=values["START_DATE"],
        end_date=values["END_DATE"],
        team=values["TEAM"],
        quarter=values["QUARTER"],
    )


def fetch_issue(issue_number: int) -> tuple[str, str, str, str]:
    query = """
    query($owner:String!, $repo:String!, $number:Int!) {
      repository(owner:$owner, name:$repo) {
        issue(number:$number) {
          id
          number
          title
          state
          body
        }
      }
    }
    """
    data = graphql(
        query,
        {"owner": "th3-st0v3", "repo": "personal-ai-system", "number": issue_number},
    )
    issue = data["repository"]["issue"]
    return issue["id"], issue["title"], issue.get("body") or "", issue["state"]


def project_snapshot() -> dict[str, Any]:
    number = validate_project_number()
    query = """
    query($login:String!, $number:Int!) {
      user(login:$login) {
        projectV2(number:$number) {
          id
          number
          title
          viewerCanUpdate
          fields(first:100) {
            nodes {
              __typename
              ... on ProjectV2Field { id name }
              ... on ProjectV2IterationField {
                id name
                configuration {
                  startDay
                  duration
                  iterations { id title startDate duration }
                }
              }
              ... on ProjectV2SingleSelectField {
                id name
                options { id name description color }
              }
            }
          }
        }
      }
    }
    """
    data = graphql(query, {"login": PROJECT_OWNER, "number": number})
    owner = data.get("user")
    project = owner.get("projectV2") if owner else None
    if not project:
        raise RuntimeError(
            f"Project {PROJECT_OWNER}/{number} was not found or is not accessible."
        )
    if PROJECT_TITLE and project["title"] != PROJECT_TITLE:
        raise RuntimeError(
            f"Deterministic Project title check failed: expected {PROJECT_TITLE!r}, "
            f"got {project['title']!r}."
        )
    if not project.get("viewerCanUpdate"):
        raise RuntimeError(
            f"Project {PROJECT_OWNER}/{number} is readable but not writable "
            "by the configured token."
        )
    return project


def field_by_name(project: dict[str, Any], name: str, typename: str) -> dict[str, Any] | None:
    for field in project["fields"]["nodes"]:
        if field.get("name") == name:
            if field.get("__typename") != typename:
                raise RuntimeError(
                    f"Project field {name!r} exists as {field.get('__typename')}, "
                    f"expected {typename}."
                )
            return field
    return None


def create_field(project_id: str, field_input: dict[str, object]) -> dict[str, Any]:
    query = """
    mutation($input:CreateProjectV2FieldInput!) {
      createProjectV2Field(input:$input) {
        projectV2Field {
          __typename
          ... on ProjectV2Field { id name }
          ... on ProjectV2IterationField {
            id name
            configuration {
              startDay
              duration
              iterations { id title startDate duration }
            }
          }
          ... on ProjectV2SingleSelectField {
            id name
            options { id name description color }
          }
        }
      }
    }
    """
    # Do not retry create mutations: an unknown response could have already
    # created the field, and replaying it could create duplicates.
    data = graphql(query, {"input": field_input}, retryable=False)
    return data["createProjectV2Field"]["projectV2Field"]


def update_iteration_field(
    project_id: str,
    field_id: str,
    configuration: dict[str, object],
) -> dict[str, Any]:
    query = """
    mutation($input:UpdateProjectV2FieldInput!) {
      updateProjectV2Field(input:$input) {
        projectV2Field {
          ... on ProjectV2IterationField {
            id
            name
            configuration {
              startDay
              duration
              iterations { id title startDate duration }
            }
          }
        }
      }
    }
    """
    data = graphql(
        query,
        {
            "input": {
                "fieldId": field_id,
                "iterationConfiguration": configuration,
            }
        },
    )
    return data["updateProjectV2Field"]["projectV2Field"]


def update_single_select_field(
    field_id: str,
    options: list[dict[str, object]],
) -> None:
    query = """
    mutation($input:UpdateProjectV2FieldInput!) {
      updateProjectV2Field(input:$input) {
        projectV2Field {
          ... on ProjectV2SingleSelectField { id name options { id name } }
        }
      }
    }
    """
    graphql(
        query,
        {"input": {"fieldId": field_id, "singleSelectOptions": options}},
    )


def ensure_schema(project: dict[str, Any]) -> dict[str, Any]:
    fields = {field["name"]: field for field in project["fields"]["nodes"]}

    if START_FIELD not in fields:
        create_field(
            project["id"],
            {"projectId": project["id"], "name": START_FIELD, "dataType": "DATE"},
        )
    elif fields[START_FIELD]["__typename"] != "ProjectV2Field":
        raise RuntimeError(f"{START_FIELD!r} exists but is not a DATE project field.")

    if END_FIELD not in fields:
        create_field(
            project["id"],
            {"projectId": project["id"], "name": END_FIELD, "dataType": "DATE"},
        )
    elif fields[END_FIELD]["__typename"] != "ProjectV2Field":
        raise RuntimeError(f"{END_FIELD!r} exists but is not a DATE project field.")

    if TEAM_FIELD not in fields:
        create_field(
            project["id"],
            {
                "projectId": project["id"],
                "name": TEAM_FIELD,
                "dataType": "SINGLE_SELECT",
                "singleSelectOptions": [
                    {"name": "Backend", "description": "PASI backend phase", "color": "GRAY"},
                    {"name": "Frontend", "description": "PASI frontend phase", "color": "GRAY"},
                ],
            },
        )

    if QUARTER_FIELD not in fields:
        create_field(
            project["id"],
            {
                "projectId": project["id"],
                "name": QUARTER_FIELD,
                "dataType": "SINGLE_SELECT",
                "singleSelectOptions": [
                    {"name": name, "description": f"PASI quarter {name}", "color": "GRAY"}
                    for name in sorted({info["quarter"] for info in PHASES.values()})
                ],
            },
        )

    for field_name in (
        DESCRIPTION_FIELD,
        RELATIONSHIP_FIELD,
        DEVELOPMENT_MILESTONE_FIELD,
    ):
        if field_name not in fields:
            create_field(
                project["id"],
                {"projectId": project["id"], "name": field_name, "dataType": "TEXT"},
            )
        elif fields[field_name]["__typename"] != "ProjectV2Field":
            raise RuntimeError(
                f"{field_name!r} exists but is not a TEXT project field."
            )

    if ITERATION_FIELD not in fields:
        iterations = [
            {
                "title": info["iteration"],
                "startDate": info["start"],
                "duration": (
                    date.fromisoformat(info["end"]) - date.fromisoformat(info["start"])
                ).days + 1,
            }
            for info in PHASES.values()
        ]
        create_field(
            project["id"],
            {
                "projectId": project["id"],
                "name": ITERATION_FIELD,
                "dataType": "ITERATION",
                "iterationConfiguration": {
                    "startDate": iterations[0]["startDate"],
                    "duration": iterations[0]["duration"],
                    "iterations": iterations,
                },
            },
        )

    # Re-read after field creation.
    project = project_snapshot()
    fields = {field["name"]: field for field in project["fields"]["nodes"]}

    team = field_by_name(project, TEAM_FIELD, "ProjectV2SingleSelectField")
    quarter = field_by_name(project, QUARTER_FIELD, "ProjectV2SingleSelectField")
    iteration = field_by_name(project, ITERATION_FIELD, "ProjectV2IterationField")
    status = field_by_name(project, STATUS_FIELD, "ProjectV2SingleSelectField")

    if not team or not quarter or not iteration or not status:
        raise RuntimeError("Required PASI Project fields could not be resolved.")

    status_names = {normalize_status_name(option["name"]) for option in status["options"]}
    desired_statuses = (STATUS_TODO, "In Progress", STATUS_DONE)
    missing_statuses = [
        name
        for name in desired_statuses
        if normalize_status_name(name) not in status_names
    ]
    if missing_statuses:
        options = list(status["options"])
        for name in missing_statuses:
            options.append({
                "name": name,
                "description": f"PASI project status {name}",
                "color": "GRAY",
            })
        update_single_select_field(status["id"], options)
        project = project_snapshot()
        status = field_by_name(project, STATUS_FIELD, "ProjectV2SingleSelectField")

    if not status:
        raise RuntimeError("Required PASI Project Status field could not be resolved after reconciliation.")

    remaining_statuses = {
        normalize_status_name(option["name"]) for option in status["options"]
    }
    still_missing = [
        name
        for name in desired_statuses
        if normalize_status_name(name) not in remaining_statuses
    ]
    if still_missing:
        raise RuntimeError(
            "PASI Project Status field is missing required options after reconciliation: "
            + ", ".join(still_missing)
        )

    # Reconcile Team/Quarter options while preserving existing option IDs.
    desired_team = ["Backend", "Frontend"]
    existing_team = {option["name"] for option in team["options"]}
    missing_team = [name for name in desired_team if name not in existing_team]
    if missing_team:
        options = list(team["options"]) + [
            {"name": name, "description": f"PASI {name.lower()} phase", "color": "GRAY"}
            for name in missing_team
        ]
        update_single_select_field(team["id"], options)
        project = project_snapshot()
        team = field_by_name(project, TEAM_FIELD, "ProjectV2SingleSelectField")

    desired_quarters = sorted({info["quarter"] for info in PHASES.values()})
    existing_quarters = {option["name"] for option in quarter["options"]}
    missing_quarters = [name for name in desired_quarters if name not in existing_quarters]
    if missing_quarters:
        options = list(quarter["options"]) + [
            {"name": name, "description": f"PASI quarter {name}", "color": "GRAY"}
            for name in missing_quarters
        ]
        update_single_select_field(quarter["id"], options)
        project = project_snapshot()
        quarter = field_by_name(project, QUARTER_FIELD, "ProjectV2SingleSelectField")

    expected_iterations = [
        {
            "title": info["iteration"],
            "startDate": info["start"],
            "duration": (
                date.fromisoformat(info["end"]) - date.fromisoformat(info["start"])
            ).days + 1,
        }
        for info in PHASES.values()
    ]
    current_iterations = iteration["configuration"]["iterations"]

    if current_iterations != expected_iterations:
        update_iteration_field(
            project["id"],
            iteration["id"],
            {
                "startDate": expected_iterations[0]["startDate"],
                "duration": expected_iterations[0]["duration"],
                "iterations": expected_iterations,
            },
        )
        project = project_snapshot()
        iteration = field_by_name(project, ITERATION_FIELD, "ProjectV2IterationField")

    if iteration is None:
        raise RuntimeError("Required PASI Project iteration field could not be resolved after reconciliation.")

    actual_by_title = {
        item["title"]: item for item in iteration["configuration"]["iterations"]
    }
    for expected in expected_iterations:
        actual = actual_by_title.get(expected["title"])
        if not actual or actual["startDate"] != expected["startDate"] or actual["duration"] != expected["duration"]:
            raise RuntimeError(
                f"Iteration reconciliation failed for {expected['title']}."
            )

    return project_snapshot()


def update_item_field(
    project_id: str,
    item_id: str,
    field_id: str,
    value: dict[str, object],
) -> None:
    query = """
    mutation($input:UpdateProjectV2ItemFieldValueInput!) {
      updateProjectV2ItemFieldValue(input:$input) {
        projectV2Item { id }
      }
    }
    """
    graphql(
        query,
        {
            "input": {
                "projectId": project_id,
                "itemId": item_id,
                "fieldId": field_id,
                "value": value,
            }
        },
    )


def add_item(project_id: str, content_id: str) -> str:
    query = """
    mutation($project:ID!, $content:ID!) {
      addProjectV2ItemById(input:{projectId:$project, contentId:$content}) {
        item { id }
      }
    }
    """
    data = graphql(query, {"project": project_id, "content": content_id})
    return data["addProjectV2ItemById"]["item"]["id"]


def all_frontend_phase_issues() -> list[dict[str, Any]]:
    raw = run_gh(
        [
            "api",
            f"repos/{REPO}/issues?state=all&per_page=100",
            "--paginate",
            "--jq",
            (
                ".[] | select(.pull_request == null) | "
                "{number,title,state,body,labels:[.labels[].name]}"
            ),
        ]
    )
    issues: list[dict[str, Any]] = []
    for line in raw.splitlines():
        if line.strip():
            issues.append(json.loads(line))
    return issues


def resolve_frontend_phase_map() -> tuple[dict[str, int], set[str]]:
    candidates: dict[str, list[dict[str, Any]]] = {phase: [] for phase in PHASES}
    for issue in all_frontend_phase_issues():
        title = str(issue.get("title") or "")
        declared_title = FRONTEND_PHASE_TITLE_RE.match(title)
        body = issue.get("body") or ""
        declared_metadata: str | None = None
        if "PASI_PROJECT_METADATA" in body:
            try:
                metadata = parse_metadata(body)
            except ValueError:
                metadata = None
            else:
                if metadata.issue_type == "frontend":
                    declared_metadata = metadata.phase

        phases = {phase for phase in (declared_title.group("phase") if declared_title else None, declared_metadata) if phase}
        for phase in phases:
            if phase in candidates:
                candidates[phase].append(issue)

    resolved: dict[str, int] = {}
    invalid: set[str] = set()

    for phase, expected_issue in FRONTEND_PHASE_ISSUES.items():
        phase_candidates = candidates[phase]
        if not phase_candidates:
            print(
                f"::warning::FE-{phase} mapping skipped: no unique frontend phase issue found "
                f"(expected canonical issue #{expected_issue})."
            )
            invalid.add(phase)
            continue

        unique_numbers = sorted({int(issue["number"]) for issue in phase_candidates})
        if len(unique_numbers) != 1:
            print(
                f"::warning::FE-{phase} mapping skipped: duplicate frontend phase issues "
                f"detected at #{', #'.join(str(number) for number in unique_numbers)}."
            )
            invalid.add(phase)
            continue

        issue = phase_candidates[0]
        actual_issue = int(issue["number"])
        title = str(issue.get("title") or "")
        title_match = FRONTEND_PHASE_TITLE_RE.match(title)

        if actual_issue != expected_issue:
            print(
                f"::warning::FE-{phase} mapping skipped: canonical issue #{expected_issue} "
                f"is not the unique FE-{phase} issue; discovered issue #{actual_issue} instead."
            )
            invalid.add(phase)
            continue

        if not title_match or title_match.group("phase") != phase:
            print(
                f"::warning::FE-{phase} mapping skipped: canonical issue #{expected_issue} "
                f"has been renamed and no longer carries the FE-{phase} phase identity."
            )
            invalid.add(phase)
            continue

        labels = set(issue.get("labels") or [])
        if "frontend" not in labels or "roadmap" not in labels:
            print(
                f"::warning::FE-{phase} mapping skipped: canonical issue #{expected_issue} "
                f"is missing required frontend/roadmap labels."
            )
            invalid.add(phase)
            continue

        resolved[phase] = actual_issue

    return resolved, invalid


def normalize_status_name(name: str) -> str:
    return re.sub(r"\\s+", " ", name.strip()).casefold()


def project_status_option(project: dict[str, Any], status_name: str) -> dict[str, Any]:
    status = field_by_name(project, STATUS_FIELD, "ProjectV2SingleSelectField")
    if not status:
        raise RuntimeError("Required PASI Project Status field could not be resolved.")
    option = next(
        (
            option
            for option in status["options"]
            if normalize_status_name(option["name"]) == normalize_status_name(status_name)
        ),
        None,
    )
    if not option:
        raise RuntimeError(f"PASI Project Status option {status_name!r} is unavailable.")
    return option


def set_project_status(project: dict[str, Any], item_id: str, status_name: str) -> None:
    option = project_status_option(project, status_name)
    status = field_by_name(project, STATUS_FIELD, "ProjectV2SingleSelectField")
    if not status:
        raise RuntimeError("Required PASI Project Status field could not be resolved.")
    update_item_field(
        project["id"],
        item_id,
        status["id"],
        {"singleSelectOptionId": option["id"]},
    )


def sync_frontend_statuses(
    project: dict[str, Any],
    items: dict[int, dict[str, Any]],
    issue_states: dict[int, str],
    resolved_phase_issues: dict[str, int],
) -> None:
    event_issue = int(PROJECT_EVENT_ISSUE_NUMBER_RAW) if PROJECT_EVENT_ISSUE_NUMBER_RAW.isdigit() else None
    for phase, issue_number in resolved_phase_issues.items():
        item = items.get(issue_number)
        if not item:
            continue
        current = (item.get("status") or {}).get("name")
        desired = current or STATUS_TODO
        if issue_states.get(issue_number, "").upper() == "CLOSED":
            desired = STATUS_DONE
        elif PROJECT_EVENT_ACTION == "reopened" and event_issue == issue_number:
            desired = STATUS_TODO
        if desired not in {STATUS_TODO, "In Progress", STATUS_DONE}:
            raise RuntimeError(
                f"Unsupported Project Status {desired!r} for frontend phase {phase} (#{issue_number})."
            )
        if current != desired:
            set_project_status(project, item["id"], desired)
            print(f"Synced #{issue_number} {phase} Project Status: {current!r} -> {desired!r}")


def synchronize_frontend_roadmap_checkboxes(
    body: str,
    project_items_by_number: dict[int, dict[str, Any]],
    resolved_phase_issues: dict[str, int],
    invalid_phases: set[str],
) -> str:
    pattern = re.compile(
        r"^(?P<prefix>\s*-\s*)\[(?P<checked>[ xX])\](?P<rest>\s+\[FE-P(?P<phase>\d+)\s+—[^\n]*\]\(https://github\.com/th3-st0v3/personal-ai-system/issues/(?P<issue>\d+)\))\s*$",
        re.MULTILINE,
    )
    seen: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        phase = f"P{match.group('phase')}"
        issue_number = int(match.group("issue"))
        if phase in invalid_phases:
            print(
                f"::warning::FE-{phase} roadmap checkbox skipped because its phase issue mapping is invalid."
            )
            seen.add(phase)
            return match.group(0)
        resolved_issue = resolved_phase_issues.get(phase)
        if resolved_issue != issue_number:
            raise RuntimeError(
                f"Frontend roadmap mapping drifted for FE-{phase}: expected resolved issue "
                f"#{resolved_issue}, got #{issue_number}."
            )
        status_name = (project_items_by_number.get(issue_number, {}).get("status") or {}).get("name")
        checked = status_name == STATUS_DONE
        seen.add(phase)
        return f"{match.group('prefix')}[{'x' if checked else ' '}]"+match.group("rest")

    updated = pattern.sub(replace, body)
    missing = sorted(set(FRONTEND_PHASE_ISSUES) - seen, key=lambda value: int(value[1:]))
    if missing:
        raise RuntimeError(
            "Frontend roadmap is missing checkbox mappings for: " + ", ".join(f"FE-{phase}" for phase in missing)
        )
    return updated


def verify_frontend_roadmap_checkboxes(
    body: str,
    project_items_by_number: dict[int, dict[str, Any]],
    resolved_phase_issues: dict[str, int],
    invalid_phases: set[str],
) -> None:
    expected = synchronize_frontend_roadmap_checkboxes(
        body, project_items_by_number, resolved_phase_issues, invalid_phases
    )
    if expected != body:
        raise RuntimeError("Frontend roadmap checkbox state is out of sync with Project Status.")


def apply_roadmap_form_to_item(
    project: dict[str, Any],
    item_id: str,
    form: RoadmapForm,
    issue_number: int,
    title: str,
) -> dict[str, Any]:
    project = ensure_schema(project)
    fields = {field["name"]: field for field in project["fields"]["nodes"]}

    update_item_field(
        project["id"], item_id, fields[DESCRIPTION_FIELD]["id"], {"text": form.description}
    )
    update_item_field(
        project["id"], item_id, fields[START_FIELD]["id"], {"date": form.start_date}
    )
    update_item_field(
        project["id"], item_id, fields[END_FIELD]["id"], {"date": form.end_date}
    )
    update_item_field(
        project["id"], item_id, fields[RELATIONSHIP_FIELD]["id"], {"text": form.relationship}
    )
    update_item_field(
        project["id"],
        item_id,
        fields[DEVELOPMENT_MILESTONE_FIELD]["id"],
        {"text": form.development_milestone},
    )
    status = field_by_name(project, STATUS_FIELD, "ProjectV2SingleSelectField")
    if not status:
        raise RuntimeError("Required PASI Project Status field could not be resolved.")
    status_option = next(
        (
            option
            for option in status["options"]
            if normalize_status_name(option["name"]) == normalize_status_name(form.status)
        ),
        None,
    )
    if not status_option:
        raise RuntimeError(
            f"PASI Project Status option {form.status!r} is unavailable."
        )
    update_item_field(
        project["id"],
        item_id,
        status["id"],
        {"singleSelectOptionId": status_option["id"]},
    )
    print(f"Synced roadmap form #{issue_number} {title} -> {form.status}")
    return project


def apply_metadata_to_item(
    project: dict[str, Any],
    item_id: str,
    metadata: Metadata,
    issue_number: int,
    title: str,
) -> dict[str, Any]:
    project = ensure_schema(project)
    fields = {field["name"]: field for field in project["fields"]["nodes"]}

    team_option = next(
        (option for option in fields[TEAM_FIELD]["options"] if option["name"] == metadata.team),
        None,
    )
    quarter_option = next(
        (option for option in fields[QUARTER_FIELD]["options"] if option["name"] == metadata.quarter),
        None,
    )
    iteration = next(
        (
            item
            for item in fields[ITERATION_FIELD]["configuration"]["iterations"]
            if item["title"] == metadata.iteration
        ),
        None,
    )
    if not team_option or not quarter_option or not iteration:
        raise RuntimeError(f"Project options are incomplete for {metadata.phase}.")

    update_item_field(
        project["id"], item_id, fields[START_FIELD]["id"], {"date": metadata.start_date}
    )
    update_item_field(
        project["id"], item_id, fields[END_FIELD]["id"], {"date": metadata.end_date}
    )
    update_item_field(
        project["id"], item_id, fields[TEAM_FIELD]["id"],
        {"singleSelectOptionId": team_option["id"]},
    )
    update_item_field(
        project["id"], item_id, fields[QUARTER_FIELD]["id"],
        {"singleSelectOptionId": quarter_option["id"]},
    )
    update_item_field(
        project["id"], item_id, fields[ITERATION_FIELD]["id"],
        {"iterationId": iteration["id"]},
    )
    print(f"Synced #{issue_number} {title} -> {metadata.phase}/{metadata.iteration}")
    return project


def sync_issue(
    project: dict[str, Any],
    issue_number: int,
    existing_items: dict[int, dict[str, Any]],
) -> tuple[dict[str, Any], Metadata | None, RoadmapForm | None, str]:
    content_id, title, body, state = fetch_issue(issue_number)
    metadata = parse_metadata(body) if "PASI_PROJECT_METADATA" in body else None
    form = parse_roadmap_form(body)

    existing = existing_items.get(issue_number)
    if existing:
        item_id = existing["id"]
        membership_action = "already present"
    else:
        item_id = add_item(project["id"], content_id)
        membership_action = "added"

    if metadata is not None:
        project = apply_metadata_to_item(project, item_id, metadata, issue_number, title)

    if form is not None:
        # Explicit close/reopen events take precedence over a stale form Status.
        if PROJECT_EVENT_ACTION == "closed" or state.upper() == "CLOSED":
            form = RoadmapForm(
                description=form.description,
                start_date=form.start_date,
                end_date=form.end_date,
                relationship=form.relationship,
                development_milestone=form.development_milestone,
                status=STATUS_DONE,
            )
        elif PROJECT_EVENT_ACTION == "reopened":
            form = RoadmapForm(
                description=form.description,
                start_date=form.start_date,
                end_date=form.end_date,
                relationship=form.relationship,
                development_milestone=form.development_milestone,
                status=STATUS_TODO,
            )
        project = apply_roadmap_form_to_item(project, item_id, form, issue_number, title)

    if metadata is None and form is None:
        print(
            f"Project membership {membership_action}: #{issue_number} {title} "
            "(no PASI metadata block or roadmap form)."
        )

    return project, metadata, form, state


def all_metadata_issue_numbers() -> list[int]:
    endpoint = f"repos/{REPO}/issues?state=all&per_page=100"
    raw = run_gh(
        [
            "api",
            endpoint,
            "--paginate",
            "--jq",
            '.[] | select(.body != null) | select(.body | contains("PASI_PROJECT_METADATA")) | .number',
        ]
    )
    return sorted({int(line) for line in raw.splitlines() if line.strip()})


def metadata_for_issue(issue_number: int) -> Metadata:
    _, _, body, _ = fetch_issue(issue_number)
    return parse_metadata(body)


def project_items(project: dict[str, Any], field_names: dict[str, str]) -> dict[int, dict[str, Any]]:
    query = """
    query(
      $project:ID!,
      $after:String,
      $startField:String!,
      $endField:String!,
      $teamField:String!,
      $quarterField:String!,
      $iterationField:String!,
      $statusField:String!,
      $descriptionField:String!,
      $relationshipField:String!,
      $developmentMilestoneField:String!
    ) {
      node(id:$project) {
        ... on ProjectV2 {
          items(first:100, after:$after) {
            pageInfo { hasNextPage endCursor }
            nodes {
              id
              content {
                __typename
                ... on Issue {
                  number
                  repository { nameWithOwner }
                }
              }
              start: fieldValueByName(name:$startField) {
                ... on ProjectV2ItemFieldDateValue { date }
              }
              end: fieldValueByName(name:$endField) {
                ... on ProjectV2ItemFieldDateValue { date }
              }
              team: fieldValueByName(name:$teamField) {
                ... on ProjectV2ItemFieldSingleSelectValue { name }
              }
              quarter: fieldValueByName(name:$quarterField) {
                ... on ProjectV2ItemFieldSingleSelectValue { name }
              }
              iteration: fieldValueByName(name:$iterationField) {
                ... on ProjectV2ItemFieldIterationValue {
                  iterationId
                  title
                  startDate
                  duration
                }
              }
              status: fieldValueByName(name:$statusField) {
                ... on ProjectV2ItemFieldSingleSelectValue {
                  optionId
                  name
                }
              }
              description: fieldValueByName(name:$descriptionField) {
                ... on ProjectV2ItemFieldTextValue { text }
              }
              relationship: fieldValueByName(name:$relationshipField) {
                ... on ProjectV2ItemFieldTextValue { text }
              }
              developmentMilestone: fieldValueByName(name:$developmentMilestoneField) {
                ... on ProjectV2ItemFieldTextValue { text }
              }
            }
          }
        }
      }
    }
    """
    after: str | None = None
    found: dict[int, dict[str, Any]] = {}

    while True:
        variables = {
            "project": project["id"],
            "after": after,
            **field_names,
        }
        data = graphql(query, variables)
        page = data["node"]["items"]
        for item in page["nodes"]:
            content = item.get("content")
            if not content or content.get("__typename") != "Issue":
                continue
            if content.get("repository", {}).get("nameWithOwner") != REPO:
                continue
            found[int(content["number"])] = item
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]

    return found


def verify_roadmap_form(
    project_items_by_number: dict[int, dict[str, Any]],
    issue_number: int,
    form: RoadmapForm,
) -> None:
    item = project_items_by_number.get(issue_number)
    if not item:
        raise RuntimeError(
            f"Project verification failed: issue #{issue_number} is not in the Project."
        )

    checks = [
        ("Description", item.get("description", {}).get("text"), form.description),
        ("Start Date", item.get("start", {}).get("date"), form.start_date),
        ("End Date", item.get("end", {}).get("date"), form.end_date),
        ("Relationship", item.get("relationship", {}).get("text"), form.relationship),
        (
            "Development Milestone",
            item.get("developmentMilestone", {}).get("text"),
            form.development_milestone,
        ),
        ("Status", item.get("status", {}).get("name"), form.status),
    ]
    mismatches = [
        f"{name}: expected {expected!r}, got {actual!r}"
        for name, actual, expected in checks
        if actual != expected
    ]
    if mismatches:
        raise RuntimeError(
            f"Project form verification failed for #{issue_number}: "
            + "; ".join(mismatches)
        )


def verify_issue(project_items_by_number: dict[int, dict[str, Any]], issue_number: int, metadata: Metadata) -> None:
    item = project_items_by_number.get(issue_number)
    if not item:
        raise RuntimeError(f"Project verification failed: issue #{issue_number} is not in the Project.")

    checks = [
        ("Start Date", item.get("start", {}).get("date"), metadata.start_date),
        ("End Date", item.get("end", {}).get("date"), metadata.end_date),
        ("Team", item.get("team", {}).get("name"), metadata.team),
        ("Quarter", item.get("quarter", {}).get("name"), metadata.quarter),
        ("Iteration", item.get("iteration", {}).get("title"), metadata.iteration),
    ]
    mismatches = [
        f"{name}: expected {expected!r}, got {actual!r}"
        for name, actual, expected in checks
        if actual != expected
    ]
    if mismatches:
        raise RuntimeError(
            f"Project verification failed for #{issue_number}: " + "; ".join(mismatches)
        )


def synchronize(issue_numbers: list[int]) -> None:
    project = ensure_schema(project_snapshot())
    resolved_phase_issues, invalid_frontend_phases = resolve_frontend_phase_map()
    canonical_frontend_issue_numbers = set(FRONTEND_PHASE_ISSUES.values())
    issue_numbers = sorted(
        (set(issue_numbers) - canonical_frontend_issue_numbers)
        | set(resolved_phase_issues.values())
        | {FRONTEND_ROADMAP_ISSUE}
    )
    field_names = {
        "startField": START_FIELD,
        "endField": END_FIELD,
        "teamField": TEAM_FIELD,
        "quarterField": QUARTER_FIELD,
        "iterationField": ITERATION_FIELD,
        "statusField": STATUS_FIELD,
        "descriptionField": DESCRIPTION_FIELD,
        "relationshipField": RELATIONSHIP_FIELD,
        "developmentMilestoneField": DEVELOPMENT_MILESTONE_FIELD,
    }
    existing_items = project_items(project, field_names)
    metadata_by_issue: dict[int, Metadata] = {}
    form_by_issue: dict[int, RoadmapForm] = {}
    issue_states: dict[int, str] = {}

    for issue_number in issue_numbers:
        project, metadata, form, state = sync_issue(project, issue_number, existing_items)
        issue_states[issue_number] = state
        if metadata is not None:
            metadata_by_issue[issue_number] = metadata
        if form is not None:
            form_by_issue[issue_number] = form

    project = project_snapshot()
    items = project_items(project, field_names)
    frontend_states = {
        issue_number: issue_states.get(issue_number) or fetch_issue(issue_number)[3]
        for issue_number in resolved_phase_issues.values()
        if issue_number in items
    }
    sync_frontend_statuses(project, items, frontend_states, resolved_phase_issues)

    project = project_snapshot()
    items = project_items(project, field_names)
    _, _, roadmap_body, _ = fetch_issue(FRONTEND_ROADMAP_ISSUE)
    updated_body = synchronize_frontend_roadmap_checkboxes(
        roadmap_body,
        items,
        resolved_phase_issues,
        invalid_frontend_phases,
    )
    if updated_body != roadmap_body:
        update_issue_body(FRONTEND_ROADMAP_ISSUE, updated_body)
        print(f"Synchronized FE roadmap #{FRONTEND_ROADMAP_ISSUE} checkboxes from Project Status.")

    errors: list[str] = []
    for issue_number in issue_numbers:
        if issue_number not in items:
            errors.append(
                f"Project verification failed: issue #{issue_number} is not in the Project."
            )

    if metadata_by_issue or form_by_issue:
        fields = {field["name"]: field for field in project["fields"]["nodes"]}
        missing_fields = [name for name in field_names.values() if name not in fields]
        if missing_fields:
            errors.append(
                f"Metadata verification cannot run; missing Project fields: {missing_fields}"
            )
        else:
            expected_iterations = PHASES
            iteration_field = fields[ITERATION_FIELD]
            actual_iterations = iteration_field["configuration"]["iterations"]
            for phase, expected in expected_iterations.items():
                actual = next(
                    (value for value in actual_iterations if value["title"] == expected["iteration"]),
                    None,
                )
                expected_duration = (
                    date.fromisoformat(expected["end"]) - date.fromisoformat(expected["start"])
                ).days + 1
                if (
                    not actual
                    or actual["startDate"] != expected["start"]
                    or actual["duration"] != expected_duration
                ):
                    errors.append(
                        f"Post-sync verification failed for {expected['iteration']}."
                    )

            for issue_number, metadata in metadata_by_issue.items():
                try:
                    verify_issue(items, issue_number, metadata)
                except RuntimeError as exc:
                    errors.append(str(exc))

            for issue_number, form in form_by_issue.items():
                try:
                    verify_roadmap_form(items, issue_number, form)
                except RuntimeError as exc:
                    errors.append(str(exc))

    try:
        _, _, roadmap_body, _ = fetch_issue(FRONTEND_ROADMAP_ISSUE)
        verify_frontend_roadmap_checkboxes(
            roadmap_body,
            items,
            resolved_phase_issues,
            invalid_frontend_phases,
        )
        for phase, issue_number in resolved_phase_issues.items():
            item = items.get(issue_number)
            if not item:
                errors.append(
                    f"Frontend Project verification failed: FE-{phase} issue #{issue_number} is not in the Project."
                )
                continue
            status_name = (item.get("status") or {}).get("name")
            if status_name not in {STATUS_TODO, "In Progress", STATUS_DONE}:
                errors.append(
                    f"Frontend Project verification failed for FE-{phase}: invalid Status {status_name!r}."
                )

        if invalid_frontend_phases:
            print(
                "::warning::FE roadmap automation skipped invalid phase mappings: "
                + ", ".join(f"FE-{phase}" for phase in sorted(invalid_frontend_phases, key=lambda value: int(value[1:])))
            )
    except RuntimeError as exc:
        errors.append(str(exc))

    if errors:
        raise RuntimeError(
            "Post-sync verification failed:\n- " + "\n- ".join(errors)
        )

    print(
        f"POST-SYNC VERIFICATION PASSED: {len(issue_numbers)} issue(s) in Project; "
        f"{len(metadata_by_issue)} phase issue(s) formatted."
    )


def all_roadmap_issue_numbers() -> list[int]:
    endpoint = f"repos/{REPO}/issues?state=all&labels=roadmap&per_page=100"
    raw = run_gh(
        [
            "api",
            endpoint,
            "--paginate",
            "--jq",
            '.[] | select(.pull_request == null) | .number',
        ]
    )
    return sorted({int(line) for line in raw.splitlines() if line.strip()})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("issue", nargs="?", type=int)
    parser.add_argument(
        "--complete-frontend",
        type=int,
        help="Synchronize a completed FE-P0..FE-P22 phase and its parent roadmap checkbox.",
    )
    parser.add_argument("--all", action="store_true", help="Synchronize all issues carrying PASI metadata.")
    parser.add_argument("--roadmap", action="store_true", help="Add all roadmap-labeled issues to the Project and format phase metadata where present.")
    args = parser.parse_args()

    selected_modes = [
        bool(args.issue),
        bool(args.complete_frontend),
        args.all,
        args.roadmap,
    ]
    if sum(selected_modes) > 1:
        raise SystemExit(
            "Use only one of issue number, --complete-frontend, --all, or --roadmap."
        )

    if args.complete_frontend is not None:
        phase = next(
            (
                phase
                for phase, issue_number in FRONTEND_PHASE_ISSUES.items()
                if issue_number == args.complete_frontend
            ),
            None,
        )
        if phase is None:
            raise SystemExit(
                f"Issue #{args.complete_frontend} is not a PASI FE-P0..FE-P22 phase."
            )
        completion_record = next(
            (
                issue
                for issue in all_frontend_phase_issues()
                if int(issue["number"]) == args.complete_frontend
            ),
            None,
        )
        if completion_record is None:
            print(
                f"::warning::FE-{phase} completion skipped: canonical issue #{args.complete_frontend} "
                "is missing from the repository."
            )
            return
        if str(completion_record.get("state", "")).upper() != "CLOSED":
            raise SystemExit(
                f"FE-{phase} issue #{args.complete_frontend} is not closed; completion sync requires state=closed."
            )
        print(
            f"Completing FE-{phase}: Project Status -> Done and parent FE roadmap checkbox -> [x]."
        )
        numbers = [args.complete_frontend]
    elif args.roadmap:
        numbers = all_roadmap_issue_numbers()
    elif args.all:
        numbers = all_metadata_issue_numbers()
    elif args.issue:
        numbers = [args.issue]
    else:
        raise SystemExit("Provide an issue number, --complete-frontend, --all, or --roadmap")

    if not numbers:
        raise SystemExit("No matching issues were found.")

    synchronize(numbers)


if __name__ == "__main__":
    main()
