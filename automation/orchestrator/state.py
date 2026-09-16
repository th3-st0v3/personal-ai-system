from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any


class StateManager:
    def __init__(self, ai_dir: Path):
        self.ai_dir = ai_dir

        self.project_state_path = ai_dir / "project-state.json"
        self.current_task_path = ai_dir / "current-task.json"
        self.feature_status_path = ai_dir / "feature-status.json"
        self.retry_state_path = ai_dir / "retry-state.json"
        self.test_results_path = ai_dir / "test-results.json"
        self.browser_results_path = ai_dir / "browser-results.json"
        self.context_package_path = ai_dir / "context-package.json"
        self.research_state_path = ai_dir / "research-state.json"
        self.execution_results_path = ai_dir / "execution-results.json"
        self.handoff_path = ai_dir / "handoff.json"
        self.queue_path = ai_dir / "queue.json"
        self.lock_path = ai_dir / "lock.json"

    def write_json(self, path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)

        temporary_path = path.with_suffix(path.suffix + ".tmp")

        with temporary_path.open("w", encoding="utf-8") as file:
            json.dump(
                value,
                file,
                indent=2,
                ensure_ascii=False,
            )
            file.write("\n")

        temporary_path.replace(path)

    def read_json(
        self,
        path: Path,
        default: Any,
    ) -> Any:
        if not path.exists():
            return default

        try:
            with path.open("r", encoding="utf-8") as file:
                return json.load(file)
        except (OSError, json.JSONDecodeError):
            return default

    def save_dataclass(self, path: Path, value: Any) -> None:
        self.write_json(path, asdict(value))

    def load_project_state(self) -> dict[str, Any]:
        return self.read_json(
            self.project_state_path,
            {},
        )

    def save_project_state(self, state: Any) -> None:
        self.save_dataclass(
            self.project_state_path,
            state,
        )

    def load_current_task(self) -> dict[str, Any]:
        return self.read_json(
            self.current_task_path,
            {},
        )

    def save_current_task(self, task: Any) -> None:
        self.save_dataclass(
            self.current_task_path,
            task,
        )

    def load_feature_status(self) -> dict[str, Any]:
        return self.read_json(
            self.feature_status_path,
            {},
        )

    def save_feature_status(
        self,
        feature_status: dict[str, Any],
    ) -> None:
        self.write_json(
            self.feature_status_path,
            feature_status,
        )

    def save_test_results(
        self,
        results: dict[str, Any],
    ) -> None:
        self.write_json(
            self.test_results_path,
            results,
        )

    def save_browser_results(
        self,
        results: dict[str, Any],
    ) -> None:
        self.write_json(
            self.browser_results_path,
            results,
        )

    def save_context_package(
        self,
        context_package: Any,
    ) -> None:
        self.write_json(
            self.context_package_path,
            context_package.to_context_dict(),
        )

    def load_context_package(
        self,
    ) -> dict[str, Any]:
        value = self.read_json(
            self.context_package_path,
            {},
        )

        if not isinstance(value, dict):
            return {}

        return value

    def save_research_state(
        self,
        research_state: Any,
    ) -> None:
        self.write_json(
            self.research_state_path,
            research_state.model_dump(mode="json"),
        )

    def load_research_state(
        self,
    ) -> dict[str, Any]:
        value = self.read_json(
            self.research_state_path,
            {},
        )

        if not isinstance(value, dict):
            return {}

        return value

    def save_execution_result(
        self,
        execution_result: Any,
    ) -> None:
        self.write_json(
            self.execution_results_path,
            execution_result.model_dump(mode="json"),
        )

    def load_execution_result(
        self,
    ) -> dict[str, Any]:
        value = self.read_json(
            self.execution_results_path,
            {},
        )

        if not isinstance(value, dict):
            return {}

        return value

    def load_browser_results(
        self,
    ) -> dict[str, Any]:
        value = self.read_json(
            self.browser_results_path,
            {},
        )

        if not isinstance(value, dict):
            return {}

        return value

    def save_handoff(
        self,
        handoff: dict[str, Any],
    ) -> None:
        self.write_json(
            self.handoff_path,
            handoff,
        )

    def save_queue(
        self,
        queue: list[dict[str, Any]],
    ) -> None:
        self.write_json(
            self.queue_path,
            queue,
        )

    def load_queue(
        self,
    ) -> list[dict[str, Any]]:
        value = self.read_json(
            self.queue_path,
            [],
        )

        if not isinstance(value, list):
            return []

        return value
