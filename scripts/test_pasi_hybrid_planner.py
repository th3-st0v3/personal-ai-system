from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Iterable, cast
from unittest import mock

from scripts import pasi_hybrid_planner as planner


def task(
    task_id: str,
    *,
    depends_on: tuple[str, ...] = (),
    priority: int = 0,
    status: str = "pending",
    splittable: bool = False,
    estimated_size: str = "medium",
    allowed_paths: tuple[str, ...] = ("scripts/",),
    decomposition_parent: str = "",
    decomposed_children: tuple[str, ...] = (),
) -> planner.TaskSpec:
    return planner.TaskSpec(
        id=task_id,
        title=task_id,
        objective=f"Objective for {task_id}",
        depends_on=depends_on,
        acceptance_criteria=("Acceptance criterion is met.",),
        verification=("Run the deterministic test.",),
        allowed_paths=allowed_paths,
        priority=priority,
        status=status,
        splittable=splittable,
        estimated_size=estimated_size,
        decomposition_parent=decomposition_parent,
        decomposed_children=decomposed_children,
    )


class TestHybridPlanner(unittest.TestCase):
    def test_load_roadmap_rejects_malformed_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "roadmap.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "not-an-integer",
                        "tasks": [task("a").to_dict()],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(planner.PlannerError, "schema_version must be an integer"):
                planner.load_roadmap(path)

    def test_load_roadmap_validates_dependencies_and_cycles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "roadmap.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "tasks": [
                            task("a").to_dict(),
                            task("b", depends_on=("a",)).to_dict(),
                        ],
                    }
                ),
                encoding="utf-8",
            )
            tasks = planner.load_roadmap(path)
            self.assertEqual([item.id for item in tasks], ["a", "b"])

            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "tasks": [
                            task("a", depends_on=("b",)).to_dict(),
                            task("b", depends_on=("a",)).to_dict(),
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(planner.PlannerError, "cycle"):
                planner.load_roadmap(path)

    def test_eligibility_is_deterministic_and_dependencies_gate_execution(self) -> None:
        tasks = (
            task("root"),
            task("child", depends_on=("root",)),
            task("blocked", status="blocked"),
        )
        ledger = {
            "root": {"task_id": "root", "task": "root", "status": "completed"},
        }
        eligible = planner.eligible_tasks(tasks, ledger)
        self.assertEqual([item.id for item in eligible], ["child"])

    def test_decomposed_parent_is_not_satisfied_until_all_children_complete(self) -> None:
        tasks = (
            task(
                "parent",
                status="decomposed",
                splittable=True,
                estimated_size="large",
                decomposed_children=("parent.one", "parent.two"),
            ),
            task("parent.one", decomposition_parent="parent"),
            task("parent.two", decomposition_parent="parent"),
            task("after", depends_on=("parent",)),
        )
        ledger = {
            "parent": {"task_id": "parent", "task": "parent", "status": "decomposed"},
            "parent.one": {"task_id": "parent.one", "task": "one", "status": "completed"},
        }
        self.assertNotIn("after", [item.id for item in planner.eligible_tasks(tasks, ledger)])
        ledger["parent.two"] = {"task_id": "parent.two", "task": "two", "status": "completed"}
        self.assertIn("after", [item.id for item in planner.eligible_tasks(tasks, ledger)])

    def test_decomposed_parent_is_never_execution_eligible(self) -> None:
        tasks = (
            task(
                "parent",
                status="decomposed",
                splittable=True,
                estimated_size="large",
                decomposed_children=("parent.one", "parent.two"),
            ),
            task("parent.one", decomposition_parent="parent"),
            task("parent.two", decomposition_parent="parent"),
        )
        eligible = planner.eligible_tasks(tasks, {})
        self.assertNotIn("parent", [item.id for item in eligible])
        self.assertEqual([item.id for item in eligible], ["parent.one", "parent.two"])

    def test_roadmap_is_complete_requires_all_tasks_satisfied(self) -> None:
        tasks = (
            task("root"),
            task("child", depends_on=("root",)),
        )
        ledger = {
            "root": {"task_id": "root", "status": "completed"},
            "child": {"task_id": "child", "status": "completed"},
        }
        self.assertTrue(planner.roadmap_is_complete(tasks, ledger))
        ledger["child"]["status"] = "blocked"
        self.assertFalse(planner.roadmap_is_complete(tasks, ledger))


    def test_deterministic_rank_uses_priority_then_unblock_count_then_id(self) -> None:
        tasks = (
            task("a", priority=10),
            task("b", priority=10),
            task("c", depends_on=("a",), priority=1),
        )
        ledger = {}
        candidates = planner.eligible_tasks(tasks, ledger)
        ranked = planner.deterministic_rank(candidates, tasks, ledger)
        self.assertEqual([item.id for item in ranked], ["a", "b"])

    def test_ai_rank_is_used_only_after_deterministic_eligibility(self) -> None:
        tasks = (task("a"), task("b"), task("blocked", status="blocked"))
        ledger = {}
        seen: list[str] = []

        def ranker(candidates):
            seen.extend(item.id for item in candidates)
            return ["b", "a"]

        decision = planner.select_task(tasks, ledger, ai_ranker=ranker)
        assert decision.selected is not None
        self.assertEqual(decision.selected.id, "b")
        self.assertEqual(decision.mode, "ai_rank")
        self.assertEqual(seen, ["a", "b"])
        self.assertNotIn("blocked", seen)

    def test_invalid_ai_ranking_falls_back_to_deterministic_choice(self) -> None:
        tasks = (task("a", priority=10), task("b", priority=0))
        decision = planner.select_task(
            tasks,
            {},
            ai_ranker=lambda _candidates: ["not-eligible", "b"],
        )
        assert decision.selected is not None
        self.assertEqual(decision.selected.id, "a")
        self.assertEqual(decision.mode, "deterministic_fallback")
        self.assertFalse(decision.ai_used)

    def test_ai_ranking_rejects_non_string_task_ids(self) -> None:
        candidates = (task("a"), task("b"))
        with self.assertRaisesRegex(planner.PlannerError, "IDs must be strings"):
            planner.validate_ai_ranking(candidates, cast(Iterable[str], ["a", 1]))

    def test_single_eligible_task_never_calls_ai(self) -> None:
        tasks = (task("a"), task("b", depends_on=("a",)))
        called = False

        def ranker(_candidates):
            nonlocal called
            called = True
            return ["b"]

        decision = planner.select_task(
            tasks,
            {"a": {"task_id": "a", "status": "completed"}},
            ai_ranker=ranker,
        )
        assert decision.selected is not None
        self.assertEqual(decision.selected.id, "b")
        self.assertFalse(called)

    def test_decomposition_validation_rejects_scope_escape_and_external_dependency(self) -> None:
        parent = task(
            "parent",
            depends_on=("foundation",),
            splittable=True,
            estimated_size="large",
            allowed_paths=("scripts/",),
        )
        good = task(
            "parent.one",
            decomposition_parent="parent",
            depends_on=("foundation",),
            allowed_paths=("scripts/subdir/",),
        )
        good_two = task(
            "parent.two",
            decomposition_parent="parent",
            depends_on=("foundation",),
            allowed_paths=("scripts/",),
        )
        planner.validate_decomposition(parent, (good, good_two))

        missing_prerequisite = task(
            "parent.missing",
            decomposition_parent="parent",
            allowed_paths=("scripts/",),
        )
        with self.assertRaisesRegex(planner.PlannerError, "prerequisites"):
            planner.validate_decomposition(parent, (good, missing_prerequisite))

        bad_scope = task("parent.bad", decomposition_parent="parent", allowed_paths=("automation/",))
        with self.assertRaisesRegex(planner.PlannerError, "scope"):
            planner.validate_decomposition(parent, (good, bad_scope))

        bad_dependency = task("parent.bad2", decomposition_parent="parent", depends_on=("outside",))
        with self.assertRaisesRegex(planner.PlannerError, "external dependency"):
            planner.validate_decomposition(parent, (good, bad_dependency))

    def test_decomposition_overlay_round_trips_without_erasing_previous_entries(self) -> None:
        parent = task("parent", splittable=True, estimated_size="large")
        children = (
            task("parent.one", decomposition_parent="parent"),
            task("parent.two", decomposition_parent="parent"),
        )
        other_parent = task("other", splittable=True, estimated_size="large")
        other_children = (
            task("other.one", decomposition_parent="other"),
            task("other.two", decomposition_parent="other"),
        )
        with tempfile.TemporaryDirectory() as directory:
            overlay = Path(directory) / "overlay.json"
            roadmap = Path(directory) / "roadmap.json"
            roadmap.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "tasks": [parent.to_dict(), other_parent.to_dict()],
                    }
                ),
                encoding="utf-8",
            )
            planner.save_decomposition_overlay(
                overlay,
                parent=parent,
                children=children,
                roadmap_path=roadmap,
            )
            planner.save_decomposition_overlay(
                overlay,
                parent=other_parent,
                children=other_children,
                roadmap_path=roadmap,
            )
            loaded = planner.load_roadmap_with_overlay(roadmap, overlay)
            by_id = {item.id: item for item in loaded}
            self.assertEqual(by_id["parent"].status, "decomposed")
            self.assertEqual(by_id["other"].status, "decomposed")
            self.assertIn("parent.one", by_id)
            self.assertIn("other.two", by_id)

    def test_remote_planner_endpoint_is_rejected_by_default(self) -> None:
        with self.assertRaisesRegex(planner.PlannerError, "must be local"):
            with mock.patch.object(planner, "_http_json") as http_json:
                planner._ollama_call(
                    system_prompt="rank",
                    user_payload={"tasks": []},
                    timeout_seconds=0.1,
                    base_url="https://example.com",
                    model="test-model",
                )
                http_json.assert_not_called()

    def test_stale_decomposition_overlay_is_ignored_after_roadmap_changes(self) -> None:
        parent = task("parent", splittable=True, estimated_size="large")
        children = (
            task("parent.one", decomposition_parent="parent"),
            task("parent.two", decomposition_parent="parent"),
        )
        with tempfile.TemporaryDirectory() as directory:
            roadmap = Path(directory) / "roadmap.json"
            overlay = Path(directory) / "overlay.json"
            roadmap.write_text(
                json.dumps({"schema_version": 1, "tasks": [parent.to_dict()]}),
                encoding="utf-8",
            )
            planner.save_decomposition_overlay(
                overlay,
                parent=parent,
                children=children,
                roadmap_path=roadmap,
            )
            roadmap.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "tasks": [task("replacement").to_dict()],
                    }
                ),
                encoding="utf-8",
            )
            loaded = planner.load_roadmap_with_overlay(roadmap, overlay)
            self.assertEqual([item.id for item in loaded], ["replacement"])

    def test_saving_after_roadmap_change_discards_stale_generated_tasks(self) -> None:
        old_parent = task("old.parent", splittable=True, estimated_size="large")
        old_children = (
            task("old.parent.one", decomposition_parent="old.parent"),
            task("old.parent.two", decomposition_parent="old.parent"),
        )
        new_parent = task("new.parent", splittable=True, estimated_size="large")
        new_children = (
            task("new.parent.one", decomposition_parent="new.parent"),
            task("new.parent.two", decomposition_parent="new.parent"),
        )
        with tempfile.TemporaryDirectory() as directory:
            roadmap = Path(directory) / "roadmap.json"
            overlay = Path(directory) / "overlay.json"
            roadmap.write_text(
                json.dumps({"schema_version": 1, "tasks": [old_parent.to_dict()]}),
                encoding="utf-8",
            )
            planner.save_decomposition_overlay(
                overlay,
                parent=old_parent,
                children=old_children,
                roadmap_path=roadmap,
            )
            roadmap.write_text(
                json.dumps({"schema_version": 1, "tasks": [new_parent.to_dict()]}),
                encoding="utf-8",
            )
            planner.save_decomposition_overlay(
                overlay,
                parent=new_parent,
                children=new_children,
                roadmap_path=roadmap,
            )
            loaded = planner.load_roadmap_with_overlay(roadmap, overlay)
            self.assertEqual(
                [item.id for item in loaded],
                ["new.parent", "new.parent.one", "new.parent.two"],
            )


    def test_ollama_ranker_uses_resource_safe_non_thinking_json_settings(self) -> None:
        candidates = (task("a"), task("b"))
        captured = {}

        def fake_call(**kwargs):
            captured.update(kwargs)
            return {"ranked_ids": ["b", "a"]}

        with mock.patch.object(planner, "_ollama_call", side_effect=fake_call):
            ranked = planner.ollama_ranker(candidates)

        self.assertEqual(ranked, ("b", "a"))
        self.assertFalse(captured["think"])
        self.assertEqual(captured["num_ctx"], 4096)
        self.assertTrue(captured["json_mode"])
        self.assertEqual(captured["timeout_seconds"], 30.0)

    def test_ollama_ranker_validates_structured_response(self) -> None:
        candidates = (task("a"), task("b"))
        with mock.patch.object(
            planner,
            "_ollama_call",
            return_value={"ranked_ids": ["b", "a"]},
        ):
            ranked = planner.ollama_ranker(candidates, model="test-model")
        self.assertEqual(ranked, ("b", "a"))

    def test_ollama_decomposition_rejects_conflicting_parent(self) -> None:
        parent = task("parent", splittable=True, estimated_size="large")
        with mock.patch.object(
            planner,
            "_ollama_call",
            return_value={
                "tasks": [
                    task("parent.one", decomposition_parent="other").to_dict(),
                    task("parent.two").to_dict(),
                ]
            },
        ):
            with self.assertRaisesRegex(planner.PlannerError, "conflicting parent"):
                planner.ai_decompose_with_ollama(parent, model="test-model")

    def test_ollama_decomposition_requires_verifiable_children(self) -> None:
        parent = task("parent", splittable=True, estimated_size="large")
        with mock.patch.object(
            planner,
            "_ollama_call",
            return_value={
                "tasks": [
                    task("parent.one").to_dict(),
                    task("parent.two").to_dict(),
                ]
            },
        ):
            children = planner.ai_decompose_with_ollama(parent, model="test-model")
        self.assertEqual([item.id for item in children], ["parent.one", "parent.two"])


if __name__ == "__main__":
    unittest.main()
