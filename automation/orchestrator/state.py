from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any


class StateCorruptionError(RuntimeError):
    """Raised when persisted orchestration state cannot be trusted."""


MAX_PERSISTED_TERMINAL_QUEUE_ITEMS = 32
TERMINAL_QUEUE_STATUSES = frozenset({"completed", "failed", "cancelled"})


class StateManager:
    def __init__(self, ai_dir: Path):
        self.ai_dir = ai_dir

        self.project_state_path = ai_dir / "project-state.json"
        self.current_task_path = ai_dir / "current-task.json"
        self.feature_status_path = ai_dir / "feature-status.json"
        self.retry_state_path = ai_dir / "retry-state.json"
        self.test_results_path = ai_dir / "test-results.json"
        self.browser_results_path = ai_dir / "browser-results.json"
        self.browser_health_path = ai_dir / "browser-health.json"
        self.browser_state_path = ai_dir / "browser-state.json"
        self.browser_response_path = ai_dir / "browser-response.json"
        self.context_package_path = ai_dir / "context-package.json"
        self.research_state_path = ai_dir / "research-state.json"
        self.execution_results_path = ai_dir / "execution-results.json"
        self.handoff_path = ai_dir / "handoff.json"
        self.queue_path = ai_dir / "queue.json"
        self.terminal_responses_dir = ai_dir / "terminal-responses"
        self.lock_path = ai_dir / "lock.json"

    def write_json(self, path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)

        temporary_path = path.with_suffix(path.suffix + ".tmp")

        try:
            with temporary_path.open("w", encoding="utf-8") as file:
                json.dump(
                    value,
                    file,
                    indent=2,
                    ensure_ascii=False,
                )
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())

            temporary_path.replace(path)

            # Persist the directory entry as well as the file contents so an
            # unexpected process/host restart cannot acknowledge a queue or
            # handoff update that is still only in filesystem cache.
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass

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
        except (OSError, json.JSONDecodeError) as exc:
            raise StateCorruptionError(
                f"Corrupt state file: {path}"
            ) from exc

    @staticmethod
    def require_dict(path: Path, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise StateCorruptionError(
                f"Invalid state shape for {path}: expected object"
            )
        return value

    @staticmethod
    def require_list(path: Path, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise StateCorruptionError(
                f"Invalid state shape for {path}: expected list of objects"
            )
        return value

    def save_dataclass(self, path: Path, value: Any) -> None:
        self.write_json(path, asdict(value))

    def load_project_state(self) -> dict[str, Any]:
        return self.require_dict(
            self.project_state_path,
            self.read_json(self.project_state_path, {}),
        )

    def save_project_state(self, state: Any) -> None:
        self.save_dataclass(
            self.project_state_path,
            state,
        )

    def load_current_task(self) -> dict[str, Any]:
        return self.require_dict(
            self.current_task_path,
            self.read_json(self.current_task_path, {}),
        )

    def save_current_task(self, task: Any) -> None:
        self.save_dataclass(
            self.current_task_path,
            task,
        )

    def load_feature_status(self) -> dict[str, Any]:
        return self.require_dict(
            self.feature_status_path,
            self.read_json(self.feature_status_path, {}),
        )

    def save_feature_status(
        self,
        feature_status: dict[str, Any],
    ) -> None:
        self.write_json(
            self.feature_status_path,
            feature_status,
        )

    def save_retry_state(
        self,
        retry_state: dict[str, Any],
    ) -> None:
        self.write_json(
            self.retry_state_path,
            retry_state,
        )

    def load_retry_state(
        self,
    ) -> dict[str, Any]:
        return self.require_dict(
            self.retry_state_path,
            self.read_json(self.retry_state_path, {}),
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

    def save_browser_response(
        self,
        response: dict[str, Any],
    ) -> None:
        self.write_json(
            self.browser_response_path,
            response,
        )

    def save_browser_health(self, health: dict[str, Any]) -> None:
        self.write_json(self.browser_health_path, health)

    def load_browser_health(self) -> dict[str, Any]:
        return self.require_dict(
            self.browser_health_path,
            self.read_json(self.browser_health_path, {}),
        )

    def save_browser_state(self, state: dict[str, Any]) -> None:
        self.write_json(self.browser_state_path, state)

    def load_browser_state(self) -> dict[str, Any]:
        return self.require_dict(
            self.browser_state_path,
            self.read_json(self.browser_state_path, {}),
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
        return self.require_dict(
            self.context_package_path,
            self.read_json(self.context_package_path, {}),
        )

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
        return self.require_dict(
            self.research_state_path,
            self.read_json(self.research_state_path, {}),
        )

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
        return self.require_dict(
            self.execution_results_path,
            self.read_json(self.execution_results_path, {}),
        )

    def load_browser_results(
        self,
    ) -> dict[str, Any]:
        return self.require_dict(
            self.browser_results_path,
            self.read_json(self.browser_results_path, {}),
        )

    def load_browser_response(
        self,
    ) -> dict[str, Any]:
        return self.require_dict(
            self.browser_response_path,
            self.read_json(self.browser_response_path, {}),
        )

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
    ) -> list[dict[str, Any]]:
        terminal_indexes = [
            index
            for index, item in enumerate(queue)
            if item.get("status") in TERMINAL_QUEUE_STATUSES
        ]
        if len(terminal_indexes) > MAX_PERSISTED_TERMINAL_QUEUE_ITEMS:
            drop_indexes = set(
                terminal_indexes[:-MAX_PERSISTED_TERMINAL_QUEUE_ITEMS]
            )
            queue[:] = [
                item
                for index, item in enumerate(queue)
                if index not in drop_indexes
            ]
        self.write_json(
            self.queue_path,
            queue,
        )
        return queue

    @staticmethod
    def _terminal_response_filename(operation_id: str) -> str:
        if not isinstance(operation_id, str) or not operation_id.strip():
            raise ValueError("operation_id must be a nonblank string")
        digest = hashlib.sha256(operation_id.encode("utf-8")).hexdigest()
        return f"{digest}.json"

    def _terminal_response_path(self, operation_id: str) -> Path:
        return self.terminal_responses_dir / self._terminal_response_filename(operation_id)

    def save_terminal_response(
        self,
        operation_id: str,
        response_text: str,
    ) -> None:
        if not isinstance(response_text, str):
            raise ValueError("terminal response must be a string")
        self.write_json(
            self._terminal_response_path(operation_id),
            {
                "operation_id": operation_id,
                "response_text": response_text,
            },
        )

    def load_terminal_response(
        self,
        operation_id: str,
    ) -> str | None:
        path = self._terminal_response_path(operation_id)
        value = self.read_json(path, None)
        if value is None:
            return None
        if (
            not isinstance(value, dict)
            or value.get("operation_id") != operation_id
            or not isinstance(value.get("response_text"), str)
        ):
            raise StateCorruptionError(
                f"Invalid state shape for {path}: expected terminal response record"
            )
        return value["response_text"]

    def prune_terminal_responses(
        self,
        retained_operation_ids: set[str],
    ) -> None:
        if not self.terminal_responses_dir.exists():
            return
        retained_files = {
            self._terminal_response_filename(operation_id)
            for operation_id in retained_operation_ids
        }
        for path in self.terminal_responses_dir.glob("*.json"):
            if path.name in retained_files:
                continue
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    def load_queue(
        self,
    ) -> list[dict[str, Any]]:
        return self.require_list(
            self.queue_path,
            self.read_json(self.queue_path, []),
        )
