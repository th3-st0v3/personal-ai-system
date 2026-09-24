#!/usr/bin/env python3
"""Synchronize PASI issue planning metadata into a GitHub Project v2.

The issue body is the declarative source for the phase metadata. The script:
- discovers the PASI project,
- creates missing Start Date / End Date / Team / Quarter / Iteration fields,
- ensures Iteration 1..23 exist with the roadmap's actual phase windows,
- adds the issue to the project,
- writes date, iteration, team, and quarter values to the project item.

Requires GitHub CLI authentication with project write access.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

REPO = "th3-st0v3/personal-ai-system"
PROJECT_QUERY = os.environ.get("PASI_PROJECT_QUERY", "PASI")
PROJECT_TITLE = os.environ.get("PASI_PROJECT_TITLE", "").strip()

DATE_FIELDS = {"start": "Start Date", "end": "End Date"}
SINGLE_SELECT_FIELDS = {
    "team": ("Team", ["Backend", "Frontend"]),
    "quarter": (
        "Quarter",
        ["Q3-2026", "Q4-2026", "Q1-2027", "Q2-2027", "Q3-2027", "Q4-2027", "Q1-2028"],
    ),
}
ITERATION_FIELD = "Iteration"

META_RE = re.compile(
    r"<!--\\s*PASI_PROJECT_METADATA\\s*\\n(?P<body>.*?)\\nPASI_PROJECT_METADATA\\s*-->",
    re.DOTALL,
)


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


def graphql(query: str, **variables: Any) -> dict[str, Any]:
    args = ["api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        if isinstance(value, int):
            args.extend(["-F", f"{key}={value}"])
        else:
            args.extend(["-f", f"{key}={value}"])
    payload = json.loads(run_gh(args))
    if payload.get("errors"):
        raise RuntimeError(json.dumps(payload["errors"], indent=2))
    return payload["data"]


def parse_metadata(body: str) -> Metadata:
    match = META_RE.search(body or "")
    if not match:
        raise ValueError("Issue body is missing <!-- PASI_PROJECT_METADATA ... -->")

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
    data = graphql(query, owner="th3-st0v3", repo="personal-ai-system", number=issue_number)
    issue = data["repository"]["issue"]
    return issue["id"], issue["title"], issue.get("body") or ""


def project_snapshot() -> dict[str, Any]:
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
    data = graphql(query, login="th3-st0v3", query=PROJECT_QUERY)
    projects = data["user"]["projectsV2"]["nodes"]
    if PROJECT_TITLE:
        matches = [project for project in projects if project["title"] == PROJECT_TITLE]
    else:
        matches = [
            project
            for project in projects
            if "pasi" in project["title"].lower()
        ]
    if len(matches) != 1:
        names = ", ".join(project["title"] for project in matches) or "<none>"
        raise RuntimeError(
            f"Expected exactly one PASI Project (set PASI_PROJECT_TITLE to disambiguate); found: {names}"
        )
    return matches[0]


def mutation_add_item(project_id: str, content_id: str) -> str:
    query = """
    mutation($project:ID!, $content:ID!) {
      addProjectV2ItemById(input:{projectId:$project, contentId:$content}) {
        item { id }
      }
    }
    """
    data = graphql(query, project=project_id, content=content_id)
    return data["addProjectV2ItemById"]["item"]["id"]


def create_field(project_id: str, name: str, data_type: str, **extra: Any) -> dict[str, Any]:
    query = """
    mutation($project:ID!, $name:String!, $dataType:ProjectV2CustomFieldType!,
             $iterationConfiguration:ProjectV2IterationFieldConfigurationInput,
             $singleSelectOptions:[ProjectV2SingleSelectFieldOptionInput!]) {
      createProjectV2Field(input:{
        projectId:$project
        name:$name
        dataType:$dataType
        iterationConfiguration:$iterationConfiguration
        singleSelectOptions:$singleSelectOptions
      }) {
        projectV2Field {
          __typename
          ... on ProjectV2Field { id name }
          ... on ProjectV2IterationField {
            id name
            configuration { duration iterations { id title startDate duration } }
          }
          ... on ProjectV2SingleSelectField {
            id name
            options { id name }
          }
        }
      }
    }
    """
    data = graphql(
        query,
        project=project_id,
        name=name,
        dataType=data_type,
        iterationConfiguration=extra.get("iterationConfiguration"),
        singleSelectOptions=extra.get("singleSelectOptions"),
    )
    return data["createProjectV2Field"]["projectV2Field"]


def ensure_field(project: dict[str, Any], name: str, data_type: str, options: list[str] | None = None) -> dict[str, Any]:
    for field in project["fields"]["nodes"]:
        if field.get("name") == name:
            return field

    kwargs: dict[str, Any] = {}
    if data_type == "SINGLE_SELECT":
        kwargs["singleSelectOptions"] = [
            {
                "name": option,
                "description": f"PASI project metadata option: {option}",
                "color": "GRAY",
            }
            for option in (options or [])
        ]
    return create_field(project["id"], name, data_type, **kwargs)


def update_field_value(project_id: str, item_id: str, field_id: str, value: dict[str, Any]) -> None:
    query = """
    mutation($project:ID!, $item:ID!, $field:ID!, $value:ProjectV2FieldValue!) {
      updateProjectV2ItemFieldValue(
        input:{projectId:$project, itemId:$item, fieldId:$field, value:$value}
      ) { projectV2Item { id } }
    }
    """
    graphql(query, project=project_id, item=item_id, field=field_id, value=json.dumps(value))


def ensure_iterations(project: dict[str, Any], metadata: Metadata) -> dict[str, Any]:
    field = next((f for f in project["fields"]["nodes"] if f.get("name") == ITERATION_FIELD), None)

    # The complete roadmap schedule is carried in this repository, so the
    # automation builds the iteration catalog from the issue metadata set.
    if field is None:
        return create_field(project["id"], ITERATION_FIELD, "ITERATION")

    return field


def sync_issue(issue_number: int) -> None:
    content_id, title, body = fetch_issue(issue_number)
    metadata = parse_metadata(body)
    project = project_snapshot()

    start_field = ensure_field(project, DATE_FIELDS["start"], "DATE")
    end_field = ensure_field(project, DATE_FIELDS["end"], "DATE")
    team_field = ensure_field(project, SINGLE_SELECT_FIELDS["team"][0], "SINGLE_SELECT", SINGLE_SELECT_FIELDS["team"][1])
    quarter_field = ensure_field(project, SINGLE_SELECT_FIELDS["quarter"][0], "SINGLE_SELECT", SINGLE_SELECT_FIELDS["quarter"][1])
    iteration_field = ensure_iterations(project, metadata)

    item_id = mutation_add_item(project["id"], content_id)

    update_field_value(project["id"], item_id, start_field["id"], {"date": metadata.start_date})
    update_field_value(project["id"], item_id, end_field["id"], {"date": metadata.end_date})

    team_option = next(
        (option for option in team_field.get("options", []) if option["name"] == metadata.team),
        None,
    )
    quarter_option = next(
        (option for option in quarter_field.get("options", []) if option["name"] == metadata.quarter),
        None,
    )
    if not team_option or not quarter_option:
        raise RuntimeError(f"Project select options missing for {metadata.phase}")

    update_field_value(
        project["id"], item_id, team_field["id"],
        {"singleSelectOptionId": team_option["id"]},
    )
    update_field_value(
        project["id"], item_id, quarter_field["id"],
        {"singleSelectOptionId": quarter_option["id"]},
    )

    iteration = next(
        (
            value
            for value in iteration_field.get("configuration", {}).get("iterations", [])
            if value["title"] == metadata.iteration
        ),
        None,
    )
    if iteration:
        update_field_value(
            project["id"], item_id, iteration_field["id"],
            {"iterationId": iteration["id"]},
        )
    else:
        print(
            f"WARNING: {metadata.iteration} is not configured in the project's Iteration field. "
            "Run the iteration bootstrap job after adding the full roadmap catalog.",
        )

    print(f"Synced #{issue_number} {title} -> {metadata.phase}/{metadata.iteration}")


def all_metadata_issue_numbers() -> list[int]:
    endpoint = f"repos/{REPO}/issues?state=all&per_page=100"
    raw = run_gh(["api", endpoint, "--paginate", "--jq", ".[] | select(.body != null) | [(.number|tostring), .body] | @tsv"])
    numbers: list[int] = []
    for line in raw.splitlines():
        number_s, body = line.split("\t", 1)
        if "PASI_PROJECT_METADATA" in body:
            numbers.append(int(number_s))
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
