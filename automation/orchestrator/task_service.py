from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from typing import Protocol

from .task_runner import BoundedTaskRunner, TaskRunResult


class TaskRunFactory(Protocol):
    """Application composition seam for constructing a fully wired task runner."""

    def create(self, *, runner_id: str, prompt: str) -> BoundedTaskRunner: ...


@dataclass(frozen=True)
class TaskSubmission:
    runner_id: str
    prompt: str


class TaskService:
    """Application-level lifecycle service around the bounded task runner.

    The service owns concurrency and submission/status plumbing, while the
    factory owns provider/adapters/goals. This keeps the runner testable and
    prevents the HTTP/UI/GitHub ingress layers from constructing execution
    components ad hoc.
    """

    def __init__(self, factory: TaskRunFactory) -> None:
        self.factory = factory
        self._lock = threading.RLock()
        self._runners: dict[str, BoundedTaskRunner] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._results: dict[str, TaskRunResult] = {}

    def submit(self, prompt: str, *, runner_id: str | None = None) -> TaskSubmission:
        prompt = prompt.strip()
        if not prompt:
            raise ValueError("prompt must be non-empty")
        selected_id = runner_id or f"task-{uuid.uuid4().hex}"
        if not selected_id.strip() or any(char in selected_id for char in "/\\"):
            raise ValueError("runner_id must be a path-safe identifier")

        with self._lock:
            if selected_id in self._runners:
                raise ValueError(f"task runner {selected_id!r} is already registered")
            runner = self.factory.create(runner_id=selected_id, prompt=prompt)
            self._runners[selected_id] = runner
            thread = threading.Thread(
                target=self._run,
                args=(selected_id, runner),
                name=f"pasi-task-{selected_id}",
                daemon=True,
            )
            self._threads[selected_id] = thread
            thread.start()
        return TaskSubmission(runner_id=selected_id, prompt=prompt)

    def status(self, runner_id: str) -> object:
        with self._lock:
            runner = self._runners.get(runner_id)
            if runner is None:
                raise KeyError(runner_id)
            return runner.state

    def result(self, runner_id: str) -> TaskRunResult | None:
        with self._lock:
            return self._results.get(runner_id)

    def approve(self, runner_id: str) -> object:
        with self._lock:
            runner = self._require_runner(runner_id)
            state = runner.approve_pending_action()
            self._start_thread_if_needed(runner_id, runner)
            return state

    def reset(self, runner_id: str) -> object:
        with self._lock:
            runner = self._require_runner(runner_id)
            self._results.pop(runner_id, None)
            return runner.reset()

    def _run(self, runner_id: str, runner: BoundedTaskRunner) -> None:
        try:
            result = runner.run()
        except Exception as exc:
            # The runner itself is fail-closed; retain the exception for the
            # application boundary rather than allowing a daemon thread to die
            # without an observable outcome.
            result = TaskRunResult(
                phase="failed",
                steps=runner.state.steps,
                reason=f"task service worker crashed: {exc}",
            )
        with self._lock:
            self._results[runner_id] = result
            self._threads.pop(runner_id, None)

    def _start_thread_if_needed(self, runner_id: str, runner: BoundedTaskRunner) -> None:
        existing = self._threads.get(runner_id)
        if existing is not None and existing.is_alive():
            return
        thread = threading.Thread(
            target=self._run,
            args=(runner_id, runner),
            name=f"pasi-task-{runner_id}",
            daemon=True,
        )
        self._threads[runner_id] = thread
        thread.start()

    def _require_runner(self, runner_id: str) -> BoundedTaskRunner:
        runner = self._runners.get(runner_id)
        if runner is None:
            raise KeyError(runner_id)
        return runner


__all__ = ["TaskRunFactory", "TaskService", "TaskSubmission"]
