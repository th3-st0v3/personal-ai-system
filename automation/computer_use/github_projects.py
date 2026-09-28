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
    """Semantic GitHub Projects V2 client.

    The caller uses repository/issue/project/field names; GraphQL node IDs are
    resolved internally. Mutations are followed by a read-back verification.
    """

    def __init__(self, transport: GitHubGraphQLTransport, *, owner: str, owner_type: str = "USER") -> None:
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
        query = """
        query($login: String!, $number: Int!) {
          user(login: $login) { projectV2(number: $number) { id number title } }
          organization(login: $login) { projectV2(number: $number) { id number title } }
        }
        """
        data = self._data(query, {"login": self.owner, "number": number})
        owner_data = data["user"] if self.owner_type == "USER" else data["organization"]
        project = owner_data.get("projectV2") if isinstance(owner_data, Mapping) else None
        if not isinstance(project, Mapping):
            raise GitHubProjectError(f"Project #{number} was not found for {self.owner}")
        return GitHubProject(str(project["id"]), int(project["number"]), str(project["title"]))

    def get_issue_id(self, repository: str, issue_number: int) -> str:
        owner, name = self._split_repo(repository)
        query = """
        query($owner: String!, $name: String!, $number: Int!) {
          repository(owner: $owner, name: $name) {
            issue(number: $number) { id number title }
          }
        }
        """
        data = self._data(query, {"owner": owner, "name": name, "number": issue_number})
        issue = data.get("repository", {}).get("issue")
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
                    id name dataType
                    options { id name }
                  }
                  ... on ProjectV2IterationField {
                    id name dataType
                    configuration {
                      iterations { id title }
                    }
                  }
                }
              }
            }
          }
        }
        """
        data = self._data(query, {"id": project.id})
        nodes = data.get("node", {}).get("fields", {}).get("nodes", [])
        fields: list[GitHubProjectField] = []
        for node in nodes:
            if not isinstance(node, Mapping) or not node.get("id") or not node.get("name"):
                continue
            options = node.get("options") or node.get("configuration", {}).get("iterations") or []
            fields.append(
                GitHubProjectField(
                    id=str(node["id"]),
                    name=str(node["name"]),
                    data_type=str(node.get("dataType", "")),
                    options=tuple(option for option in options if isinstance(option, Mapping)),
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
            items = data.get("node", {}).get("items", {})
            for item in items.get("nodes", []):
                content = item.get("content") if isinstance(item, Mapping) else None
                if isinstance(content, Mapping) and content.get("id") == issue_id:
                    return str(item["id"])
            page = items.get("pageInfo", {})
            if not page.get("hasNextPage"):
                return None
            after = page.get("endCursor")

    def ensure_item(self, project_number: int, repository: str, issue_number: int) -> str:
        existing = self.get_item_id(project_number, repository, issue_number)
        if existing:
            return existing
        project = self.get_project(project_number)
        issue_id = self.get_issue_id(repository, issue_number)
        mutation = """
        mutation($projectId: ID!, $contentId: ID!) {
          addProjectV2ItemById(input: {projectId: $projectId, contentId: $contentId}) {
            item { id }
          }
        }
        """
        data = self._data(mutation, {"projectId": project.id, "contentId": issue_id})
        item = data.get("addProjectV2ItemById", {}).get("item")
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
        mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $value: ProjectV2FieldValue!) {
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
            {"projectId": project.id, "itemId": item_id, "fieldId": field.id, "value": input_value},
        )
        updated = data.get("updateProjectV2ItemFieldValue", {}).get("projectV2Item")
        if not isinstance(updated, Mapping) or updated.get("id") != item_id:
            raise GitHubProjectError("GitHub did not return the updated ProjectV2 item")
        observed = self.get_field_value(project_number, item_id, field_name)
        if not self._matches(field, observed, value):
            raise GitHubProjectError(
                f"Project field verification failed for {field_name!r}: expected {value!r}, observed {observed!r}"
            )
        return {"project_id": project.id, "item_id": item_id, "field_id": field.id, "value": observed}

    def get_field_value(self, project_number: int, item_id: str, field_name: str) -> Any:
        project = self.get_project(project_number)
        query = """
        query($projectId: ID!, $itemId: ID!, $fieldName: String!) {
          node(id: $projectId) {
            ... on ProjectV2 {
              item: item(id: $itemId) {
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
        }
        """
        data = self._data(query, {"itemId": item_id, "fieldName": field_name})
        value = data.get("node", {}).get("fieldValueByName")
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
        matches = [field for field in self.get_project_fields(project_number) if field.name.casefold() == name.casefold()]
        if not matches:
            raise GitHubProjectError(f"Project field {name!r} was not found")
        return matches[0]

    @staticmethod
    def _field_value(field: GitHubProjectField, value: Any) -> Mapping[str, Any]:
        if field.data_type == "SINGLE_SELECT":
            option = next((item for item in field.options if str(item.get("name", "")).casefold() == str(value).casefold()), None)
            if option is None:
                raise GitHubProjectError(f"Option {value!r} was not found for field {field.name!r}")
            return {"singleSelectOptionId": str(option["id"])}
        if field.data_type == "ITERATION":
            option = next((item for item in field.options if str(item.get("title", "")).casefold() == str(value).casefold()), None)
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
        if field.data_type == "NUMBER":
            return float(observed) == float(expected)
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


__all__ = ["GitHubGraphQLTransport", "GitHubProjectError", "GitHubProject", "GitHubProjectField", "GitHubProjectsV2"]
