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

START_FIELD = "Start Date"
END_FIELD = "End Date"
TEAM_FIELD = "Team"
QUARTER_FIELD = "Quarter"
ITERATION_FIELD = "Iteration"

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


def fetch_issue(issue_number: int) -> tuple[str, str, str]:
    query = """
    query($owner:String!, $repo:String!, $number:Int!) {
      repository(owner:$owner, name:$repo) {
        issue(number:$number) {
          id
          number
          title
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
    return issue["id"], issue["title"], issue.get("body") or ""


def project_snapshot() -> dict[str, Any]:
    number = validate_project_number()
    query = """
    query($login:String!, $number:Int!) {
      user(login:$login) {
        projectV2(number:$number) {
          id
          number
          title
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

    if not team or not quarter or not iteration:
        raise RuntimeError("Required PASI Project fields could not be resolved.")

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


def sync_issue(
    project: dict[str, Any],
    metadata: Metadata,
    issue_number: int,
) -> None:
    content_id, title, body = fetch_issue(issue_number)
    parsed = parse_metadata(body)
    if parsed != metadata:
        raise RuntimeError("Issue metadata changed between validation and synchronization.")

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

    item_id = add_item(project["id"], content_id)
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
    _, _, body = fetch_issue(issue_number)
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
      $iterationField:String!
    ) {
      node(id:$project) {
        ... on ProjectV2 {
          items(first:100, after:$after) {
            pageInfo { hasNextPage endCursor }
            nodes {
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
    project = project_snapshot()
    metadata_by_issue = {
        issue_number: metadata_for_issue(issue_number)
        for issue_number in issue_numbers
    }

    for issue_number, metadata in metadata_by_issue.items():
        sync_issue(project, metadata, issue_number)

    project = project_snapshot()
    fields = {field["name"]: field for field in project["fields"]["nodes"]}
    field_names = {
        "startField": START_FIELD,
        "endField": END_FIELD,
        "teamField": TEAM_FIELD,
        "quarterField": QUARTER_FIELD,
        "iterationField": ITERATION_FIELD,
    }
    missing_fields = [name for name in field_names.values() if name not in fields]
    if missing_fields:
        raise RuntimeError(
            f"Post-sync verification cannot run; missing Project fields: {missing_fields}"
        )

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
        if not actual or actual["startDate"] != expected["start"] or actual["duration"] != expected_duration:
            raise RuntimeError(
                f"Post-sync verification failed for {expected['iteration']}."
            )

    items = project_items(project, field_names)
    errors: list[str] = []
    for issue_number, metadata in metadata_by_issue.items():
        try:
            verify_issue(items, issue_number, metadata)
        except RuntimeError as exc:
            errors.append(str(exc))

    if errors:
        raise RuntimeError(
            "Post-sync verification failed:\n- " + "\n- ".join(errors)
        )

    print(
        f"POST-SYNC VERIFICATION PASSED: {len(metadata_by_issue)} issue(s), "
        f"{len(actual_iterations)} configured iteration(s)."
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("issue", nargs="?", type=int)
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    if args.all:
        numbers = all_metadata_issue_numbers()
    elif args.issue:
        numbers = [args.issue]
    else:
        raise SystemExit("Provide an issue number or --all")

    if not numbers:
        raise SystemExit("No issues with PASI_PROJECT_METADATA were found.")

    synchronize(numbers)


if __name__ == "__main__":
    main()
