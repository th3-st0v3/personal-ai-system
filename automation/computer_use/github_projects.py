from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol


class GitHubProjectError(RuntimeError):
    """Raised when a GitHub Projects V2 operation cannot be completed."""


class GitHubGraphQLTransport(Protocol):
    def execute(self, query: str, variables: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        ...


@dataclass(frozen=True)
class GitHubProject:
    id: str
    number: int
    title: str


@dataclass(frozen=True)
class GitHubProjectField:
    id: str
    name: str
    data_type: str
    options: tuple[Mapping[str, Any], ...] = ()


class GitHubProjectsV2:
    """Semantic GitHub Projects V2 client with write/read-back verification."""

    def __init__(
        self,
        transport: GitHubGraphQLTransport,
        *,
        owner: str,
        owner_type: str = "USER",
    ) -> None:
        if not owner.strip():
            raise ValueError("GitHub project owner is required")
        if owner_type not in {"USER", "ORGANIZATION"}:
            raise ValueError("owner_type must be USER or ORGANIZATION")
        self.transport = transport
        self.owner = owner
        self.owner_type = owner_type

    def get_project(self, number: int) -> GitHubProject:
        if not isinstance(number, int) or isinstance(number, bool) or number < 1:
            raise ValueError("project number must be a positive integer")
        root_name = "user" if self.owner_type == "USER" else "organization"
        query = f"""
        query($login: String!, $number: Int!) {{
          {root_name}(login: $login) {{
            projectV2(number: $number) {{ id number title }}
          }}
        }}
        """
        data = self._data(query, {"login": self.owner, "number": number})
        root = data.get(root_name)
        project = root.get("projectV2") if isinstance(root, Mapping) else None
        if not isinstance(project, Mapping):
            raise GitHubProjectError(f"Project #{number} was not found for {self.owner}")
        return GitHubProject(str(project["id"]), int(project["number"]), str(project["title"]))

    def get_issue_id(self, repository: str, issue_number: int) -> str:
        owner, name = self._split_repo(repository)
        if not isinstance(issue_number, int) or isinstance(issue_number, bool) or issue_number < 1:
            raise ValueError("issue number must be a positive integer")
        query = """
        query($owner: String!, $name: String!, $number: Int!) {
          repository(owner: $owner, name: $name) {
            issue(number: $number) { id number title }
          }
        }
        """
        data = self._data(query, {"owner": owner, "name": name, "number": issue_number})
        repository_data = data.get("repository")
        issue = repository_data.get("issue") if isinstance(repository_data, Mapping) else None
        if not isinstance(issue, Mapping):
            raise GitHubProjectError(f"Issue #{issue_number} was not found in {repository}")
        return str(issue["id"])

    def get_project_fields(self, project_number: int) -> list[GitHubProjectField]:
        project = self.get_project(project_number)
        query = """
        query($id: ID!) {
          node(id: $id) {
            ... on ProjectV2 {
              fields(first: 100) {
                nodes {
                  ... on ProjectV2Field { id name dataType }
                  ... on ProjectV2SingleSelectField {
                    id
                    name
                    dataType
                    options { id name }
                  }
                  ... on ProjectV2IterationField {
                    id
                    name
                    dataType
                    configuration { iterations { id title startDate } }
                  }
                }
              }
            }
          }
        }
        """
        data = self._data(query, {"id": project.id})
        node = data.get("node")
        fields_obj = node.get("fields") if isinstance(node, Mapping) else None
        nodes = fields_obj.get("nodes", []) if isinstance(fields_obj, Mapping) else []
        fields: list[GitHubProjectField] = []
        for item in nodes:
            if not isinstance(item, Mapping) or not item.get("id") or not item.get("name"):
                continue
            options = item.get("options")
            if not options:
                configuration = item.get("configuration")
                if isinstance(configuration, Mapping):
                    options = configuration.get("iterations")
            fields.append(
                GitHubProjectField(
                    id=str(item["id"]),
                    name=str(item["name"]),
                    data_type=str(item.get("dataType", "")),
                    options=tuple(v for v in (options or []) if isinstance(v, Mapping)),
                )
            )
        return fields

    def get_item_id(self, project_number: int, repository: str, issue_number: int) -> str | None:
        project = self.get_project(project_number)
        issue_id = self.get_issue_id(repository, issue_number)
        query = """
        query($projectId: ID!, $after: String) {
          node(id: $projectId) {
            ... on ProjectV2 {
              items(first: 100, after: $after) {
                nodes {
                  id
                  content {
                    ... on Issue { id }
                    ... on PullRequest { id }
                  }
                }
                pageInfo { hasNextPage endCursor }
              }
            }
          }
        }
        """
        after: str | None = None
        while True:
            data = self._data(query, {"projectId": project.id, "after": after})
            node = data.get("node")
            items = node.get("items") if isinstance(node, Mapping) else None
            items = items if isinstance(items, Mapping) else {}
            for item in items.get("nodes", []):
                if not isinstance(item, Mapping):
                    continue
                content = item.get("content")
                if isinstance(content, Mapping) and content.get("id") == issue_id:
                    item_id = item.get("id")
                    return str(item_id) if item_id else None
            page_info = items.get("pageInfo")
            page_info = page_info if isinstance(page_info, Mapping) else {}
            if not page_info.get("hasNextPage"):
                return None
            after = page_info.get("endCursor")
            if not isinstance(after, str) or not after:
                raise GitHubProjectError("GitHub returned a continuation page without a cursor")

    def ensure_item(self, project_number: int, repository: str, issue_number: int) -> str:
        existing = self.get_item_id(project_number, repository, issue_number)
        if existing:
            return existing
        project = self.get_project(project_number)
        issue_id = self.get_issue_id(repository, issue_number)
        mutation = """
        mutation($projectId: ID!, $contentId: ID!) {
          addProjectV2ItemById(
            input: { projectId: $projectId, contentId: $contentId }
          ) {
            item { id }
          }
        }
        """
        data = self._data(mutation, {"projectId": project.id, "contentId": issue_id})
        result = data.get("addProjectV2ItemById")
        item = result.get("item") if isinstance(result, Mapping) else None
        if not isinstance(item, Mapping) or not item.get("id"):
            raise GitHubProjectError("GitHub did not return a ProjectV2 item ID")
        return str(item["id"])

    def set_field(
        self,
        project_number: int,
        repository: str,
        issue_number: int,
        field_name: str,
        value: Any,
    ) -> Mapping[str, Any]:
        project = self.get_project(project_number)
        item_id = self.ensure_item(project_number, repository, issue_number)
        field = self._find_field(project_number, field_name)
        input_value = self._field_value(field, value)
        mutation = """
        mutation(
          $projectId: ID!
          $itemId: ID!
          $fieldId: ID!
          $value: ProjectV2FieldValue!
        ) {
          updateProjectV2ItemFieldValue(
            input: {
              projectId: $projectId
              itemId: $itemId
              fieldId: $fieldId
              value: $value
            }
          ) {
            projectV2Item { id }
          }
        }
        """
        data = self._data(
            mutation,
            {
                "projectId": project.id,
                "itemId": item_id,
                "fieldId": field.id,
                "value": input_value,
            },
        )
        result = data.get("updateProjectV2ItemFieldValue")
        updated = result.get("projectV2Item") if isinstance(result, Mapping) else None
        if not isinstance(updated, Mapping) or updated.get("id") != item_id:
            raise GitHubProjectError("GitHub did not return the updated ProjectV2 item")
        observed = self.get_field_value(item_id, field_name)
        if not self._matches(field, observed, value):
            raise GitHubProjectError(
                f"Project field verification failed for {field_name!r}: "
                f"expected {value!r}, observed {observed!r}"
            )
        return {
            "project_id": project.id,
            "item_id": item_id,
            "field_id": field.id,
            "field_name": field.name,
            "value": observed,
        }

    def clear_field(
        self,
        project_number: int,
        repository: str,
        issue_number: int,
        field_name: str,
    ) -> Mapping[str, Any]:
        project = self.get_project(project_number)
        item_id = self.ensure_item(project_number, repository, issue_number)
        field = self._find_field(project_number, field_name)
        mutation = """
        mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!) {
          clearProjectV2ItemFieldValue(
            input: {
              projectId: $projectId
              itemId: $itemId
              fieldId: $fieldId
            }
          ) {
            projectV2Item { id }
          }
        }
        """
        data = self._data(
            mutation,
            {"projectId": project.id, "itemId": item_id, "fieldId": field.id},
        )
        result = data.get("clearProjectV2ItemFieldValue")
        updated = result.get("projectV2Item") if isinstance(result, Mapping) else None
        if not isinstance(updated, Mapping) or updated.get("id") != item_id:
            raise GitHubProjectError("GitHub did not return the cleared ProjectV2 item")
        observed = self.get_field_value(item_id, field_name)
        if observed is not None:
            raise GitHubProjectError(
                f"Project field clear verification failed for {field_name!r}: observed {observed!r}"
            )
        return {
            "project_id": project.id,
            "item_id": item_id,
            "field_id": field.id,
            "field_name": field.name,
            "value": None,
        }

    def set_status(self, project_number: int, repository: str, issue_number: int, status: str) -> Mapping[str, Any]:
        return self.set_field(project_number, repository, issue_number, "Status", status)

    def set_team(self, project_number: int, repository: str, issue_number: int, team: str) -> Mapping[str, Any]:
        return self.set_field(project_number, repository, issue_number, "Team", team)

    def set_iteration(self, project_number: int, repository: str, issue_number: int, iteration: str) -> Mapping[str, Any]:
        return self.set_field(project_number, repository, issue_number, "Iteration", iteration)

    def set_quarter(self, project_number: int, repository: str, issue_number: int, quarter: str) -> Mapping[str, Any]:
        return self.set_field(project_number, repository, issue_number, "Quarter", quarter)

    def get_field_value(self, item_id: str, field_name: str) -> Any:
        query = """
        query($itemId: ID!, $fieldName: String!) {
          node(id: $itemId) {
            ... on ProjectV2Item {
              fieldValueByName(name: $fieldName) {
                ... on ProjectV2ItemFieldSingleSelectValue { name optionId }
                ... on ProjectV2ItemFieldTextValue { text }
                ... on ProjectV2ItemFieldNumberValue { number }
                ... on ProjectV2ItemFieldDateValue { date }
                ... on ProjectV2ItemFieldIterationValue { title iterationId }
              }
            }
          }
        }
        """
        data = self._data(query, {"itemId": item_id, "fieldName": field_name})
        node = data.get("node")
        value = node.get("fieldValueByName") if isinstance(node, Mapping) else None
        if not isinstance(value, Mapping):
            return None
        if "name" in value:
            return value["name"]
        if "text" in value:
            return value["text"]
        if "number" in value:
            return value["number"]
        if "date" in value:
            return value["date"]
        if "title" in value:
            return value["title"]
        return None

    def _find_field(self, project_number: int, name: str) -> GitHubProjectField:
        matches = [v for v in self.get_project_fields(project_number) if v.name.casefold() == name.casefold()]
        if not matches:
            raise GitHubProjectError(f"Project field {name!r} was not found")
        return matches[0]

    @staticmethod
    def _field_value(field: GitHubProjectField, value: Any) -> Mapping[str, Any]:
        if field.data_type == "SINGLE_SELECT":
            option = next(
                (v for v in field.options if str(v.get("name", "")).casefold() == str(value).casefold()),
                None,
            )
            if option is None:
                raise GitHubProjectError(f"Option {value!r} was not found for field {field.name!r}")
            return {"singleSelectOptionId": str(option["id"])}
        if field.data_type == "ITERATION":
            option = next(
                (v for v in field.options if str(v.get("title", "")).casefold() == str(value).casefold()),
                None,
            )
            if option is None:
                raise GitHubProjectError(f"Iteration {value!r} was not found for field {field.name!r}")
            return {"iterationId": str(option["id"])}
        if field.data_type == "TEXT":
            if not isinstance(value, str):
                raise ValueError("TEXT project fields require a string value")
            return {"text": value}
        if field.data_type == "NUMBER":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("NUMBER project fields require a numeric value")
            return {"number": float(value)}
        if field.data_type == "DATE":
            if not isinstance(value, str):
                raise ValueError("DATE project fields require an ISO date string")
            return {"date": value}
        raise GitHubProjectError(f"Unsupported writable project field type: {field.data_type}")

    @staticmethod
    def _matches(field: GitHubProjectField, observed: Any, expected: Any) -> bool:
        if observed is None:
            return False
        if field.data_type == "NUMBER":
            try:
                return float(observed) == float(expected)
            except (TypeError, ValueError):
                return False
        return observed == expected

    @staticmethod
    def _split_repo(repository: str) -> tuple[str, str]:
        parts = repository.split("/")
        if len(parts) != 2 or not all(parts):
            raise ValueError("repository must be owner/name")
        return parts[0], parts[1]

    def _data(self, query: str, variables: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            response = self.transport.execute(query, variables)
        except Exception as exc:
            if isinstance(exc, GitHubProjectError):
                raise
            raise GitHubProjectError(f"GitHub GraphQL request failed: {exc}") from exc
        if not isinstance(response, Mapping):
            raise GitHubProjectError("GitHub GraphQL response must be an object")
        errors = response.get("errors")
        if errors:
            raise GitHubProjectError(f"GitHub GraphQL error: {errors}")
        data = response.get("data")
        if not isinstance(data, Mapping):
            raise GitHubProjectError("GitHub GraphQL response has no data")
        return data


__all__ = [
    "GitHubGraphQLTransport",
    "GitHubProjectError",
    "GitHubProject",
    "GitHubProjectField",
    "GitHubProjectsV2",
]
