#!/usr/bin/env python3
"""Synchronize PASI phase metadata into a GitHub Project v2."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import date

REPO = "th3-st0v3/personal-ai-system"
PROJECT_QUERY = os.environ.get("PASI_PROJECT_QUERY", "PASI")
PROJECT_TITLE = os.environ.get("PASI_PROJECT_TITLE", "").strip()

META_RE = re.compile(
    r"<!--\s*PASI_PROJECT_METADATA\s*\n(?P<body>.*?)\nPASI_PROJECT_METADATA\s*-->",
    re.DOTALL,
)

PHASE_SCHEDULE = [
    ("P0", "Iteration 1", "2026-09-22", "2026-10-04"),
    ("P1", "Iteration 2", "2026-10-04", "2026-10-12"),
    ("P2", "Iteration 3", "2026-10-13", "2026-10-24"),
    ("P3", "Iteration 4", "2026-10-25", "2026-11-07"),
    ("P4", "Iteration 5", "2026-11-08", "2026-11-21"),
    ("P5", "Iteration 6", "2026-11-22", "2026-12-05"),
    ("P6", "Iteration 7", "2026-12-06", "2026-12-19"),
    ("P7", "Iteration 8", "2026-12-20", "2027-01-09"),
    ("P8", "Iteration 9", "2027-01-10", "2027-01-30"),
    ("P9", "Iteration 10", "2027-01-31", "2027-02-20"),
    ("P10", "Iteration 11", "2027-02-21", "2027-03-20"),
    ("P11", "Iteration 12", "2027-03-21", "2027-04-10"),
    ("P12", "Iteration 13", "2027-04-11", "2027-05-08"),
    ("P13", "Iteration 14", "2027-05-09", "2027-05-29"),
    ("P14", "Iteration 15", "2027-05-30", "2027-06-19"),
    ("P15", "Iteration 16", "2027-06-20", "2027-07-10"),
    ("P16", "Iteration 17", "2027-07-11", "2027-08-07"),
    ("P17", "Iteration 18", "2027-08-08", "2027-08-28"),
    ("P18", "Iteration 19", "2027-08-29", "2027-09-25"),
    ("P19", "Iteration 20", "2027-09-26", "2027-10-16"),
    ("P20", "Iteration 21", "2027-10-17", "2027-11-13"),
    ("P21", "Iteration 22", "2027-11-14", "2027-12-11"),
    ("P22", "Iteration 23", "2027-12-12", "2028-01-15"),
]


@dataclass(frozen=True)
class Metadata:
    phase: str
    issue_type: str
    iteration: str
    start_date: str
    end_date: str
    team: str
    quarter: str


def run_gh(args: list[str], *, input_text: str | None = None) -> str:
    proc = subprocess.run(
        ["gh", *args],
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def graphql(query: str, variables: dict[str, object] | None = None) -> dict[str, object]:
    payload = {"query": query, "variables": variables or {}}
    raw = run_gh(["api", "graphql", "--input", "-"], input_text=json.dumps(payload))
    response = json.loads(raw)
    if response.get("errors"):
        raise RuntimeError(json.dumps(response["errors"], indent=2))
    return response["data"]


def parse_metadata(body: str) -> Metadata:
    match = META_RE.search(body or "")
    if not match:
        raise ValueError("Issue body is missing PASI_PROJECT_METADATA")

    values: dict[str, str] = {}
    for line in match.group("body").splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            values[key.strip()] = value.strip()

    required = ["PHASE", "TYPE", "ITERATION", "START_DATE", "END_DATE", "TEAM", "QUARTER"]
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise ValueError(f"Missing planning metadata: {', '.join(missing)}")

    start = date.fromisoformat(values["START_DATE"])
    end = date.fromisoformat(values["END_DATE"])
    if end < start:
        raise ValueError(f"END_DATE precedes START_DATE for {values['PHASE']}")

    if values["TYPE"] not in {"backend", "frontend"}:
        raise ValueError(f"Unsupported TYPE: {values['TYPE']}")
    if values["TEAM"] not in {"Backend", "Frontend"}:
        raise ValueError(f"Unsupported TEAM: {values['TEAM']}")

    return Metadata(
        phase=values["PHASE"],
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
        issue(number:$number) { id number title body }
      }
    }
    """
    data = graphql(query, {"owner": "th3-st0v3", "repo": "personal-ai-system", "number": issue_number})
    issue = data["repository"]["issue"]  # type: ignore[index]
    return issue["id"], issue["title"], issue.get("body") or ""  # type: ignore[index]


def project_snapshot() -> dict[str, object]:
    query = """
    query($login:String!, $query:String!) {
      user(login:$login) {
        projectsV2(first:100, query:$query) {
          nodes {
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
                  options { id name }
                }
              }
            }
          }
        }
      }
    }
    """
    data = graphql(query, {"login": "th3-st0v3", "query": PROJECT_QUERY})
    projects = data["user"]["projectsV2"]["nodes"]  # type: ignore[index]
    if PROJECT_TITLE:
        matches = [p for p in projects if p["title"] == PROJECT_TITLE]
    else:
        matches = [p for p in projects if "pasi" in p["title"].lower()]
    if len(matches) != 1:
        names = ", ".join(p["title"] for p in matches) or "<none>"
        raise RuntimeError(
            f"Expected exactly one PASI Project; found {names}. "
            "Set PASI_PROJECT_TITLE to disambiguate."
        )
    return matches[0]


def create_field(project_id: str, field_input: dict[str, object]) -> dict[str, object]:
    query = """
    mutation($input:CreateProjectV2FieldInput!) {
      createProjectV2Field(input:$input) {
        projectV2Field {
          __typename
          ... on ProjectV2Field { id name }
          ... on ProjectV2IterationField {
            id name
            configuration { startDay duration iterations { id title startDate duration } }
          }
          ... on ProjectV2SingleSelectField {
            id name
            options { id name }
          }
        }
      }
    }
    """
    data = graphql(query, {"input": field_input})
    return data["createProjectV2Field"]["projectV2Field"]  # type: ignore[index]


def update_field(project_id: str, field_input: dict[str, object]) -> dict[str, object]:
    query = """
    mutation($input:UpdateProjectV2FieldInput!) {
      updateProjectV2Field(input:$input) {
        projectV2Field {
          __typename
          ... on ProjectV2IterationField {
            id name
            configuration { startDay duration iterations { id title startDate duration } }
          }
        }
      }
    }
    """
    data = graphql(query, {"input": {"fieldId": field_input["fieldId"], "iterationConfiguration": field_input["iterationConfiguration"]}})
    return data["updateProjectV2Field"]["projectV2Field"]  # type: ignore[index]


def find_field(project: dict[str, object], aliases: list[str]) -> dict[str, object] | None:
    fields = project["fields"]["nodes"]  # type: ignore[index]
    wanted = {alias.lower() for alias in aliases}
    for field in fields:
        if field.get("name", "").lower() in wanted:
            return field
    return None


def ensure_date_field(project: dict[str, object], name: str, aliases: list[str]) -> dict[str, object]:
    field = find_field(project, aliases)
    if field:
        return field
    return create_field(project["id"], {"projectId": project["id"], "name": name, "dataType": "DATE"})


def ensure_single_select(project: dict[str, object], name: str, options: list[str]) -> dict[str, object]:
    field = find_field(project, [name])
    if field:
        existing = {option["name"] for option in field.get("options", [])}
        missing = [option for option in options if option not in existing]
        if missing:
            update_single_select_field(project["id"], field["id"], field.get("options", []) + [
                {"name": option, "description": f"PASI metadata option: {option}", "color": "GRAY"}
                for option in missing
            ])
            return None
        return field
    return create_field(
        project["id"],
        {
            "projectId": project["id"],
            "name": name,
            "dataType": "SINGLE_SELECT",
            "singleSelectOptions": [
                {"name": option, "description": f"PASI metadata option: {option}", "color": "GRAY"}
                for option in options
            ],
        },
    )


def update_single_select_field(project_id: str, field_id: str, options: list[dict[str, object]]) -> None:
    query = """
    mutation($input:UpdateProjectV2FieldInput!) {
      updateProjectV2Field(input:$input) { projectV2Field { id } }
    }
    """
    graphql(query, {"input": {"fieldId": field_id, "singleSelectOptions": options}})


def iteration_configs() -> list[dict[str, object]]:
    return [
        {
            "title": iteration,
            "startDate": start,
            "duration": (date.fromisoformat(end) - date.fromisoformat(start)).days + 1,
        }
        for _, iteration, start, end in PHASE_SCHEDULE
    ]


def ensure_iterations(project: dict[str, object]) -> dict[str, object]:
    fields = project["fields"]["nodes"]  # type: ignore[index]
    field = next((f for f in fields if f.get("name") == "Iteration"), None)
    desired = iteration_configs()

    if field is None:
        return create_field(
            project["id"],
            {
                "projectId": project["id"],
                "name": "Iteration",
                "dataType": "ITERATION",
                "iterationConfiguration": {
                    "startDate": desired[0]["startDate"],
                    "duration": desired[0]["duration"],
                    "iterations": desired,
                },
            },
        )

    existing = field.get("configuration", {}).get("iterations", [])
    desired_by_title = {item["title"]: item for item in desired}
    existing_by_title = {item["title"]: item for item in existing}
    merged_by_title = dict(existing_by_title)
    merged_by_title.update(desired_by_title)
    merged = sorted(merged_by_title.values(), key=lambda item: item["startDate"])
    start_date = min(item["startDate"] for item in merged)
    default_duration = next(
        item["duration"] for item in merged if item["title"] == "Iteration 1"
    )

    if merged != existing:
        field = update_field(
            project["id"],
            {
                "fieldId": field["id"],
                "iterationConfiguration": {
                    "startDate": start_date,
                    "duration": default_duration,
                    "iterations": merged,
                },
            },
        )
    return field


def update_item_field(project_id: str, item_id: str, field_id: str, value: dict[str, object]) -> None:
    query = """
    mutation($input:UpdateProjectV2ItemFieldValueInput!) {
      updateProjectV2ItemFieldValue(input:$input) {
        projectV2Item { id }
      }
    }
    """
    graphql(query, {"input": {"projectId": project_id, "itemId": item_id, "fieldId": field_id, "value": value}})


def add_item(project_id: str, content_id: str) -> str:
    query = """
    mutation($project:ID!, $content:ID!) {
      addProjectV2ItemById(input:{projectId:$project, contentId:$content}) {
        item { id }
      }
    }
    """
    data = graphql(query, {"project": project_id, "content": content_id})
    return data["addProjectV2ItemById"]["item"]["id"]  # type: ignore[index]


def sync_issue(issue_number: int) -> None:
    content_id, title, body = fetch_issue(issue_number)
    metadata = parse_metadata(body)
    project = project_snapshot()

    start_field = ensure_date_field(project, "Start Date", ["Start Date", "Start date", "Start"])
    end_field = ensure_date_field(project, "End Date", ["End Date", "End date", "Target Date", "Target date", "End"])
    team_field = ensure_single_select(project, "Team", ["Backend", "Frontend"])
    quarter_field = ensure_single_select(
        project,
        "Quarter",
        ["Q3-2026", "Q4-2026", "Q1-2027", "Q2-2027", "Q3-2027", "Q4-2027", "Q1-2028"],
    )
    iteration_field = ensure_iterations(project)

    # Refresh after any field creation/update so newly-created option/iteration IDs are current.
    project = project_snapshot()
    fields = {field["name"]: field for field in project["fields"]["nodes"]}

    start_field = next(field for field in fields.values() if field["name"].lower() in {"start date", "start"})
    end_field = next(field for field in fields.values() if field["name"].lower() in {"end date", "target date", "end"})
    item_id = add_item(project["id"], content_id)
    update_item_field(project["id"], item_id, fields["Start Date"]["id"], {"date": metadata.start_date})
    update_item_field(project["id"], item_id, fields["End Date"]["id"], {"date": metadata.end_date})

    team_option = next(
        option for option in fields["Team"]["options"] if option["name"] == metadata.team
    )
    quarter_option = next(
        option for option in fields["Quarter"]["options"] if option["name"] == metadata.quarter
    )
    update_item_field(
        project["id"], item_id, fields["Team"]["id"],
        {"singleSelectOptionId": team_option["id"]},
    )
    update_item_field(
        project["id"], item_id, fields["Quarter"]["id"],
        {"singleSelectOptionId": quarter_option["id"]},
    )

    iteration = next(
        item
        for item in fields["Iteration"]["configuration"]["iterations"]
        if item["title"] == metadata.iteration
    )
    update_item_field(
        project["id"], item_id, fields["Iteration"]["id"],
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
            ".[] | select(.body != null) | [(.number|tostring), .body] | @tsv",
        ]
    )
    numbers: list[int] = []
    for line in raw.splitlines():
        number, body = line.split("\t", 1)
        if "PASI_PROJECT_METADATA" in body:
            numbers.append(int(number))
    return sorted(set(numbers))


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

    for number in numbers:
        sync_issue(number)


if __name__ == "__main__":
    main()
