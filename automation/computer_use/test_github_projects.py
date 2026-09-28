from __future__ import annotations

import unittest
from typing import Any, Mapping

from automation.computer_use.github_projects import GitHubProjectError, GitHubProjectsV2


class FakeGraphQL:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Mapping[str, Any]]] = []
        self.field_value: str | None = "Todo"
        self.item_present = True

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
                                    "id": "PVTF_STATUS",
                                    "name": "Status",
                                    "dataType": "SINGLE_SELECT",
                                    "options": [
                                        {"id": "opt_todo", "name": "Todo"},
                                        {"id": "opt_done", "name": "Done"},
                                    ],
                                },
                                {
                                    "id": "PVTF_ITERATION",
                                    "name": "Iteration",
                                    "dataType": "ITERATION",
                                    "configuration": {
                                        "iterations": [
                                            {"id": "iter_1", "title": "Iteration 1"},
                                            {"id": "iter_2", "title": "Iteration 2"},
                                        ]
                                    },
                                },
                            ]
                        }
                    }
                }
            }
        if "items(first" in query:
            nodes = [{"id": "PVTI_1", "content": {"id": "I_1"}}] if self.item_present else []
            return {"data": {"node": {"items": {"nodes": nodes, "pageInfo": {"hasNextPage": False, "endCursor": None}}}}}
        if "addProjectV2ItemById" in query:
            self.item_present = True
            return {"data": {"addProjectV2ItemById": {"item": {"id": "PVTI_1"}}}}
        if "clearProjectV2ItemFieldValue" in query:
            self.field_value = None
            return {"data": {"clearProjectV2ItemFieldValue": {"projectV2Item": {"id": "PVTI_1"}}}}
        if "updateProjectV2ItemFieldValue" in query:
            if variables["value"] == {"iterationId": "iter_2"}:
                self.field_value = "Iteration 2"
            else:
                self.field_value = "Done"
            return {"data": {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": "PVTI_1"}}}}
        if "fieldValueByName" in query:
            if self.field_value is None:
                value = None
            elif self.field_value == "Iteration 2":
                value = {"title": "Iteration 2", "iterationId": "iter_2"}
            else:
                value = {"name": self.field_value, "optionId": "opt_done"}
            return {"data": {"node": {"fieldValueByName": value}}}
        raise AssertionError(f"unexpected query: {query}")


class GitHubProjectsV2Tests(unittest.TestCase):
    def make_client(self) -> tuple[FakeGraphQL, GitHubProjectsV2]:
        transport = FakeGraphQL()
        return transport, GitHubProjectsV2(transport, owner="th3-st0v3")

    def test_status_set_and_readback(self) -> None:
        transport, client = self.make_client()
        result = client.set_status(1, "th3-st0v3/personal-ai-system", 42, "Done")
        self.assertEqual(result["project_id"], "PVT_1")
        self.assertEqual(result["item_id"], "PVTI_1")
        self.assertEqual(result["field_id"], "PVTF_STATUS")
        self.assertEqual(result["value"], "Done")
        self.assertTrue(any("updateProjectV2ItemFieldValue" in q for q, _ in transport.calls))
        self.assertTrue(all("\\n" not in q for q, _ in transport.calls))

    def test_missing_item_is_added_before_update(self) -> None:
        transport, client = self.make_client()
        transport.item_present = False
        client.set_status(1, "th3-st0v3/personal-ai-system", 42, "Done")
        queries = [q for q, _ in transport.calls]
        self.assertLess(
            next(i for i, q in enumerate(queries) if "addProjectV2ItemById" in q),
            next(i for i, q in enumerate(queries) if "updateProjectV2ItemFieldValue" in q),
        )

    def test_iteration_resolves_by_title(self) -> None:
        transport, client = self.make_client()
        result = client.set_iteration(1, "th3-st0v3/personal-ai-system", 42, "Iteration 2")
        self.assertEqual(result["value"], "Iteration 2")
        mutation_vars = next(v for q, v in transport.calls if "updateProjectV2ItemFieldValue" in q)
        self.assertEqual(mutation_vars["value"], {"iterationId": "iter_2"})

    def test_unknown_option_is_rejected_before_mutation(self) -> None:
        transport, client = self.make_client()
        with self.assertRaises(GitHubProjectError):
            client.set_status(1, "th3-st0v3/personal-ai-system", 42, "Missing")
        self.assertFalse(any("updateProjectV2ItemFieldValue" in q for q, _ in transport.calls))

    def test_clear_verifies_readback(self) -> None:
        transport, client = self.make_client()
        result = client.clear_field(1, "th3-st0v3/personal-ai-system", 42, "Status")
        self.assertIsNone(result["value"])
        self.assertTrue(any("clearProjectV2ItemFieldValue" in q for q, _ in transport.calls))

    def test_invalid_owner_type_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            GitHubProjectsV2(FakeGraphQL(), owner="th3-st0v3", owner_type="TEAM")


if __name__ == "__main__":
    unittest.main()
