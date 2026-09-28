from __future__ import annotations

import unittest
from typing import Any, Mapping

from automation.computer_use.github_projects import (
    GitHubProjectError,
    GitHubProjectsV2,
)


class FakeGraphQL:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Mapping[str, Any]]] = []
        self.field_value = "Todo"

    def execute(self, query: str, variables: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        variables = dict(variables or {})
        self.calls.append((query, variables))
        if "user(login" in query and "projectV2" in query:
            return {"data": {"user": {"projectV2": {"id": "PVT_1", "number": 1, "title": "Roadmap"}}}}
        if "repository(owner" in query:
            return {"data": {"repository": {"issue": {"id": "I_1", "number": 42, "title": "P0.1"}}}}
        if "fields(first" in query:
            return {
                "data": {
                    "node": {
                        "fields": {
                            "nodes": [
                                {
                                    "id": "PVTF_1",
                                    "name": "Status",
                                    "dataType": "SINGLE_SELECT",
                                    "options": [
                                        {"id": "opt_todo", "name": "Todo"},
                                        {"id": "opt_done", "name": "Done"},
                                    ],
                                }
                            ]
                        }
                    }
                }
            }
        if "items(first" in query:
            return {
                "data": {
                    "node": {
                        "items": {
                            "nodes": [{"id": "PVTI_1", "content": {"id": "I_1"}}],
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                        }
                    }
                }
            }
        if "updateProjectV2ItemFieldValue" in query:
            self.field_value = "Done"
            return {"data": {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": "PVTI_1"}}}}
        if "fieldValueByName" in query:
            return {
                "data": {
                    "node": {
                        "item": {
                            "fieldValueByName": {
                                "name": self.field_value,
                                "optionId": "opt_done" if self.field_value == "Done" else "opt_todo",
                            }
                        }
                    }
                }
            }
        raise AssertionError(f"unexpected query: {query}")


class GitHubProjectsV2Tests(unittest.TestCase):
    def test_resolves_project_issue_item_and_field_before_mutation(self) -> None:
        transport = FakeGraphQL()
        client = GitHubProjectsV2(transport, owner="th3-st0v3")
        result = client.set_field(1, "th3-st0v3/personal-ai-system", 42, "Status", "Done")
        self.assertEqual(result["project_id"], "PVT_1")
        self.assertEqual(result["item_id"], "PVTI_1")
        self.assertEqual(result["field_id"], "PVTF_1")
        self.assertEqual(result["value"], "Done")
        self.assertTrue(any("updateProjectV2ItemFieldValue" in query for query, _ in transport.calls))

    def test_unknown_option_is_rejected_before_mutation(self) -> None:
        transport = FakeGraphQL()
        client = GitHubProjectsV2(transport, owner="th3-st0v3")
        with self.assertRaises(GitHubProjectError):
            client.set_field(1, "th3-st0v3/personal-ai-system", 42, "Status", "Missing")
        self.assertFalse(any("updateProjectV2ItemFieldValue" in query for query, _ in transport.calls))

    def test_invalid_owner_type_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            GitHubProjectsV2(FakeGraphQL(), owner="th3-st0v3", owner_type="TEAM")


if __name__ == "__main__":
    unittest.main()
